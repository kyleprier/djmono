#!/usr/bin/env python3
"""djmono: curate crates on the Mac, render them for the Digitakt II, sync, and dial kits in over MIDI.

  crates/<WORLD>/<FN>.txt   ->  +Drive /<WORLD>/<FN>/          (the repo mirrors the device)
  presets/, kits/, projects/->  the rig: sounds, kits and the TRIAD project as plain text
  config/paths.local        ->  where the sample library lives on this machine (never in git)
  config/midi.txt           ->  how the loader talks to the DT2
  build/drive/              ->  rendered 16-bit / 48 kHz WAVs, ready to send
  state/drive.lock          ->  what was built, from what, and when it reached the device
  state/slots.txt           ->  which RAM slot holds which sample in TRIAD

Python 3.9+ and `sox`. `elektroid-cli` for sync if installed, otherwise Elektron Transfer.
MIDI (load, browse) uses mido + python-rtmidi from .venv (see ./djmono doctor).
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import fnmatch
import functools
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRATES = ROOT / "crates"
BUILD = ROOT / "build"
DRIVE = BUILD / "drive"
CACHE = BUILD / ".cache.json"
LOCK = ROOT / "state" / "drive.lock"
SLOTS = ROOT / "state" / "slots.txt"
INDEX = ROOT / "index"
CONFIG = ROOT / "config"
BACKUPS = ROOT / "backups"

# --- Device facts (Digitakt II, OS 1.16) ------------------------------------------------
MB = 1_000_000
PROJECT_RAM, PROJECT_SLOTS = 400 * MB, 1016          # per project
# TRIAD holds every world in one project: 390 MB, 7 of the 8 RAM banks (127 slots each); H stays free
BUDGET = {"CORE": (30 * MB, 127), "DUB": (110 * MB, 254), "RITE": (110 * MB, 381), "DRIFT": (140 * MB, 127)}
TRANSFER_MIB_S = 0.5                                 # measured over USB-MIDI (Transfer and Elektroid)
MAX_TRANSFER_BYTES = 59 * MB                         # community-tested per-file ceiling
MAX_NAME = 32

WORLDS = ("CORE", "DUB", "RITE", "DRIFT")
AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac"}

# --- Processing profiles, chosen by function folder ---------------------------------------
PROFILES = {
    "hit":  dict(mono=True,  trim=True,  len=4,   fade=15,  norm=-1.0),
    "tone": dict(mono=False, trim=True,  len=8,   fade=40,  norm=-1.0),
    "ring": dict(mono=False, trim=True,  len=15,  fade=150, norm=-1.0),
    "bed":  dict(mono=False, trim=False, len=20,  fade=200, norm=-3.0),
    "loop": dict(mono=False, trim=False, len=300, fade=0,   norm=-1.0),
}
FUNCTIONS = {
    "KICK": "hit", "SNR": "hit", "HAT": "hit", "HAND": "hit", "SHKR": "hit", "WOOD": "hit",
    "BELL": "ring", "FX": "ring", "GTR": "ring",
    "BASS": "tone", "STAB": "tone", "KEYS": "tone", "HORN": "tone", "VOX": "tone",
    "PAD": "bed", "SCAPE": "bed", "NOISE": "bed",
    "LOOP": "loop", "CHAIN": "loop",
}
# Folders inside sample packs that hold DAW/sampler formats (duplicates of the WAVs). Skipped.
FORMAT_WORDS = ("ableton", "kontakt", "exs", "exs24", "logic", "reason", "nn xt", "nnxt", "sfz",
                "maschine", "battery", "mpc", "fl studio", "flstudio", "apple loops", "__macosx")
KITS_DIR = re.compile(r"^(\d+\.? )?kits$")  # SFM "Kits" folders repeat the individual hits
DEFAULT_PREFER = "color"  # SFM ships clean + color (tape/tube) takes; keep color unless a rule says prefer=clean or prefer=any
OPTION_KEYS = {"limit", "pick", "prefer", "exclude", "code", "name", "keepname", "raw", "strip", "drop",
               "mono", "stereo", "len", "fade", "norm", "trim", "notrim"}


# --- small helpers -----------------------------------------------------------------------
def die(msg):
    sys.exit(f"djmono: {msg}")


def norm(s):
    s = s.lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm_path(p):
    return "/".join(norm(seg) for seg in p.split("/"))


def is_glob(p):
    return "*" in p or "?" in p


def slug(s):
    s = s.lower().replace("#", "s")
    s = re.sub(r"from[\s_-]*mars", " ", s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def fmt_mb(b):
    return f"{b / MB:,.1f} MB"


def transfer_minutes(b):
    return b / (TRANSFER_MIB_S * 1024 * 1024) / 60


def rel(p):
    try:
        return str(Path(p).relative_to(ROOT))
    except ValueError:
        return str(p)


# --- config ------------------------------------------------------------------------------
def load_paths(required=True):
    p = CONFIG / "paths.local"
    if not p.exists():
        if required:
            die("config/paths.local is missing. Run ./djmono doctor")
        return {}
    roots = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        roots[k.strip()] = Path(os.path.expanduser(v.strip()))
    return roots


def load_codes():
    codes = {}
    p = CONFIG / "codes.txt"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                codes[norm(parts[1])] = parts[0]
    return codes


# --- sources -----------------------------------------------------------------------------
class SrcFile:
    __slots__ = ("key", "rel", "norm", "size", "abs")

    def __init__(self, key, relpath, size, absroot):
        self.key, self.rel, self.size = key, relpath, size
        self.norm = norm_path(relpath)
        self.abs = (absroot / relpath) if absroot else None

    @property
    def sid(self):
        return f"{self.key}:{self.rel}"


@functools.lru_cache(maxsize=None)
def _skip_dir(name):
    if name[:1] in ".@#":  # hidden, Synology @eaDir / #recycle / #snapshot
        return True
    if "mars" in name.lower():  # a pack folder, e.g. "MPC60 From Mars", is never a format folder
        return False
    n = norm(name)
    if n.startswith("mpc"):  # "MPC1000 & MPC2500", "MPC Live"
        return True
    padded = f" {n} "
    return any(f" {w} " in padded for w in FORMAT_WORDS)


def keep_file(relpath):
    parts = relpath.split("/")
    name = parts[-1]
    if name.startswith(".") or os.path.splitext(name)[1].lower() not in AUDIO_EXT:
        return False
    return not any(_skip_dir(d) for d in parts[:-1])


def walk_source(root, label=""):
    out, dirs, tty = [], 0, sys.stderr.isatty()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d))
        dirs += 1
        for f in sorted(filenames):
            if f.startswith(".") or Path(f).suffix.lower() not in AUDIO_EXT:
                continue
            full = Path(dirpath) / f
            try:
                size = full.stat().st_size
            except OSError:
                continue
            out.append((str(full.relative_to(root)), size))
        if tty and dirs % 25 == 0:
            print(f"\r  scanning {label}: {len(out):,} files in {dirs:,} folders", end="", file=sys.stderr, flush=True)
    if tty:
        print("\r" + " " * 70 + "\r", end="", file=sys.stderr, flush=True)
    return out


_INDEX_CACHE = {}


def read_index(path):
    if str(path) in _INDEX_CACHE:
        return _INDEX_CACHE[str(path)]
    items = _INDEX_CACHE[str(path)] = []
    with open(path, encoding="utf-8", errors="surrogateescape") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            r, tab, sz = line.rpartition("\t")
            if not tab:
                r, sz = line, "0"
            if keep_file(r):
                items.append((r, int(sz or 0)))
    return items


def nested_in(child, parent):
    try:
        return child != parent and child.resolve().is_relative_to(parent.resolve())
    except (AttributeError, OSError):  # Python 3.8 has no is_relative_to
        return str(child).startswith(str(parent).rstrip("/") + "/")


class Library:
    """Reads index/<key>.tsv (fast; the NAS is slow to walk). A source nested inside another
    (sfm inside lib) reads the parent's index. Walks the disk only when there is no index."""

    def __init__(self, roots):
        self.roots, self._files, self._tops, self.missing = roots, {}, {}, set()

    def by_top(self, key):
        """Files grouped by their pack folder, so an anchored rule only looks inside its pack."""
        if key not in self._tops:
            self._tops[key] = {}
            for f in self.files(key):
                self._tops[key].setdefault(f.norm.split("/", 1)[0], []).append(f)
        return self._tops[key]

    def _from_index(self, key):
        idx = INDEX / f"{key}.tsv"
        if idx.exists():
            return read_index(idx)
        root = self.roots.get(key)
        for pkey, proot in self.roots.items():
            if root and pkey != key and nested_in(root, proot) and (INDEX / f"{pkey}.tsv").exists():
                prefix = str(root.relative_to(proot)) + "/"
                return [(r[len(prefix):], s) for r, s in read_index(INDEX / f"{pkey}.tsv") if r.startswith(prefix)]
        return None

    def files(self, key):
        if key in self._files:
            return self._files[key]
        root = self.roots.get(key)
        online = bool(root and root.is_dir())
        items = self._from_index(key)
        if items is None and online:
            items = walk_source(root, key)
        absroot = root if online else None
        if items is None:
            if key not in self.missing:
                where = f" at {root}" if root else " in config/paths.local"
                nas = " (NAS not mounted?)" if root and str(root).startswith("/Volumes/") else ""
                print(f"  warn  source '{key}' not found{where}{nas}; its rules are skipped")
            self.missing.add(key)
            return []
        if not items and not online:
            self.missing.add(key)
        self._files[key] = [SrcFile(key, r, s, absroot) for r, s in items]
        return self._files[key]

    def online(self, key):
        root = self.roots.get(key)
        return bool(root and root.is_dir())


