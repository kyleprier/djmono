#!/usr/bin/env python3
"""djmono: curate crates on the Mac, render them for the Digitakt II, sync.

  crates/<WORLD>/<FN>.txt   ->  +Drive /<WORLD>/<FN>/          (the repo mirrors the device)
  config/paths.local        ->  where the sample library lives on this machine (never in git)
  build/drive/              ->  rendered 16-bit / 48 kHz WAVs, ready to send
  state/drive.lock          ->  what was built, from what, and when it reached the device

Stdlib only (Python 3.9+). Needs `sox`. Uses `elektroid-cli` for sync if installed,
otherwise stages a folder for Elektron Transfer.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import fnmatch
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
INDEX = ROOT / "index"
CONFIG = ROOT / "config"

# --- Device facts (Digitakt II, OS 1.16) ------------------------------------------------
MB = 1_000_000
PROJECT_RAM, PROJECT_SLOTS = 400 * MB, 1016          # per project
BUDGET = {"CORE": (100 * MB, 250)}                   # CORE + any one world = one project
BUDGET_WORLD = (300 * MB, 760)
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
    "bed":  dict(mono=False, trim=False, len=40,  fade=200, norm=-3.0),
    "loop": dict(mono=False, trim=False, len=300, fade=0,   norm=-1.0),
}
FUNCTIONS = {
    "KICK": "hit", "SNR": "hit", "HAT": "hit", "HAND": "hit", "SHKR": "hit", "WOOD": "hit",
    "BELL": "ring", "FX": "ring",
    "BASS": "tone", "KEYS": "tone", "CHRD": "tone", "HORN": "tone", "TONE": "tone", "VOX": "tone",
    "PAD": "bed", "DRONE": "bed", "FIELD": "bed", "NOISE": "bed",
    "LOOP": "loop", "CHAIN": "loop",
}
# Folders inside sample packs that hold DAW/sampler formats (duplicates of the WAVs). Skipped.
FORMAT_WORDS = ("ableton", "kontakt", "exs", "exs24", "logic", "reason", "nn xt", "nnxt", "sfz",
                "maschine", "battery", "mpc", "fl studio", "flstudio", "__macosx")
DEFAULT_PREFER = "color"  # SFM ships clean + color (tape/tube) takes; keep color unless a rule says prefer=clean or prefer=any
OPTION_KEYS = {"limit", "pick", "prefer", "exclude", "code", "name", "keepname", "raw",
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


def _skip_dir(name):
    if name.startswith("."):
        return True
    if "mars" in name.lower():  # a pack folder, e.g. "MPC60 From Mars", is never a format folder
        return False
    padded = f" {norm(name)} "
    return any(f" {w} " in padded for w in FORMAT_WORDS)


def walk_source(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d))
        for f in sorted(filenames):
            if f.startswith(".") or Path(f).suffix.lower() not in AUDIO_EXT:
                continue
            full = Path(dirpath) / f
            try:
                size = full.stat().st_size
            except OSError:
                continue
            out.append((str(full.relative_to(root)), size))
    return out


class Library:
    """Lazily indexes each source root (or falls back to index/<key>.tsv when the root is absent)."""

    def __init__(self, roots):
        self.roots, self._files, self.missing = roots, {}, set()

    def files(self, key):
        if key in self._files:
            return self._files[key]
        root = self.roots.get(key)
        if root and root.is_dir():
            items, absroot = walk_source(root), root
        elif (INDEX / f"{key}.tsv").exists():
            items, absroot = [], None
            for line in (INDEX / f"{key}.tsv").read_text().splitlines():
                if line and not line.startswith("#"):
                    r, _, s = line.rpartition("\t")
                    items.append((r, int(s or 0)))
        else:
            if key not in self.missing:
                where = f" at {root}" if root else " in config/paths.local"
                print(f"  warn  source '{key}' not found{where}; its rules are skipped")
            self.missing.add(key)
            return []
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
    for k in ("limit", "len", "fade"):
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
        hits = [f for f in files if fnmatch.fnmatchcase(f.norm, g) or fnmatch.fnmatchcase(f.norm, "*/" + g)]
    else:
        hits = [f for f in files if f.rel == rule.pattern] or \
               [f for f in files if f.norm == norm_path(rule.pattern)]
    if "exclude" in rule.opts:
        pats = [norm_path(p) for p in str(rule.opts["exclude"]).split(",") if p]
        hits = [f for f in hits if not any(fnmatch.fnmatchcase(f.norm, "*" + p + "*") for p in pats)]
    prefer = str(rule.opts.get("prefer", DEFAULT_PREFER))
    if prefer != "any":
        words = [norm(w) for w in prefer.split(",") if w]
        pref = [f for f in hits if any(re.search(rf"\b{re.escape(w)}\b", f.norm) for w in words)]
        hits = pref or hits
    hits.sort(key=lambda f: f.rel.lower())
    limit = rule.opts.get("limit")
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
    # drop leading words the prefix already says: pack name, code, function (909 Kick 01 -> 909_kick_01)
    redundant = {code, fn.lower()} | (set(slug(pack_seg).split("-")) if pack_seg else set())
    parts = slug(stem).split("-")
    while len(parts) > 1 and parts[0] in redundant:
        parts.pop(0)
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
    st = f.abs.stat()
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
    """Resolve every crate into jobs. Names already in the lock are reused so they never drift."""
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
    print(f"\n  {'world':<7}{'files':>7}{'size':>12}   budget (one project = CORE + one world)")
    over = False
    for w in WORLDS:
        b, n = per.get(w, (0, 0))
        cap_b, cap_n = BUDGET.get(w, BUDGET_WORLD)
        flag = ""
        if b > cap_b or n > cap_n:
            flag, over = "  << over budget", True
        print(f"  {w:<7}{n:>7}{fmt_mb(b):>12}   {100 * b / cap_b:5.0f}% of {fmt_mb(cap_b)}, {n}/{cap_n} files{flag}")
    total = sum(b for b, _ in per.values())
    print(f"  {'total':<7}{sum(n for _, n in per.values()):>7}{fmt_mb(total):>12}   "
          f"~{transfer_minutes(total):.0f} min to send everything over USB")
    return over


def cmd_build(args):
    if not shutil.which("sox"):
        die("sox not found. brew install sox")
    lib, codes, lock = Library(load_paths()), load_codes(), read_lock()
    print("resolving crates")
    jobs, warnings = plan_build(lib, codes, lock, args.crate)
    missing = sorted({j["file"].key for j in jobs if j["file"].abs is None})
    if missing:
        die(f"source(s) {', '.join(missing)} are only available as an index here; build on the machine with the files")

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
    INDEX.mkdir(exist_ok=True)
    for k in keys:
        root = roots.get(k)
        if not root or not root.is_dir():
            print(f"  skip {k}: {root} not found")
            continue
        items = walk_source(root)
        with open(INDEX / f"{k}.tsv", "w") as fh:
            fh.write(f"# {k}: {len(items)} audio files, scanned {dt.date.today().isoformat()} (relative path, bytes)\n")
            for r, s in items:
                fh.write(f"{r}\t{s}\n")
        print(f"  {k}: {len(items)} files -> index/{k}.tsv")
    print("Commit index/ so crates can be curated from any machine.")


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


def find_sfm_root():
    bases = [Path.home() / "music production", Path.home() / "Music", Path.home() / "Samples"]
    bases += [p for p in Path("/Volumes").glob("*")] if Path("/Volumes").exists() else []
    for base in bases:
        if not base.is_dir():
            continue
        for d in [base, *base.glob("*"), *base.glob("*/*"), *base.glob("*/*/*")]:
            try:
                if d.is_dir() and sum(1 for c in d.iterdir() if "from mars" in c.name.lower()) >= 3:
                    return d
            except OSError:
                continue
    return None


def cmd_doctor(args):
    ok = True

    def check(label, good, hint=""):
        nonlocal ok
        print(f"  {'ok ' if good else '-- '} {label}" + ("" if good or not hint else f"   -> {hint}"))
        ok = ok and good

    print("tools")
    check(f"python {sys.version.split()[0]}", sys.version_info >= (3, 9), "brew install python")
    check("sox", bool(shutil.which("sox")), "brew install sox")
    check("afplay (audition)", bool(shutil.which("afplay") or shutil.which("play")))
    has_el = bool(shutil.which("elektroid-cli"))
    print(f"  {'ok ' if has_el else '.. '} elektroid-cli" + ("" if has_el else "   (optional: without it, sync stages a folder for Transfer)"))

    print("config")
    local = CONFIG / "paths.local"
    if not local.exists():
        text = (CONFIG / "paths.example").read_text()
        found = find_sfm_root()
        if found:
            text = re.sub(r"^sfm\s*=.*$", f"sfm = {found}", text, flags=re.M)
            print(f"  found Samples From Mars at {found}")
        local.write_text(text)
        print("  created config/paths.local (edit it if a path is wrong)")
    files = crate_files()
    rules = [r for f in files for r in parse_crate(f)]
    used = {r.src for r in rules}
    for k, p in load_paths().items():
        if p.is_dir() or k in used:
            check(f"{k:<4} {p}", p.is_dir(), "fix the path in config/paths.local")
        else:
            print(f"  ..  {k:<4} {p}   (not there yet; fine until a crate uses '{k}:')")
    for k in sorted(used - set(load_paths())):
        check(f"{k:<4} (used by crates)", False, f"add '{k} = /path' to config/paths.local")

    print("crates")
    print(f"  ok  {len(files)} crates, {len(rules)} active rules")
    print("\nready." if ok else "\nfix the items marked -- and rerun.")


def main():
    ap = argparse.ArgumentParser(prog="djmono", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check tools and paths; create config/paths.local").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("scan", help="index a sample source into index/<source>.tsv")
    p.add_argument("source", nargs="?")
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
    args = ap.parse_args()
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet when piped into head/less
    args.fn(args)


if __name__ == "__main__":
    main()