# --- crates ------------------------------------------------------------------------------
class Rule:
    def __init__(self, crate, line_no, src, pattern, opts):
        self.crate, self.line_no, self.src, self.pattern, self.opts = crate, line_no, src, pattern, opts

    def where(self):
        return f"{rel(self.crate)}:{self.line_no}"


def parse_opts(s, where):
    opts = {}
    for tok in s.split():
        k, eq, v = tok.partition("=")
        if k not in OPTION_KEYS:
            die(f"{where}: unknown option '{k}'. Known: {', '.join(sorted(OPTION_KEYS))}")
        opts[k] = v if eq else True
    for k in ("limit", "len", "fade", "strip"):
        if k in opts:
            try:
                opts[k] = int(opts[k])
            except (TypeError, ValueError):
                die(f"{where}: {k} needs a whole number")
    if "norm" in opts:
        try:
            opts["norm"] = float(opts["norm"])
        except (TypeError, ValueError):
            die(f"{where}: norm needs a number (dBFS), e.g. norm=-1")
    return opts


def parse_crate(path):
    rules = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        spec, _, optstr = s.partition("|")
        src, sep, pattern = spec.strip().partition(":")
        if not sep or not pattern.strip():
            die(f"{rel(path)}:{i}: expected  source:path/or/glob  [| options]")
        rules.append(Rule(path, i, src.strip(), pattern.strip(), parse_opts(optstr, f"{rel(path)}:{i}")))
    return rules


def crate_files(selector=None):
    files = sorted(CRATES.glob("*/*.txt"))
    for f in files:
        world, fn = f.parent.name, f.stem
        if world not in WORLDS:
            die(f"{rel(f)}: world folder must be one of {', '.join(WORLDS)}")
        if fn not in FUNCTIONS:
            die(f"{rel(f)}: function must be one of {', '.join(FUNCTIONS)}")
    if selector:
        sel = selector.strip("/").upper()
        files = [f for f in files if f"{f.parent.name}/{f.stem}" == sel or f.parent.name == sel]
        if not files:
            die(f"no crate matches '{selector}' (use WORLD or WORLD/FN, e.g. DUB/CHRD)")
    return files


def resolve(rule, lib, ignore_limit=False):
    files = lib.files(rule.src)
    if is_glob(rule.pattern):
        g = norm_path(rule.pattern)
        # anchored at the source root first; anywhere below only if that finds nothing
        # (keeps "Essential WAV From Mars/.../Junos From Mars" copies out of a JUNOS rule)
        top = g.split("/", 1)[0]
        pool = lib.by_top(rule.src).get(top, []) if "/" in g and not is_glob(top) else files
        anchored = re.compile(fnmatch.translate(g)).match
        anywhere = re.compile(fnmatch.translate("*/" + g)).match
        hits = [f for f in pool if anchored(f.norm)] or [f for f in files if anywhere(f.norm)]
    else:
        hits = [f for f in files if f.rel == rule.pattern] or \
               [f for f in files if f.norm == norm_path(rule.pattern)]
    if "exclude" in rule.opts:
        pats = [norm_path(p) for p in str(rule.opts["exclude"]).split(",") if p]
        hits = [f for f in hits if not any(fnmatch.fnmatchcase(f.norm, "*" + p + "*") for p in pats)]
    prefer = str(rule.opts.get("prefer", DEFAULT_PREFER))
    if prefer != "any":
        words = [norm(w) for w in prefer.split(",") if w]
        # folders only: SFM splits clean/color by folder; a filename that says "color" doesn't count
        pref = [f for f in hits if any(re.search(rf"\b{re.escape(w)}\b", f.norm.rsplit("/", 1)[0]) for w in words)]
        hits = pref or hits
    hits.sort(key=lambda f: f.rel.lower())
    limit = rule.opts.get("limit")
    # round-robin copies ("... C3_0001") when the plain take is also there
    stems = {f.norm.rsplit(".", 1)[0] for f in hits}
    hits = [f for f in hits if not (re.search(r" 0\d{3}$", f.norm.rsplit(".", 1)[0]) and
                                    re.sub(r" 0\d{3}$", "", f.norm.rsplit(".", 1)[0]) in stems)]
    if "kit" not in rule.pattern.lower():
        hits = [f for f in hits if not any(KITS_DIR.match(seg) for seg in f.norm.split("/")[:-1])]
    if limit and not ignore_limit and len(hits) > limit:
        if rule.opts.get("pick") == "first":
            hits = hits[:limit]
        else:  # spread: evenly across the sorted matches, for variety
            n = len(hits)
            idx = sorted({round(i * (n - 1) / (limit - 1)) for i in range(limit)}) if limit > 1 else [n // 2]
            hits = [hits[i] for i in idx]
    return hits


# --- naming ------------------------------------------------------------------------------
NOTE_TAIL = re.compile(r"-([a-g]s?-?\d)$")


def source_code(f, codes):
    for seg in f.rel.split("/")[:-1]:
        c = codes.get(norm(seg))
        if c:
            return c, seg
    first = f.rel.split("/")[0]
    return (re.sub(r"[^a-z0-9]", "", first.lower())[:4] or "src"), first


NOTE_TOK = re.compile(r"[a-g]s?\d")


def describe(stem, code, fn, pack_seg):
    """The useful words of a pack filename: '60 E Piano Mirage C3' -> e-piano-c3,
    'Djembe Hi Flam Reserve' -> djembe-hi-flam, '36_Hover_SH101_C1-8UFY' -> hover-c1."""
    parts = [p for p in slug(stem).split("-") if p]
    if len(parts) >= 2 and NOTE_TOK.fullmatch(parts[-2]) and (
            re.fullmatch(r"0\d{3}", parts[-1]) or
            (re.fullmatch(r"[a-z0-9]{4}", parts[-1]) and re.search(r"\d", parts[-1]) and re.search(r"[a-z]", parts[-1]))):
        parts.pop()  # round-robin counter or random tag after the note
    if len(parts) > 1 and NOTE_TOK.fullmatch(parts[-1]):
        if parts[0].isdigit():
            parts.pop(0)  # MIDI note number in front: "60 E Piano ... C3"
        else:
            parts[0] = re.sub(r"^\d{1,3}(?=[a-z])", "", parts[0])  # "60HissMachine"
    pack_words = set(slug(pack_seg).split("-")) if pack_seg else set()
    redundant = {code, fn.lower()} | pack_words
    nums = [w for w in pack_words if w.isdigit() and len(w) >= 3]
    def said(tok):  # the prefix already says it (pack name, code, function, SH101 for 101)
        return tok in redundant or any(tok.endswith(n) and len(tok) - len(n) <= 3 for n in nums)
    return [p for p in parts if not said(p)] or parts[-1:]


def fit(base, maxlen=MAX_NAME):
    if len(base) <= maxlen:
        return base
    m = NOTE_TAIL.search(base)
    tail = m.group(0) if m else ""
    return base[: maxlen - len(tail)].rstrip("-_") + tail


def make_name(rule, f, fn, codes):
    stem = Path(f.rel).stem
    if "name" in rule.opts:
        return fit(slug(str(rule.opts["name"])))
    if rule.opts.get("keepname") or rule.src == "rec":
        own = re.sub(r"\s+", "_", stem.strip().lower())                  # your own names: trt_kick_roomy
        return fit(re.sub(r"[^a-z0-9_]+", "-", own).strip("-_"))
    code, pack_seg = rule.opts.get("code"), None
    if not code:
        code, pack_seg = source_code(f, codes)
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z][a-z])", " ", stem)  # FireDrumGhost -> Fire Drum Ghost
    if rule.opts.get("strip"):  # pack prefixes like "SKN_BO_"
        stem = " ".join(re.split(r"[_\s-]+", stem)[int(rule.opts["strip"]):])
    parts = describe(stem, code, fn, pack_seg)
    if "drop" in rule.opts:
        gone = {norm(w) for w in str(rule.opts["drop"]).split(",")}
        parts = [p for p in parts if p not in gone] or parts
    desc = "-".join(parts)
    return fit(f"{code}_{fn.lower()}_{desc or 'x'}")


def unique(name, taken):
    if name not in taken:
        return name
    for i in range(2, 1000):
        suffix = f"-{i}"
        cand = fit(name, MAX_NAME - len(suffix)) + suffix
        if cand not in taken:
            return cand
    die(f"could not find a free name for {name}")


# --- lock --------------------------------------------------------------------------------
LOCK_HEADER = "# path\tstatus\tsynced\tbytes\tsha256\tsource\n"


def read_lock():
    rows = {}
    if LOCK.exists():
        for line in LOCK.read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            p = line.split("\t")
            if len(p) >= 6:
                rows[p[0]] = dict(path=p[0], status=p[1], synced=p[2], bytes=int(p[3]), sha=p[4], source=p[5])
    return rows


def write_lock(rows):
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lines = [LOCK_HEADER] + [
        f"{r['path']}\t{r['status']}\t{r['synced']}\t{r['bytes']}\t{r['sha']}\t{r['source']}\n"
        for r in sorted(rows.values(), key=lambda r: r["path"])
    ]
    LOCK.write_text("".join(lines))


# --- render ------------------------------------------------------------------------------
def sox_args(src, dst, o):
    fx = []
    if o["mono"]:
        fx += ["remix", "-"]
    if o["trim"]:
        fx += ["silence", "1", "0.001", "-60d"]
    if o["len"]:
        fx += ["trim", "0", str(o["len"])]
    if o["fade"]:  # fade-in 2 ms; fade-out via reverse (length is unknown after `silence`)
        fx += ["fade", "t", "0.002", "reverse", "fade", "t", f"{o['fade'] / 1000:.3f}", "reverse"]
    fx += ["rate", "-v", "48000"]
    if o["norm"] is not None:
        fx += ["norm", str(o["norm"])]
    return ["sox", "-R", "-V1", str(src), "-b", "16", "-e", "signed-integer", str(dst)] + fx


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def render(job, cache):
    out, f, o = job["out"], job["file"], job["opts"]
    try:
        st = f.abs.stat()
    except OSError:
        return job["path"], None, f"{f.rel} is in the index but not on disk. Rerun ./djmono scan"
    sig = hashlib.sha1(json.dumps([str(f.abs), st.st_size, int(st.st_mtime), o], sort_keys=True).encode()).hexdigest()
    if out.exists() and cache.get(job["path"]) == sig:
        return job["path"], sig, None
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.wav")
    if o.get("raw"):
        shutil.copyfile(f.abs, tmp)
    else:
        r = subprocess.run(sox_args(f.abs, tmp, o), capture_output=True, text=True)
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            return job["path"], None, (r.stderr.strip() or "sox failed")
    os.replace(tmp, out)
    return job["path"], sig, None


# --- commands ----------------------------------------------------------------------------
def plan_build(lib, codes, lock, selector=None, quiet=False):
    """Resolve every crate into jobs. Names already on the device are reused so they never drift;
    names that were only built, never synced, are free to change."""
    lock = {p: r for p, r in lock.items() if r["synced"] != "-"}
    by_source = {(r["path"].rsplit("/", 1)[0], r["source"]): r["path"] for r in lock.values()}
    jobs, seen, warnings = [], {}, []
    for crate in crate_files(selector):
        world, fn = crate.parent.name, crate.stem
        folder = f"{world}/{fn}"
        base = dict(PROFILES[FUNCTIONS[fn]])
        taken = {p.rsplit("/", 1)[1] for p in lock if p.rsplit("/", 1)[0] == folder}
        planned = set()
        for rule in parse_crate(crate):
            hits = resolve(rule, lib)
            if not quiet:
                print(f"  {rule.where():<28} {len(hits):>4}  {rule.src}:{rule.pattern}")
            if not hits and rule.src not in lib.missing:
                warnings.append(f"{rule.where()}: matched nothing  ({rule.src}:{rule.pattern})")
            o = dict(base)
            for k in ("len", "fade", "norm"):
                if k in rule.opts:
                    o[k] = rule.opts[k]
            if rule.opts.get("mono"):
                o["mono"] = True
            if rule.opts.get("stereo"):
                o["mono"] = False
            if rule.opts.get("trim"):
                o["trim"] = True
            if rule.opts.get("notrim"):
                o["trim"] = False
            if rule.opts.get("raw"):
                o = {"raw": True}
            for f in hits:
                if f.sid in planned:
                    continue
                planned.add(f.sid)
                if f.sid in seen and seen[f.sid] != folder:
                    warnings.append(f"{f.sid} is in both {seen[f.sid]} and {folder}; shared samples belong in CORE")
                seen[f.sid] = folder
                path = by_source.get((folder, f.sid))
                if not path:
                    name = unique(make_name(rule, f, fn, codes), taken)
                    path = f"{folder}/{name}"
                taken.add(path.rsplit("/", 1)[1])
                jobs.append(dict(path=path, file=f, opts=o, out=DRIVE / f"{path}.wav"))
    return jobs, warnings


def budget_report(rows):
    per = {}
    for r in rows:
        w = r["path"].split("/")[0]
        b, n = per.get(w, (0, 0))
        per[w] = (b + r["bytes"], n + 1)
    print(f"\n  {'world':<7}{'files':>7}{'size':>12}   TRIAD budget (all worlds in one project)")
    over = False
    for w in WORLDS:
        b, n = per.get(w, (0, 0))
        cap_b, cap_n = BUDGET[w]
        flag = ""
        if b > cap_b or n > cap_n:
            flag, over = "  << over budget", True
        print(f"  {w:<7}{n:>7}{fmt_mb(b):>12}   {100 * b / cap_b:5.0f}% of {fmt_mb(cap_b)}, {n}/{cap_n} files{flag}")
    total, count = sum(b for b, _ in per.values()), sum(n for _, n in per.values())
    print(f"  {'total':<7}{count:>7}{fmt_mb(total):>12}   {100 * total / PROJECT_RAM:5.0f}% of the 400 MB project, "
          f"{count}/{PROJECT_SLOTS} slots, ~{transfer_minutes(total):.0f} min over USB")
    return over


def estimate_bytes(job):
    """Rendered size before rendering: 16-bit / 48 kHz from the source size (assumes 24-bit stereo sources)."""
    o, f = job["opts"], job["file"]
    if o.get("raw"):
        return f.size
    secs = f.size / (44100 * 3 * 2) if f.size else 2.0
    if o.get("len"):
        secs = min(secs, o["len"])
    return int(secs * 48000 * 2 * (1 if o.get("mono") else 2)) + 44


def cmd_build(args):
    if not shutil.which("sox"):
        die("sox not found. brew install sox")
    lib, codes, lock = Library(load_paths()), load_codes(), read_lock()
    print("resolving crates")
    jobs, warnings = plan_build(lib, codes, lock, args.crate)
    if lib.missing:  # never rewrite the lock from a partial view of the library
        die(f"source(s) {', '.join(sorted(lib.missing))} unreachable (NAS not mounted?). Nothing was changed")
    missing = sorted({j["file"].key for j in jobs if j["file"].abs is None})
    if missing:
        die(f"source(s) {', '.join(missing)} are offline (NAS not mounted?). ls works from the index; build needs the files")

    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    errors, done = [], 0
    print(f"\nrendering {len(jobs)} samples")
    with cf.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        for path, sig, err in ex.map(lambda j: render(j, cache), jobs):
            done += 1
            if err:
                errors.append(f"{path}: {err}")
            else:
                cache[path] = sig
            if sys.stdout.isatty():
                print(f"\r  {done}/{len(jobs)}", end="", flush=True)
    print()
    BUILD.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True))
    ok_jobs = [j for j in jobs if j["out"].exists() and not any(e.startswith(j["path"] + ":") for e in errors)]

    # rows for the lock; identical audio within a folder is dropped
    rows, seen_sha = {}, {}
    for j in ok_jobs:
        sha = sha256(j["out"])
        folder = j["path"].rsplit("/", 1)[0]
        if (folder, sha) in seen_sha:
            j["out"].unlink()
            warnings.append(f"{j['file'].sid}: same audio as {seen_sha[(folder, sha)]}, skipped")
            continue
        seen_sha[(folder, sha)] = j["path"]
        size = j["out"].stat().st_size
        if size > MAX_TRANSFER_BYTES:
            warnings.append(f"{j['path']}: {fmt_mb(size)} is above the ~59 MB transfer ceiling; shorten with len=")
        old = lock.get(j["path"])
        synced = old["synced"] if old else "-"
        if old and old["synced"] != "-" and old["sha"] != sha:
            warnings.append(f"{j['path']}: audio changed after it was synced. The device keeps the old file; "
                            f"give this one a new name (name=) if you want both")
        rows[j["path"]] = dict(path=j["path"], status="active", synced=synced, bytes=size, sha=sha, source=j["file"].sid)

    if args.crate:  # partial build: keep lock rows for crates we didn't touch
        touched = {f"{c.parent.name}/{c.stem}" for c in crate_files(args.crate)}
        for p, r in lock.items():
            if p.rsplit("/", 1)[0] not in touched:
                rows.setdefault(p, r)
    for p, r in lock.items():  # still on the device but no longer in a crate
        if p not in rows and r["synced"] != "-":
            rows[p] = dict(r, status="retired")
    write_lock(rows)

    # keep build/drive an exact mirror of the active set
    active = {f"{p}.wav" for p, r in rows.items() if r["status"] == "active"}
    for f in DRIVE.rglob("*.wav"):
        if str(f.relative_to(DRIVE)) not in active:
            f.unlink()

    budget_report([r for r in rows.values() if r["status"] == "active"])
    unsynced = [r for r in rows.values() if r["status"] == "active" and r["synced"] == "-"]
    if unsynced:
        b = sum(r["bytes"] for r in unsynced)
        print(f"\n  {len(unsynced)} new files ({fmt_mb(b)}, ~{transfer_minutes(b):.0f} min) waiting for ./djmono sync")
    for w in warnings:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    if errors:
        sys.exit(1)


def cmd_ls(args):
    lib = Library(load_paths(required=False))
    for crate in crate_files(args.crate):
        world, fn = crate.parent.name, crate.stem
        print(f"\n{world}/{fn}  ({FUNCTIONS[fn]})")
        for rule in parse_crate(crate):
            hits = resolve(rule, lib, ignore_limit=args.all)
            print(f"  line {rule.line_no:<4}{len(hits):>5}  {rule.src}:{rule.pattern}")
            if args.verbose:
                for f in hits:
                    print(f"          {f.rel}")
    if args.verbose:
        return
    print("\n(-v lists files, --all ignores limit=)")


def cmd_status(args):
    rows = list(read_lock().values())
    if not rows:
        print("nothing built yet. ./djmono build")
        return
    active = [r for r in rows if r["status"] == "active"]
    budget_report(active)
    unsynced = [r for r in active if r["synced"] == "-"]
    retired = [r for r in rows if r["status"] == "retired"]
    b = sum(r["bytes"] for r in unsynced)
    print(f"\n  waiting to sync: {len(unsynced)} files, {fmt_mb(b)}, ~{transfer_minutes(b):.0f} min")
    if retired:
        print(f"  retired (on the device, no longer in a crate): {len(retired)}")
        for r in retired:
            print(f"    {r['path']}")
        print("  Delete these on the DT2 only once no preset or project uses them.")


def elektroid(*a):
    return subprocess.run(["elektroid-cli", *a], capture_output=True, text=True)


def find_device():
    if os.environ.get("DJMONO_DEVICE"):
        return os.environ["DJMONO_DEVICE"]
    r = elektroid("ld")
    for line in r.stdout.splitlines():
        if "digitakt" in line.lower():
            m = re.match(r"\s*(\d+)", line)
            if m:
                return m.group(1)
    die("no Digitakt II in `elektroid-cli ld`. Check USB, quit Transfer (it holds the MIDI port), "
        "or set DJMONO_DEVICE=<id>. Use ./djmono sync --transfer to go through Transfer instead")


def device_names(dev, folder):
    r = elektroid("elektron:sample:ls", f"{dev}:/{folder}")
    if r.returncode != 0:
        return None
    names = set()
    for line in r.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0] != "D":
            names.add(parts[3].strip())
    return names


def cmd_sync(args):
    rows = read_lock()
    todo = [r for r in rows.values() if r["status"] == "active" and r["synced"] == "-"]
    if not todo:
        print("device is up to date.")
        return
    missing = [r for r in todo if not (DRIVE / f"{r['path']}.wav").exists()]
    if missing:
        die(f"{len(missing)} files in the lock are missing from build/drive. Run ./djmono build first")
    b = sum(r["bytes"] for r in todo)
    print(f"{len(todo)} files, {fmt_mb(b)}, ~{transfer_minutes(b):.0f} min over USB")
    today = dt.date.today().isoformat()

    use_transfer = args.transfer or not shutil.which("elektroid-cli")
    if use_transfer:
        if args.dry_run:
            for r in todo:
                print(f"  would stage  {r['path']}")
            return
        shutil.rmtree(BUILD / "transfer", ignore_errors=True)  # only the latest stage matters
        stage = BUILD / "transfer" / dt.datetime.now().strftime("%y%m%d-%H%M")
        for r in todo:
            dst = stage / f"{r['path']}.wav"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(DRIVE / f"{r['path']}.wav", dst)
        print(f"\nstaged for Transfer: {rel(stage)}")
        for w in WORLDS:
            items = [r for r in todo if r["path"].startswith(w + "/")]
            if items:
                print(f"  {w + '/':<8}{len(items):>5} files  {fmt_mb(sum(r['bytes'] for r in items)):>10}")
        print("\nIn Transfer, open the +Drive sample browser and drag each world folder above onto the root.\n"
              "Folder paths are kept. If a folder already exists and Transfer won't merge, open it and drop\n"
              "the files from the matching subfolder instead.")
        if sys.platform == "darwin":
            subprocess.run(["open", str(stage)])
        ok = args.yes or input(f"\nMark these {len(todo)} files as synced? [y/N] ").strip().lower() == "y"
        if ok:
            for r in todo:
                r["synced"] = today
            write_lock(rows)
            print("lock updated. Commit state/drive.lock.")
        return

    dev = find_device()
    by_folder = {}
    for r in todo:
        by_folder.setdefault(r["path"].rsplit("/", 1)[0], []).append(r)
    sent = 0
    for folder, items in sorted(by_folder.items()):
        present = device_names(dev, folder)
        if present is None and not args.dry_run:
            r = elektroid("elektron:sample:mkdir", f"{dev}:/{folder}")
            if r.returncode != 0:
                die(f"mkdir {folder} failed: {r.stderr.strip()}")
            present = set()
        present = present or set()
        for r in items:
            name = r["path"].rsplit("/", 1)[1]
            if name in present:
                print(f"  have  {r['path']}")
                r["synced"] = today
                continue
            if args.dry_run:
                print(f"  would send  {r['path']}")
                continue
            res = elektroid("elektron:sample:ul", str(DRIVE / f"{r['path']}.wav"), f"{dev}:/{folder}")
            if res.returncode != 0:
                write_lock(rows)
                die(f"upload failed at {r['path']}: {res.stderr.strip()}. Progress so far is saved; rerun to resume")
            r["synced"] = today
            sent += 1
            print(f"  sent  {r['path']}")
            if sent % 20 == 0:
                write_lock(rows)
    if not args.dry_run:
        write_lock(rows)
        print(f"\n{sent} sent. Commit state/drive.lock.")


def cmd_scan(args):
    roots = load_paths()
    keys = [args.source] if args.source else sorted(roots)
    if args.only and not args.source:
        keys = ["lib"]
    INDEX.mkdir(exist_ok=True)
    for k in keys:
        root = roots.get(k)
        if not root or not root.is_dir():
            print(f"  skip {k}: {root} not found")
            continue
        if args.only:  # rescan one pack folder and merge it into the existing index
            sub = root / args.only
            if not sub.is_dir():
                print(f"  skip {k}: {sub} not found")
                continue
            idx = INDEX / f"{k}.tsv"
            prefix = args.only.strip("/") + "/"
            old = [(r, s) for r, s in (read_index(idx) if idx.exists() else []) if not r.startswith(prefix)]
            new = [(prefix + r, s) for r, s in walk_source(sub, args.only)]
            items = sorted(old + new)
            with open(idx, "w", encoding="utf-8", errors="surrogateescape") as fh:
                fh.write(f"# {k}: {len(items)} audio files, scanned {dt.date.today().isoformat()} (relative path, bytes)\n")
                for r, s in items:
                    fh.write(f"{r}\t{s}\n")
            print(f"  {k}/{args.only}: {len(new):,} files merged -> index/{k}.tsv")
            continue
        parent = next((pk for pk, pr in roots.items() if pk != k and pr.is_dir() and nested_in(root, pr)), None)
        if parent and not args.source:
            (INDEX / f"{k}.tsv").unlink(missing_ok=True)
            print(f"  {k}: inside {parent}, covered by index/{parent}.tsv")
            continue
        items = walk_source(root, k)
        with open(INDEX / f"{k}.tsv", "w", encoding="utf-8", errors="surrogateescape") as fh:
            fh.write(f"# {k}: {len(items)} audio files, scanned {dt.date.today().isoformat()} (relative path, bytes)\n")
            for r, s in items:
                fh.write(f"{r}\t{s}\n")
        print(f"  {k}: {len(items):,} files -> index/{k}.tsv")
    print("Commit index/. Rescan after adding packs; ls/build/audition read the index, not the NAS.")


def planned_samples():
    """Every sample the crates produce, with its size: real if built, estimated if not. Works from the index."""
    lib, lock = Library(load_paths(required=False)), read_lock()
    jobs, _ = plan_build(lib, load_codes(), lock, quiet=True)
    out = {}
    for j in jobs:
        row = lock.get(j["path"])
        out[j["path"]] = row["bytes"] if row and row["status"] == "active" else estimate_bytes(j)
    return out, lib.missing


def load_rig():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import rig
    return rig


def checked_rig():
    """The rig, checked against every sample the crates produce."""
    rig = load_rig()
    samples, missing = planned_samples()
    r = rig.Rig(ROOT).load().check(samples)
    return rig, r, samples, missing


def slot_map():
    import loader
    cfg = loader.read_midi_config(CONFIG / "midi.txt")
    return loader, cfg, loader.SlotMap(SLOTS, cfg["sort"])


def cmd_check(args):
    rig, r, samples, missing = checked_rig()
    if missing:
        print(f"  warn  no index or files for: {', '.join(sorted(missing))}")
    print(f"  {len(r.recipes)} recipes · {len(r.presets)} presets · {len(r.kits)} kits · {len(r.projects)} projects "
          f"· {len(samples)} samples\n")
    cov = r.coverage()
    for kind, roles in (("DRUMS", rig.DRUM_ROLES), ("TONES", rig.TONE_ROLES)):
        print(f"  {kind.lower():<12}" + "".join(f"{role:>9}" for role, *_ in roles))
        for bank in (b for b in rig.BANKS if rig.BANKS[b][1] == kind):
            print(f"  {bank} {rig.BANKS[bank][0]:<10}" + "".join(f"{f'{n}/{cap}':>9}" for _, n, cap in cov[bank]))
        print()
    for pname, proj in r.projects.items():
        for bank, kits in sorted(proj["banks"].items()):
            print(f"  {pname} {bank}: " + ", ".join(f"{kn} {r.kits[kn]['tempo']}" for kn in kits if kn in r.kits))
        print(f"  {pname}: {proj.get('slots', 0)} samples, {fmt_mb(proj.get('ram', 0))} of 400 MB, "
              f"{proj.get('slots', 0)}/{PROJECT_SLOTS} slots")
        if proj.get("ram", 0) > PROJECT_RAM or proj.get("slots", 0) > PROJECT_SLOTS:
            r.err(f"project {pname} doesn't fit one project")
    for w in r.warnings:
        print(f"  warn  {w}")
    for e in r.errors:
        print(f"  ERROR {e}")
    print("\ncomplete." if not r.errors else f"\n{len(r.errors)} problem(s).")
    if r.errors:
        sys.exit(1)


def cmd_sheet(args):
    rig, r, samples, _ = checked_rig()
    loader, cfg, sm = slot_map()
    slots = sm.of
    out = BUILD / "sheets"
    shutil.rmtree(out, ignore_errors=True)
    (out / "kits").mkdir(parents=True)
    written = []
    for pname in r.projects:
        f = out / f"1-project-{pname}.md"
        f.write_text(r.sheet_project(pname, sm.runs()))
        written.append(f)
    for name, k in sorted(r.kits.items(), key=lambda kv: (kv[1].get("pattern", "Z"), kv[0])):
        f = out / "kits" / f"{k.get('pattern', 'draft')}-{name.replace(' ', '-')}.md"
        f.write_text(r.sheet_kit(name, samples, slots))
        written.append(f)
    for bank in rig.BANKS:
        world, kind = rig.BANKS[bank]
        f = out / f"presets-{bank}-{world}-{kind}.md"
        f.write_text(r.sheet_bank(bank, slots))
        written.append(f)
    order = ["# Sheets", "",
             "1. `1-project-TRIAD.md`: new project, load the samples into RAM in the order given.",
             "2. `kits/`: one sheet per kit, named by pattern. Set the machines, `./djmono load \"KIT\"`, save the kit.",
             "3. `presets-*.md`: the preset library, bank by bank. Dial any of them onto a track with "
             "`./djmono load --preset \"B:NAME\" --track N`, or step through with `./djmono browse`.", ""]
    if not slots:
        order += ["RAM slots are blank until you run `./djmono slots`.", ""]
    (out / "README.md").write_text("\n".join(order + [f"- {rel(f)}" for f in written]) + "\n")
    print(f"{len(written)} sheets in {rel(out)}/  (start with README.md)")
    if r.errors:
        print(f"  {len(r.errors)} problem(s) found; run ./djmono check")
    if sys.platform == "darwin" and not getattr(args, "no_open", False):
        subprocess.run(["open", str(out)])


def cmd_slots(args):
    loader, cfg, sm = slot_map()
    lock = read_lock()
    # everything on the +Drive in djmono's folders, retired or not: "select all" loads what's there
    on_device = [p for p, row in lock.items() if row["synced"] != "-" and (row["status"] == "active" or not args.prune)]
    retired = [p for p in on_device if lock[p]["status"] == "retired"]
    pending = [p for p, row in lock.items() if row["status"] == "active" and row["synced"] == "-"]
    if not on_device:
        die("nothing is on the device yet (state/drive.lock). ./djmono build, then ./djmono sync")
    fresh = args.reset or not sm.slots
    if args.reset:
        sm.slots = {}
    try:
        added, dropped = sm.update(on_device)
    except ValueError as e:
        die(f"{e}. Trim that world's crates (./djmono status shows the budgets)")
    sm.save()
    if fresh:
        print(f"{len(sm.slots)} samples in the RAM plan ({rel(SLOTS)}). New project TRIAD, then load in this order:\n")
        for bank, world, runs in sm.runs():
            for folder, n, lo, hi in runs:
                print(f"  RAM {bank}  {bank}{lo:03d}-{bank}{hi:03d}  {n:>4}  /{folder}")
        print("\nIn SAMPLES > +DRIVE: open the folder, select all, FUNC + YES to pick the RAM bank, LOAD TO PROJECT.\n"
              "The project sheet (./djmono sheet) has the same list. Then ./djmono load --test.")
    else:
        if dropped:
            print("unloaded from the plan (unload these in PROJECT RAM if they're still there):")
            for slot, sample in dropped:
                print(f"  {slot}  {sample}")
        if added:
            print("load these, in this order, each into its RAM bank (select just these files):")
            for bank, world, runs in sm.runs(added):
                for folder, n, lo, hi in runs:
                    print(f"  RAM {bank}  {bank}{lo:03d}-{bank}{hi:03d}  {n:>4}  /{folder}")
        if not added and not dropped:
            print(f"RAM plan unchanged: {len(sm.slots)} samples.")
    if retired:
        print(f"\n{len(retired)} retired samples are still on the device and in the plan. To free their slots: delete "
              "them from the +Drive and unload them from PROJECT RAM, then ./djmono slots --prune")
    unbuilt = len(set(planned_samples()[0]) - set(lock))
    if pending or unbuilt:
        print(f"\n{len(pending) + unbuilt} samples in the crates aren't on the device yet: ./djmono build, "
              "./djmono sync, then ./djmono slots again")
    print(f"\nCommit {rel(SLOTS)} with state/drive.lock.")


def resolve_kit(r, name):
    kit = r.kits.get(name.upper().replace("-", " "))
    if not kit:
        close = [k for k in r.kits if name.upper() in k]
        die(f"no kit '{name}'" + (f"; did you mean {', '.join(close)}?" if close else f". Kits: {', '.join(sorted(r.kits))}"))
    return kit


def track_jobs(r, kit):
    """[(track, preset, machine, params)] for a kit."""
    jobs = []
    for trk in range(1, 17):
        t = kit["tracks"].get(trk)
        p = r.find(t["preset"]) if t else None
        if p:
            machine, params = r.sound(p, t.get("tweaks"))
            jobs.append((trk, p, machine, params))
    return jobs


def cmd_load(args):
    rig, r, samples, _ = checked_rig()
    loader, cfg, sm = slot_map()
    if args.test:
        return load_test(loader, cfg, sm, args)
    if args.preset:
        p = r.find(args.preset)
        if not p:
            close = [k for k in r.presets if args.preset.upper().split(":")[-1] in k]
            die(f"no preset '{args.preset}'" + (f"; close: {', '.join(close[:8])}" if close else ""))
        if not 1 <= args.track <= 16:
            die("--track 1-16")
        jobs = [(args.track, p, *r.sound(p))]
        kit = None
    elif args.kit:
        kit = resolve_kit(r, args.kit)
        bad = [e for e in r.errors if kit["where"] in e]
        if bad:
            die("this kit has problems:\n  " + "\n  ".join(bad))
        if args.fx:
            return load_fx(loader, cfg, kit, args)
        jobs = track_jobs(r, kit)
    else:
        die("say what to load: a kit name, --preset B:NAME --track N, or --test")
    slots = sm.of
    missing = sorted({p["sample"] for _, p, _, _ in jobs if p["sample"] not in slots})
    if missing:
        die(f"{len(missing)} samples have no RAM slot yet (e.g. {missing[0]}). ./djmono sync, then ./djmono slots, "
            "and load them into the project")
    if kit:
        print(f"{kit['name']} ({kit['world']}) · pattern {kit.get('pattern', '-')} · {kit['tempo']} BPM"
              + (f" · swing {kit['swing']}%" if kit["swing"] else ""))
    todo = [(t, m) for t, _, m, _ in jobs if m != "Oneshot"]
    print("\nOn the DT2 first: pick the pattern" + (f" {kit.get('pattern')}" if kit else "") +
          (", then set these machines (SRC page, FUNC + SRC):" if todo else "."))
    for t, m in todo:
        print(f"  track {t:>2}: {m.upper()}")
    if not args.yes and not args.dry_run:
        input("\nPress Enter to send... ")
    port = loader.Port(cfg, dry=args.dry_run)
    for trk, p, machine, params in jobs:
        slot = slots[p["sample"]]
        secs = loader.wav_seconds(DRIVE / f"{p['sample']}.wav")
        vals = loader.dial(port, trk, slot, machine, params, cfg, secs, p["sample"])
        grid = f" · grid {vals['grid']}" if "grid" in vals else ""
        print(f"  {trk:>2}  {p['bank']}{p['slot']:03d} {p['name']:<12}  {slot}  {p['sample'].split('/', 1)[1]}{grid}")
    port.close()
    print(f"\n{len(port.sent)} messages" + (" (dry run, nothing sent)" if args.dry_run else " sent."))
    hand = [(t, rig.Rig.manual(m, pr)) for t, _, m, pr in jobs]
    hand = [(t, [x for x in h if not x.startswith("machine")]) for t, h in hand]
    if any(h for _, h in hand):
        print("\nBy hand:")
        for t, h in hand:
            if h:
                print(f"  track {t:>2}: {'; '.join(h)}")
    if kit:
        print(f"\nTempo {kit['tempo']}" + (f", swing {kit['swing']}%" if kit["swing"] else "") + ". Kit FX:")
        print("\n".join(loader.fx_lines(kit["fx"])) or "  init")
        print(f"  (or ./djmono load \"{kit['name']}\" --fx to send them)")
        print(f"\nThen PRESET/KIT > SAVE (KIT) as {kit['name']}.")
        if kit["play"]:
            print(f"\nPlay it: {kit['play']}")


def load_fx(loader, cfg, kit, args):
    ch = int(cfg["fx_channel"])
    if not kit["fx"]:
        die("this kit has no FX settings")
    print(f"SETTINGS > MIDI CONFIG > CHANNELS: set TRACK {ch} to OFF and FX CONTROL CH to {ch} "
          f"(AUTO CHANNEL must not be {ch}).")
    if not args.yes and not args.dry_run:
        input("Press Enter when done... ")
    port = loader.Port(cfg, dry=args.dry_run)
    loader.send_fx(port, ch, kit["fx"])
    port.close()
    print("\n".join(loader.fx_lines(kit["fx"])))
    print(f"\n{len(port.sent)} messages" + (" (dry run, nothing sent)." if args.dry_run else
          f" sent. Now set TRACK {ch} back to {ch} and FX CONTROL CH back to OFF."))


def load_test(loader, cfg, sm, args):
    if not sm.slots:
        die("no RAM plan yet: ./djmono slots, and load the samples into TRIAD first")
    first = sorted(sm.slots.items())[0]
    second = next((kv for kv in sorted(sm.slots.items()) if kv[0][0] != first[0][0]), None)
    print("On the DT2: SETTINGS > MIDI CONFIG. PORT CONFIG: INPUT FROM = USB (or MIDI+USB), RECEIVE CC/NRPN on.\n"
          "CHANNELS: TRACK 1-16 on channels 1-16, FX CONTROL CH OFF. Use an empty pattern; track 1 on ONESHOT.")
    if not args.yes and not args.dry_run:
        input("Press Enter to send the test sound to track 1... ")
    port = loader.Port(cfg, dry=args.dry_run)
    loader.dial(port, 1, first[0], "Oneshot", loader.TEST_PARAMS, cfg)
    if second:
        loader.dial(port, 2, second[0], "Oneshot", {}, cfg)
    port.close()
    report = []

    def ask(page, expect):
        print(f"\n{page}: {expect}")
        if args.dry_run or args.yes:
            return
        ans = input("  matches? [Y/n, or type what you see] ").strip()
        if ans and ans.lower() not in ("y", "yes"):
            report.append(f"{page}: expected {expect}; saw {ans}")

    for page, expect in loader.TEST_SCREEN:
        ask(f"Track 1 {page}", expect.format(sample=f"{first[1].rsplit('/', 1)[1]} (slot {first[0]})"))
    if second:
        ask("Track 2 SRC", f"SMP shows {second[1].rsplit('/', 1)[1]} (slot {second[0]})")
    probes = sort_probes(sm)
    if probes:
        print("\nIn SAMPLES > +DRIVE the loaded samples show their slot. Check these (they sort differently "
              "depending on how the DT2 orders names):")
        for slot, sample in probes:
            ask("Browser", f"/{sample} shows slot {slot}")
    out = BUILD / "load-test.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.dry_run or args.yes:
        print("\n(nothing asked: dry run)")
        return
    out.write_text("\n".join(report) + "\n" if report else "all matched\n")
    print(f"\n{'All matched.' if not report else f'{len(report)} mismatch(es) saved to {rel(out)}: send them to Claude.'}")


def sort_probes(sm):
    """Samples whose slot would differ under natural sort or with the .wav extension."""
    import loader
    out = []
    by_folder = {}
    for slot, sample in sorted(sm.slots.items()):
        by_folder.setdefault(sample.rsplit("/", 1)[0], []).append((slot, sample))
    for folder, items in by_folder.items():
        names = [s.rsplit("/", 1)[1] for _, s in items]
        alt = sorted(names, key=loader.natural)
        ext = sorted(names, key=lambda n: n + ".wav")
        for other in (alt, ext):
            for (slot, sample), a in zip(items, other):
                if sample.rsplit("/", 1)[1] != a:
                    out.append((slot, sample))
                    break
        if len(out) >= 3:
            break
    return list(dict.fromkeys(out))[:3]


def match_presets(r, words):
    """Every word must match: a bank letter (C), a world (rite), a role (hand, sl, lp), or part of the
    name, sample, recipe or tags."""
    rig = load_rig()
    roles = {role for role, *_ in rig.DRUM_ROLES + rig.TONE_ROLES} | {"sl", "lp"}
    out = []
    for key, p in sorted(r.presets.items(), key=lambda kv: (kv[1]["bank"], kv[1]["slot"])):
        world = rig.BANKS[p["bank"]][0].lower()
        hay = " ".join([p["name"], p["recipe"], p["sample"], " ".join(p["tags"])]).lower()
        ok = True
        for w in (w.lower() for w in words):
            if len(w) == 1 and w.upper() in rig.BANKS:
                ok = p["bank"] == w.upper()
            elif w in roles:
                ok = p["role"] == {"sl": "slice", "lp": "loop"}.get(w, w)
            elif w in ("core", "dub", "rite", "drift"):
                ok = world == w
            else:
                ok = w in hay
            if not ok:
                break
        if ok:
            out.append(p)
    return out


def cmd_presets(args):
    rig, r, samples, _ = checked_rig()
    if args.seed:
        import seed
        added, notes = seed.plan(r, samples, seed.parse_rules(ROOT / "presets" / "seed.txt"))
        for n in notes:
            print(f"  note  {n}")
        n = sum(len(v) for v in added.values())
        for bank, rows in sorted(added.items()):
            for slot, name, recipe, tags, sample in rows:
                print(f"  {bank}{slot:03d}  {name:<12}  {recipe:<13}  {sample}")
        if not n:
            print("nothing new to seed.")
        elif args.dry_run:
            print(f"\n{n} presets would be added (dry run).")
        else:
            seed.write(ROOT, added)
            print(f"\n{n} presets added. ./djmono check, then commit presets/.")
        return
    found = match_presets(r, args.query)
    for p in found:
        kits = ", ".join(r.used.get(f"{p['bank']}:{p['name']}", []))
        print(f"  {p['bank']}{p['slot']:03d}  {p['name']:<12}  {p['role']:<6} {p['recipe']:<13} "
              f"{p['sample'].split('/', 1)[1]:<44} {kits}")
    print(f"\n{len(found)} of {len(r.presets)} presets" + (f" matching {' '.join(args.query)}" if args.query else ""))


def cmd_browse(args):
    rig, r, samples, _ = checked_rig()
    loader, cfg, sm = slot_map()
    slots = sm.of
    found = [p for p in match_presets(r, args.query) if p["sample"] in slots]
    if not found:
        die("nothing matches with a RAM slot (./djmono presets QUERY to search; ./djmono slots for RAM)")
    kitfile = None
    if args.kit:
        world, _, name = args.kit.upper().partition("/")
        if world not in rig.WORLD_BANKS or not name:
            die(f"--kit WORLD/NAME, WORLD one of {', '.join(rig.WORLD_BANKS)}")
        kitfile = ROOT / "kits" / world / f"{name.replace(' ', '-')}.txt"
    port = loader.Port(cfg, dry=args.dry_run)
    print(f"{len(found)} presets onto track {args.track}. Keep the pattern playing.\n"
          "  n/space next · p back · r resend · k keep" + (f" (into {rel(kitfile)})" if kitfile else "") + " · q quit\n")
    i, machine = 0, "Oneshot"
    try:
        while 0 <= i < len(found):
            p = found[i]
            m, params = r.sound(p)
            loader.dial(port, args.track, slots[p["sample"]], m, params, cfg,
                        loader.wav_seconds(DRIVE / f"{p['sample']}.wav"), p["sample"])
            warn = f"  << set machine {m.upper()}" if m != machine else ""
            machine = m
            print(f"[{i + 1}/{len(found)}] {p['bank']}:{p['name']:<12} {p['recipe']:<13} "
                  f"{p['sample'].split('/', 1)[1]}{warn}  ", end="", flush=True)
            k = "n" if args.dry_run else (read_key().lower() or "n")
            print()
            if k == "q":
                break
            if k == "r":
                continue
            if k in ("p", "b"):
                i = max(0, i - 1)
                continue
            if k == "k":
                if kitfile:
                    keep_in_kit(kitfile, args.track, f"{p['bank']}:{p['name']}")
                    print(f"  kept: track {args.track} = {p['bank']}:{p['name']} in {rel(kitfile)}")
                else:
                    print(f"  {p['bank']}:{p['name']}  (add --kit WORLD/NAME to write it into a kit)")
            i += 1
    finally:
        port.close()


def keep_in_kit(path, track, ref):
    """Set one track line in a kit file, creating a draft kit if needed."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        name = path.stem.replace("-", " ")
        path.write_text(f"# {name} · {path.parent.name}\ntempo  = 120\nstatus = draft\n\n"
                        "# trk | preset          | sample locks                       | tweaks\n")
    lines = path.read_text().splitlines()
    row = f"{track:>2}  | {ref}"
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(\d+)\s*\|", line)
        if m and int(m.group(1)) == track:
            rest = line.split("|")[2:]
            lines[i] = row if not rest else f"{row:<22}|" + "|".join(rest)
            break
    else:
        pos = next((i for i, line in enumerate(lines) if re.match(r"^\s*(\d+)\s*\|", line)
                    and int(line.split("|")[0]) > track), len(lines))
        lines.insert(pos, row)
    path.write_text("\n".join(lines) + "\n")


def cmd_backup(args):
    day = BACKUPS / dt.date.today().isoformat()
    day.mkdir(parents=True, exist_ok=True)
    print(f"backup folder: {rel(day)}\n"
          "In Transfer: select the TRIAD project and the preset banks, back them up, and save into that folder.")
    if sys.platform == "darwin":
        subprocess.run(["open", str(day)])
    if not args.yes:
        input("Press Enter once the files are saved... ")
    files = [f for f in day.rglob("*") if f.is_file()]
    print(f"  {len(files)} files, {fmt_mb(sum(f.stat().st_size for f in files))}")
    paths = load_paths(required=False)
    lib = paths.get("lib")
    dest = paths.get("backup") or (lib.parent / "djmono-backups" if lib and str(lib).startswith("/Volumes/") else None)
    if not dest:
        print("  add 'backup = /path/on/the/NAS' to config/paths.local to copy these off the Mac")
        return
    if not dest.parent.is_dir():
        die(f"{dest.parent} isn't reachable (NAS not mounted?). The backup is safe in {rel(day)}")
    shutil.copytree(BACKUPS, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("README.md"))
    print(f"  copied to {dest}")


def read_key():
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        return (input() or "\n")[0]


def cmd_audition(args):
    lib = Library(load_paths())
    player = shutil.which("afplay") or shutil.which("play")
    if not player:
        die("no audio player (afplay on macOS, or sox's play)")
    crates = crate_files(args.crate)
    if len(crates) != 1:
        die("audition one crate at a time, e.g. ./djmono audition DUB/CHRD")
    crate = crates[0]
    rules = parse_crate(crate)
    picked = {(r.src, r.pattern) for r in rules if not is_glob(r.pattern)}
    cands, seen = [], set()
    for rule in rules:
        if not is_glob(rule.pattern) or (args.line and rule.line_no != args.line):
            continue
        for f in resolve(rule, lib, ignore_limit=True):
            if f.sid not in seen and (f.key, f.rel) not in picked:
                seen.add(f.sid)
                cands.append(f)
    if not cands:
        print("nothing new to audition.")
        return
    print(f"{len(cands)} candidates.  k keep · space/enter skip · r replay · b back · q quit\n")
    keep, i, proc = [], 0, None
    try:
        while 0 <= i < len(cands):
            f = cands[i]
            if f.abs is None:
                die(f"source '{f.key}' is index-only on this machine; audition where the files are")
            if proc:
                proc.terminate()
            proc = subprocess.Popen([player, str(f.abs)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[{i + 1}/{len(cands)}] {f.rel}  ", end="", flush=True)
            k = read_key().lower()
            if k == "q":
                print()
                break
            if k == "r":
                print()
                continue
            if k == "b":
                print()
                i = max(0, i - 1)
                continue
            if k == "k":
                keep.append(f)
                print("KEEP")
            else:
                print()
            i += 1
    finally:
        if proc:
            proc.terminate()
    if keep:
        with open(crate, "a") as fh:
            fh.write(f"\n# picks {dt.date.today().isoformat()}\n")
            for f in keep:
                fh.write(f"{f.key}:{f.rel}\n")
        print(f"\n{len(keep)} picks added to {rel(crate)}. Once you're happy, delete the broad rule they came from.")


NAS_URL = "smb://apollo@archive.meistervision.com"
MOUNT_HINT = f"mount the NAS: Finder > Go > Connect to Server (cmd-K) > {NAS_URL}, open the share with audio/sample packs"


def child_ci(base, name):
    """Case-insensitive child lookup (SMB shares keep whatever case the folders were made with)."""
    try:
        for c in base.iterdir():
            if c.name.lower() == name and c.is_dir():
                return c
    except OSError:
        pass
    return None


def find_library():
    """Sample packs live on the NAS under audio/sample packs. Finder mounts shares at /Volumes/<share>."""
    vols = Path("/Volumes")
    if not vols.is_dir():
        return None
    for vol in sorted(vols.iterdir()):
        if vol.is_symlink():  # "Macintosh HD" points at /
            continue
        try:
            bases = [vol, *(c for c in sorted(vol.iterdir()) if c.is_dir())]
        except OSError:
            continue
        for base in bases:
            audio = child_ci(base, "audio")
            hit = child_ci(audio, "sample packs") if audio else child_ci(base, "sample packs")
            if hit:
                return hit
    return None


def find_sfm_root(lib):
    if not lib or not lib.is_dir():
        return None
    for d in [lib, *lib.glob("*"), *lib.glob("*/*"), *lib.glob("*/*/*")]:
        try:
            if d.is_dir() and sum(1 for c in d.iterdir() if "from mars" in c.name.lower()) >= 3:
                return d
        except OSError:
            continue
    return None


def set_path(text, key, value):
    line = f"{key} = {value}"
    if re.search(rf"^{key}\s*=", text, flags=re.M):
        return re.sub(rf"^{key}\s*=.*$", line, text, flags=re.M)
    return text.rstrip() + "\n" + line + "\n"


def cmd_doctor(args):
    ok = True

    def check(label, good, hint=""):
        nonlocal ok
        print(f"  {'ok ' if good else '-- '} {label}" + ("" if good or not hint else f"\n       -> {hint}"))
        ok = ok and good

    print("tools")
    check(f"python {sys.version.split()[0]}", sys.version_info >= (3, 9), "brew install python")
    check("sox", bool(shutil.which("sox")), "brew install sox")
    check("afplay (audition)", bool(shutil.which("afplay") or shutil.which("play")))
    has_el = bool(shutil.which("elektroid-cli"))
    print(f"  {'ok ' if has_el else '.. '} elektroid-cli" + ("" if has_el else "   (optional: without it, sync stages a folder for Transfer)"))

    print("library")
    local = CONFIG / "paths.local"
    text = local.read_text() if local.exists() else (CONFIG / "paths.example").read_text()
    roots = {}
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            roots[k.strip()] = Path(os.path.expanduser(v.strip()))
    # fill in lib/sfm when they point nowhere (first run, or the share mounted under a new name)
    lib = roots.get("lib")
    if not (lib and lib.is_dir()):
        lib = find_library()
        if lib:
            text = set_path(text, "lib", lib)
            print(f"  found sample packs at {lib}")
    sfm = roots.get("sfm")
    if not (sfm and sfm.is_dir()):
        sfm = find_sfm_root(lib)
        if sfm:
            text = set_path(text, "sfm", sfm)
            print(f"  found Samples From Mars at {sfm}")
    if not local.exists() or text != local.read_text():
        local.write_text(text)
        print("  wrote config/paths.local")

    files = crate_files()
    rules = [r for f in files for r in parse_crate(f)]
    used = {r.src for r in rules}
    paths = load_paths()
    for k, p in paths.items():
        if p.is_dir() or k in used:
            hint = MOUNT_HINT if str(p).startswith("/Volumes/") else "fix the path in config/paths.local"
            check(f"{k:<4} {p}", p.is_dir(), hint)
        else:
            print(f"  ..  {k:<4} {p}   (not there yet; fine until a crate uses '{k}:')")
    for k in sorted(used - set(paths)):
        check(f"{k:<4} (used by crates)", False, f"add '{k} = /path' to config/paths.local")
    lib = paths.get("lib")
    if lib and lib.is_dir():
        zips = [z for z in [*lib.glob("*.zip"), *lib.glob("*/*.zip"), *lib.glob("*/*/*.zip")]]
        if zips:
            print(f"  ..  {len(zips)} zipped packs under lib (djmono only reads unzipped audio), e.g. {zips[0].name}")

    print("crates")
    print(f"  ok  {len(files)} crates, {len(rules)} active rules")

    print("midi (load, browse)")
    try:
        import mido
        names = mido.get_output_names()
        cfg = slot_map()[1]
        hit = [n for n in names if cfg["port"].lower() in n.lower()]
        print(f"  {'ok ' if hit else '.. '} " + (f"port {hit[0]}" if hit else
              f"no port matching '{cfg['port']}' (DT2 unplugged? found: {', '.join(names) or 'none'})"))
    except ImportError:
        print("  ..  mido not installed (only needed for load and browse):\n"
              "       -> python3 -m venv .venv && .venv/bin/pip install mido python-rtmidi")
    except Exception as e:  # rtmidi missing or no MIDI backend
        print(f"  ..  MIDI backend: {e}\n       -> .venv/bin/pip install python-rtmidi")
    print("\nready." if ok else "\nfix the items marked -- and rerun.")


def main():
    ap = argparse.ArgumentParser(prog="djmono", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check tools and paths; create config/paths.local").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("scan", help="index a sample source into index/<source>.tsv")
    p.add_argument("source", nargs="?")
    p.add_argument("--only", metavar="FOLDER", help="rescan one pack folder, e.g. --only SKINS (fast)")
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("ls", help="show what each crate rule matches")
    p.add_argument("crate", nargs="?", help="WORLD or WORLD/FN")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--all", action="store_true", help="ignore limit=")
    p.set_defaults(fn=cmd_ls)
    p = sub.add_parser("audition", help="play a crate's candidates and keep the good ones")
    p.add_argument("crate")
    p.add_argument("--line", type=int, help="only the rule on this line")
    p.set_defaults(fn=cmd_audition)
    p = sub.add_parser("build", help="render crates to build/drive and update the lock")
    p.add_argument("crate", nargs="?", help="WORLD or WORLD/FN (default: everything)")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("sync", help="send new samples to the Digitakt II")
    p.add_argument("--transfer", action="store_true", help="stage a folder for Elektron Transfer")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-y", "--yes", action="store_true", help="mark staged files as synced without asking")
    p.set_defaults(fn=cmd_sync)
    sub.add_parser("status", help="budgets, pending sync, retired samples").set_defaults(fn=cmd_status)
    sub.add_parser("check", help="presets, kits and projects: complete, consistent, within RAM").set_defaults(fn=cmd_check)
    p = sub.add_parser("sheet", help="write the sheets: project load order, kits, preset banks")
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(fn=cmd_sheet)
    p = sub.add_parser("slots", help="plan which RAM slot each synced sample takes in TRIAD")
    p.add_argument("--reset", action="store_true", help="plan from scratch (for a new, empty project)")
    p.add_argument("--prune", action="store_true", help="forget retired samples you've deleted from the device")
    p.set_defaults(fn=cmd_slots)
    p = sub.add_parser("load", help="dial a kit (or one preset) into the DT2 over USB MIDI")
    p.add_argument("kit", nargs="?", help="kit name, e.g. \"DEEP ECHO\"")
    p.add_argument("--preset", metavar="B:NAME", help="one preset instead of a kit")
    p.add_argument("--track", type=int, default=1, help="track for --preset (1-16)")
    p.add_argument("--fx", action="store_true", help="send the kit's FX settings instead of its tracks")
    p.add_argument("--test", action="store_true", help="check the MIDI setup and RAM slots with a test sound")
    p.add_argument("--dry-run", action="store_true", help="show what would be sent")
    p.add_argument("-y", "--yes", action="store_true", help="don't stop to ask")
    p.set_defaults(fn=cmd_load)
    p = sub.add_parser("browse", help="step through presets on one track while the pattern plays")
    p.add_argument("query", nargs="*", help="words to match: name, bank letter, role, recipe, tag, sample")
    p.add_argument("--track", type=int, default=1)
    p.add_argument("--kit", metavar="WORLD/NAME", help="k writes the preset into this kit's track")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_browse)
    p = sub.add_parser("presets", help="search the preset library, or --seed it from new samples")
    p.add_argument("query", nargs="*")
    p.add_argument("--seed", action="store_true", help="add presets for new samples (presets/seed.txt)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_presets)
    p = sub.add_parser("backup", help="save a Transfer backup into backups/ and copy it to the NAS")
    p.add_argument("-y", "--yes", action="store_true", help="don't wait; copy what's already there")
    p.set_defaults(fn=cmd_backup)
    args = ap.parse_args()
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet when piped into head/less
    args.fn(args)


if __name__ == "__main__":
    main()
