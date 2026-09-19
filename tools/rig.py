"""The rig: presets, kits and projects as plain-text specs, checked against the samples djmono builds.

  presets/recipes.txt        recipe | machine | parameters
  presets/<B>-<WORLD>-<KIND>.txt   slot | NAME | recipe | tags | WORLD/FN/sample | parameters
  kits/<WORLD>/<KIT-NAME>.txt      key = value header, then  track | B:PRESET | sample locks | parameters
  projects/<NAME>.txt              load = worlds, tempo, bank X = kits (pattern order)

Banks A-D hold drums, E-H tones, one pair per world. Every drum bank uses the same slot ranges, and so does
every tone bank, so a slot number means the same kind of sound everywhere. Kit tracks 1-8 take any drum
preset; tracks 9-16 each take one tone role, so a mute on track 9 is always the bass.
"""
import fnmatch
import re
from pathlib import Path

import dt2

DRUM_ROLES = [("low", 1, 24), ("snap", 25, 48), ("hat", 49, 72), ("metal", 73, 96),
              ("hand", 97, 160), ("wood", 161, 192), ("slice", 193, 224), ("loop", 225, 256)]
TONE_ROLES = [("bass", 1, 32), ("stab", 33, 80), ("keys", 81, 112), ("lead", 113, 160),
              ("pad", 161, 192), ("scape", 193, 224), ("noise", 225, 240), ("fx", 241, 256)]
ROLE_LABEL = {"low": "LOW (kicks, surdos, low toms)", "snap": "SNAP (rims, snares, claps)",
              "hat": "HAT & SHAKE", "metal": "METAL (rides, bells, gongs)", "hand": "HAND DRUMS",
              "wood": "WOOD & FOUND", "slice": "SL · SLICE GRID (loops cut into 16 slices a bar: play them on the grid)",
              "loop": "LP · WHOLE LOOP (Stretch: plays at any tempo)",
              "bass": "BASS", "stab": "STAB (chords, plucks)", "keys": "KEYS",
              "lead": "LEAD (horns, strings, guitar, steel, voice)", "pad": "PAD", "scape": "SCAPE (field, drone)",
              "noise": "NOISE", "fx": "FX"}
PREFIX = {"slice": "SL ", "loop": "LP "}
BANKS = {"A": ("CORE", "DRUMS"), "B": ("DUB", "DRUMS"), "C": ("RITE", "DRUMS"), "D": ("DRIFT", "DRUMS"),
         "E": ("CORE", "TONES"), "F": ("DUB", "TONES"), "G": ("RITE", "TONES"), "H": ("DRIFT", "TONES")}
WORLD_BANKS = {"DUB": "ABEF", "RITE": "ACEG", "DRIFT": "ADEH", "BRIDGE": "ABCDEFGH"}
TONE_TRACK = {9: "bass", 10: "stab", 11: "keys", 12: "lead", 13: "pad", 14: "scape", 15: "noise", 16: "fx"}
TRACK_NAME = {1: "low", 2: "snap", 3: "hat", 4: "metal", 5: "hand A", 6: "hand B", 7: "wood/shake", 8: "loop",
              **TONE_TRACK}
TAGS = {"kick", "snare", "rimshot", "clap", "tom", "percussion", "hi-hat", "cymbal", "cowbell", "synth", "bass",
        "lead", "pad", "texture", "chord", "sound fx", "electronic", "metallic", "acoustic", "atmosphere", "noisy",
        "glitch", "hard", "soft", "dark", "bright", "vintage", "epic", "fail", "loop", "mine", "favourite"}
NAME_OK = re.compile(r"^[A-Z0-9 ~!@#$%^&()_+=-]{1,12}$")
KIT_KEYS = ("tempo", "swing", "ref", "feel", "play", "status", *dt2.FX)
MAX_PRESETS, MAX_KITS, KITS_PER_BANK = 2048, 1024, 16


def roles(bank):
    return DRUM_ROLES if BANKS[bank][1] == "DRUMS" else TONE_ROLES


def slot_role(bank, slot):
    for role, lo, hi in roles(bank):
        if lo <= slot <= hi:
            return role
    return None


def role_range(bank, role):
    for r, lo, hi in roles(bank):
        if r == role:
            return lo, hi
    raise KeyError(role)


def bank_file(bank):
    world, kind = BANKS[bank]
    return f"{bank}-{world}-{kind}.txt"


def bpm_of(sample):
    """The tempo written in a loop's name (skin_loop_110-..., ...-120), if any."""
    for n in re.findall(r"(?<![0-9])(\d{2,3})(?![0-9])", sample.rsplit("/", 1)[-1]):
        if 60 <= int(n) <= 180:
            return int(n)
    return None


def grid_for(sample, seconds):
    """Slices for the Grid machine: 16 a bar, from the loop's tempo and length. 16 when either is unknown."""
    bpm = bpm_of(sample)
    if not bpm or not seconds:
        return 16, None
    bars = seconds * bpm / 240
    best = min((1, 2, 4, 8), key=lambda b: abs(b - bars))
    return min(64, 16 * best), best


def _rows(path):
    for i, line in enumerate(path.read_text().splitlines(), 1):
        s = line.strip()
        if s and not s.startswith("#"):
            yield i, s


class Rig:
    def __init__(self, root):
        self.root = Path(root)
        self.errors, self.warnings = [], []
        self.recipes, self.presets, self.kits, self.projects = {}, {}, {}, {}
        self.used = {}  # preset key -> kits using it (filled by check)

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def where(self, path, i):
        return f"{path.relative_to(self.root)}:{i}"

    def _params(self, text, machine, where):
        params, bad = dt2.parse_params(text)
        for b in bad:
            self.err(f"{where}: {b}")
        for k, v in list(params.items()):
            problem = dt2.check_value(k, v, machine)
            if problem:
                self.err(f"{where}: {problem}")
                del params[k]
        return params

    # --- load --------------------------------------------------------------------------
    def load(self):
        pdir, kdir, jdir = self.root / "presets", self.root / "kits", self.root / "projects"
        rfile = pdir / "recipes.txt"
        for i, s in _rows(rfile) if rfile.exists() else ():
            where = self.where(rfile, i)
            parts = [p.strip() for p in s.split("|")]
            if len(parts) != 3:
                self.err(f"{where}: expected  recipe | machine | parameters")
                continue
            name, machine, text = parts
            if machine not in dt2.MACHINES:
                self.err(f"{where}: machine '{machine}' (use {', '.join(dt2.MACHINES)})")
                continue
            if name in self.recipes:
                self.err(f"{where}: recipe '{name}' defined twice")
            self.recipes[name] = dict(machine=machine, params=self._params(text, machine, where), where=where)
        for f in sorted(pdir.glob("[A-H]-*.txt")):
            bank = f.name[0]
            if f.name != bank_file(bank):
                self.warn(f"{f.relative_to(self.root)}: bank {bank} is {bank_file(bank)}")
            for i, s in _rows(f):
                self._load_preset(bank, s, self.where(f, i))
        for f in sorted(kdir.glob("*/*.txt")):
            self._load_kit(f)
        for f in sorted(jdir.glob("*.txt")):
            proj = dict(name=f.stem, load=[], banks={}, tempo="", where=str(f.relative_to(self.root)))
            for i, s in _rows(f):
                k, _, v = (x.strip() for x in s.partition("="))
                if k == "load":
                    proj["load"] = v.split()
                elif k.startswith("bank ") and k[5:] in BANKS:
                    proj["banks"][k[5:]] = [x.strip() for x in v.split(",") if x.strip()]
                elif k == "tempo":
                    proj["tempo"] = v
                else:
                    self.err(f"{self.where(f, i)}: unknown key '{k}' (load, tempo, bank A-H)")
            self.projects[f.stem] = proj
        return self

    def _load_preset(self, bank, s, where):
        parts = [p.strip() for p in s.split("|")]
        if len(parts) not in (5, 6) or not parts[0].isdigit():
            self.err(f"{where}: expected  slot | NAME | recipe | tags | WORLD/FN/sample | parameters")
            return
        slot, name, recipe, tags, sample = int(parts[0]), *parts[1:5]
        key = f"{bank}:{name}"
        if not 1 <= slot <= 256:
            self.err(f"{where}: slot {slot} is outside 1-256")
        if any(p["bank"] == bank and p["slot"] == slot for p in self.presets.values()):
            self.err(f"{where}: slot {bank}{slot:03d} is used twice")
        if key in self.presets:
            self.err(f"{where}: preset name {key} is used twice")
            return
        if not NAME_OK.match(name):
            self.err(f"{where}: '{name}' needs 1-12 characters: A-Z 0-9 space ~!@#$%^&()_+=-")
        r = self.recipes.get(recipe)
        if not r:
            self.err(f"{where}: recipe '{recipe}' isn't in presets/recipes.txt")
        machine = r["machine"] if r else dt2.DEFAULT_MACHINE
        params = self._params(parts[5], machine, where) if len(parts) == 6 else {}
        self.presets[key] = dict(bank=bank, slot=slot, name=name, recipe=recipe, sample=sample, own=params,
                                 tags=[t.strip() for t in tags.split(",") if t.strip()], where=where,
                                 role=slot_role(bank, slot))

    def _load_kit(self, f):
        world, name = f.parent.name, f.stem.replace("-", " ")
        kit = dict(world=world, name=name, tracks={}, fx={}, where=str(f.relative_to(self.root)),
                   **{k: "" for k in KIT_KEYS if k not in dt2.FX})
        for i, s in _rows(f):
            where = self.where(f, i)
            if "|" in s:
                parts = [p.strip() for p in s.split("|")]
                if not parts[0].isdigit() or len(parts) not in (2, 3, 4):
                    self.err(f"{where}: expected  track | B:PRESET | sample locks | parameters")
                    continue
                trk = int(parts[0])
                if trk in kit["tracks"]:
                    self.err(f"{where}: track {trk} is listed twice")
                locks = [g.strip() for g in parts[2].split(",") if g.strip()] if len(parts) > 2 else []
                kit["tracks"][trk] = dict(preset=parts[1], locks=locks, tweak_text=parts[3] if len(parts) > 3 else "",
                                          where=where)
            elif "=" in s:
                k, _, v = (x.strip() for x in s.partition("="))
                if k in dt2.FX:
                    vals, bad = dt2.parse_fx(v)
                    for b in bad:
                        self.err(f"{where}: {b}")
                    for fk in vals:
                        if fk not in dt2.FX[k]:
                            self.err(f"{where}: {k} has no '{fk}' (use {', '.join(dt2.FX[k])})")
                        elif not 0 <= vals[fk] <= 127:
                            self.err(f"{where}: {k} {fk}={vals[fk]} is outside 0-127")
                    kit["fx"][k] = {fk: v for fk, v in vals.items() if fk in dt2.FX[k]}
                elif k in KIT_KEYS:
                    kit[k] = v
                else:
                    self.err(f"{where}: unknown key '{k}' ({', '.join(KIT_KEYS)})")
            else:
                self.err(f"{where}: can't read this line")
        if name in self.kits:
            self.err(f"{kit['where']}: kit name '{name}' is also {self.kits[name]['where']}")
        self.kits[name] = kit

    # --- sounds ------------------------------------------------------------------------
    def find(self, ref):
        """A preset by B:NAME (case-insensitive)."""
        bank, _, name = ref.partition(":")
        return self.presets.get(f"{bank.strip().upper()}:{name.strip().upper()}")

    def sound(self, preset, tweaks=None):
        """(machine, params) for a preset plus a kit track's tweaks. params include lfoN.dest (set by hand)."""
        r = self.recipes.get(preset["recipe"], dict(machine=dt2.DEFAULT_MACHINE, params={}))
        return r["machine"], {**r["params"], **preset["own"], **(tweaks or {})}

    @staticmethod
    def manual(machine, params):
        """What the loader can't set: machine, LFO destinations, loop bars."""
        out = []
        if machine != dt2.DEFAULT_MACHINE:
            out.append(f"machine {machine.upper()}")
        for n in (1, 2, 3):
            d = params.get(f"lfo{n}.dest")
            if d:
                out.append(f"LFO{n} > {dt2.LFO_DEST[d]}")
        if machine in ("Stretch", "Werp"):
            out.append("BARS = loop length")
        return out

    @staticmethod
    def settings(params):
        """Compact, device-readable list of the parameters that differ from init."""
        out, lfo = [], {}
        for k, v in params.items():
            if k.startswith("lfo"):
                lfo.setdefault(k[3], {})[k[5:]] = v
                continue
            p = dt2.TRACK[k]
            if p.default is not None and v == p.default:
                continue
            out.append("grid auto (16 a bar)" if (k, v) == ("grid", "auto") else f"{k} {dt2.show(k, v)}")
        for n, l in sorted(lfo.items()):
            if "wave" in l:
                out.append(f"LFO{n} {l['wave'].upper()} spd {l['speed']} {l['mult']} dep {l['depth']:+d}"
                           + (f" > {l['dest']}" if l.get("dest") else ""))
        return " · ".join(out)

    # --- check -------------------------------------------------------------------------
    def check(self, samples):
        """samples: {"WORLD/FN/name": bytes} for everything the crates produce."""
        names = sorted(samples)
        world_of = lambda path: path.split("/", 1)[0]
        for key, p in self.presets.items():
            if p["sample"] not in samples:
                self.err(f"{p['where']}: sample {p['sample']} isn't produced by any crate")
            bad = [t for t in p["tags"] if t.lower() not in TAGS]
            if bad:
                self.err(f"{p['where']}: unknown tag(s) {', '.join(bad)}")
            role, (home, _) = p["role"], BANKS[p["bank"]]
            prefix = PREFIX.get(role)
            if prefix and not p["name"].startswith(prefix):
                self.err(f"{p['where']}: {role} presets are named '{prefix}...' so loops stand out ({p['name']})")
            if not prefix and p["name"][:3] in PREFIX.values():
                self.err(f"{p['where']}: '{p['name']}' looks like a loop but sits in the {role} range")
            machine = self.recipes.get(p["recipe"], {}).get("machine")
            if role == "slice" and machine not in ("Grid", "Slice"):
                self.err(f"{p['where']}: SL presets use the Grid or Slice machine (recipe {p['recipe']} is {machine})")
            if world_of(p["sample"]) not in (home, "CORE"):
                self.warn(f"{p['where']}: bank {p['bank']} ({home}) uses a {world_of(p['sample'])} sample")
            if home == "CORE" and world_of(p["sample"]) != "CORE":
                self.err(f"{p['where']}: CORE banks only use CORE samples, so every world can load them")
        used = {}
        for name, k in self.kits.items():
            if k["world"] not in WORLD_BANKS:
                self.err(f"{k['where']}: kits live in kits/{{{','.join(WORLD_BANKS)}}}/")
                continue
            if len(name) > 12 or not NAME_OK.match(name):
                self.err(f"{k['where']}: kit name '{name}' needs 1-12 characters")
            if not re.fullmatch(r"\d{2,3}(\.\d)?", k["tempo"]) or not 30 <= float(k["tempo"]) <= 300:
                self.err(f"{k['where']}: tempo = 30-300 is required")
            if k["swing"] and (not k["swing"].isdigit() or not 50 <= int(k["swing"]) <= 80):
                self.err(f"{k['where']}: swing is 50-80 (%)")
            missing = [t for t in range(1, 17) if t not in k["tracks"]]
            if missing:
                (self.warn if k["status"] == "draft" else self.err)(
                    f"{k['where']}: no track {', '.join(map(str, missing))}"
                    + (" (draft)" if k["status"] == "draft" else ""))
            for trk, t in sorted(k["tracks"].items()):
                if not 1 <= trk <= 16:
                    self.err(f"{t['where']}: track {trk} is outside 1-16")
                    continue
                p = self.find(t["preset"])
                if not p:
                    self.err(f"{t['where']}: preset {t['preset']} isn't in presets/")
                    continue
                t["key"] = f"{p['bank']}:{p['name']}"
                if name not in used.setdefault(t["key"], []):
                    used[t["key"]].append(name)
                kind = BANKS[p["bank"]][1]
                if trk <= 8 and kind != "DRUMS":
                    self.err(f"{t['where']}: tracks 1-8 take drum presets (banks A-D); {t['preset']} is a tone")
                if trk >= 9 and (kind != "TONES" or p["role"] != TONE_TRACK[trk]):
                    self.err(f"{t['where']}: track {trk} is {TONE_TRACK[trk]}, but {t['preset']} is "
                             f"{p['role']} (slot {p['bank']}{p['slot']:03d})")
                if p["bank"] not in WORLD_BANKS[k["world"]]:
                    self.err(f"{t['where']}: a {k['world']} kit uses banks {', '.join(WORLD_BANKS[k['world']])}; "
                             f"{t['preset']} is {BANKS[p['bank']][0]}")
                machine = self.recipes.get(p["recipe"], {}).get("machine", dt2.DEFAULT_MACHINE)
                t["tweaks"] = self._params(t["tweak_text"], machine, t["where"]) if t["tweak_text"] else {}
                for g in t["locks"]:
                    hits = fnmatch.filter(names, g)
                    if not hits:
                        self.err(f"{t['where']}: sample lock '{g}' matches no sample")
                    elif k["world"] != "BRIDGE" and any(world_of(h) not in (k["world"], "CORE") for h in hits):
                        self.warn(f"{t['where']}: sample lock '{g}' reaches outside {k['world']} and CORE")
        self.used = used
        placed = {}
        for pname, proj in self.projects.items():
            for bank, kits in proj["banks"].items():
                if len(kits) > KITS_PER_BANK:
                    self.err(f"{proj['where']}: bank {bank} has {len(kits)} kits; a pattern bank holds 16")
                for i, kn in enumerate(kits, 1):
                    kit = self.kits.get(kn)
                    if not kit:
                        self.err(f"{proj['where']}: kit '{kn}' isn't in kits/")
                        continue
                    if kn in placed:
                        self.warn(f"{proj['where']}: kit '{kn}' is in pattern {placed[kn]} and {bank}{i:02d}")
                    placed.setdefault(kn, f"{bank}{i:02d}")
                    kit.setdefault("pattern", f"{bank}{i:02d}")
            loaded = [n for n in names if world_of(n) in proj["load"]]
            proj["ram"], proj["slots"] = sum(samples[n] for n in loaded), len(loaded)
            for kn in (k for ks in proj["banks"].values() for k in ks):
                for t in self.kits.get(kn, {}).get("tracks", {}).values():
                    p = self.find(t["preset"])
                    if p and world_of(p["sample"]) not in proj["load"]:
                        self.err(f"{proj['where']}: {kn} needs {p['sample']}, which isn't loaded")
        for name, k in self.kits.items():
            if name not in placed and k["status"] != "draft":
                self.warn(f"{k['where']}: not in any project's pattern banks")
        if len(self.presets) > MAX_PRESETS:
            self.err(f"{len(self.presets)} presets; the +Drive holds {MAX_PRESETS}")
        if len(self.kits) > MAX_KITS:
            self.err(f"{len(self.kits)} kits; the +Drive holds {MAX_KITS}")
        return self

    def coverage(self):
        """{bank: [(role, count, capacity)]}"""
        out = {}
        for bank in BANKS:
            out[bank] = [(role, sum(1 for p in self.presets.values() if p["bank"] == bank and p["role"] == role),
                          hi - lo + 1) for role, lo, hi in roles(bank)]
        return out

    # --- sheets ------------------------------------------------------------------------
    def sheet_bank(self, bank, slots=None):
        slots = slots or {}
        world, kind = BANKS[bank]
        rows = sorted((p for p in self.presets.values() if p["bank"] == bank), key=lambda p: p["slot"])
        out = [f"# Preset bank {bank}: {world} {kind.lower()}", "",
               "Dial any of these onto a track from the Mac: `./djmono load --preset \"" + bank + ":NAME\" --track N`. "
               "To keep one on the device, save it to this slot (PRESET > MANAGE > slot > SAVE TO HERE) and name it.",
               ""]
        for role, lo, hi in roles(bank):
            group = [p for p in rows if p["role"] == role]
            out += [f"## {bank}{lo:03d}-{bank}{hi:03d} {ROLE_LABEL[role]}", ""]
            if not group:
                out += ["(empty)", ""]
                continue
            out += ["| Slot | Name | Sample | RAM | Recipe | Settings | Set by hand | Kits |",
                    "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for p in group:
                machine, params = self.sound(p)
                kits = ", ".join(sorted(self.used.get(f"{bank}:{p['name']}", [])))
                out.append(f"| {bank}{p['slot']:03d} | {p['name']} | {p['sample'].split('/', 1)[1]} | "
                           f"{slots.get(p['sample'], '')} | {p['recipe']} | {self.settings(params)} | "
                           f"{'; '.join(self.manual(machine, params))} | {kits} |")
            out.append("")
        return "\n".join(out)

    def sheet_kit(self, name, samples, slots=None):
        slots = slots or {}
        k = self.kits[name]
        names = sorted(samples)
        head = [f"# {name} ({k['world']})", ""]
        facts = [f"pattern {k.get('pattern', '-')}", f"{k['tempo']} BPM"] + ([f"swing {k['swing']}%"] if k["swing"] else [])
        head += [" · ".join(facts), ""]
        if k["ref"]:
            head += [f"**After:** {k['ref']}", ""]
        if k["feel"]:
            head += [f"**Feel:** {k['feel']}", ""]
        if k["play"]:
            head += [f"**Play it:** {k['play']}", ""]
        head += [f"Load: `./djmono load \"{name}\"` (set the machines below first)", "",
                 "| FX | Settings |", "| --- | --- |"]
        for page in dt2.FX:
            vals = k["fx"].get(page)
            head.append(f"| {dt2.FX_LABEL[page]} | {' · '.join(f'{fk} {v}' for fk, v in vals.items()) if vals else 'init'} |")
        head += ["", "| Trk | Role | Preset | Sample | RAM | Settings | Set by hand | Sample locks |",
                 "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for trk in range(1, 17):
            t = k["tracks"].get(trk)
            p = self.find(t["preset"]) if t else None
            if not p:
                head.append(f"| {trk} | {TRACK_NAME[trk]} | {t['preset'] if t else '-'} | | | | | |")
                continue
            machine, params = self.sound(p, t.get("tweaks"))
            locks = "; ".join(f"{g} ({len(fnmatch.filter(names, g))})" for g in t["locks"])
            head.append(f"| {trk} | {TRACK_NAME[trk]} | {p['bank']}{p['slot']:03d} {p['name']} | "
                        f"{p['sample'].split('/', 1)[1]} | {slots.get(p['sample'], '')} | {self.settings(params)} | "
                        f"{'; '.join(self.manual(machine, params))} | {locks} |")
        return "\n".join(head) + "\n"

    def sheet_project(self, pname, plan):
        """plan: [(ram bank, world, [(folder, count, first slot, last slot)])] from the slot map."""
        proj = self.projects[pname]
        out = [f"# Project {pname}", "",
               f"{proj.get('slots', 0)} samples, {proj.get('ram', 0) / 1e6:,.0f} MB of the 400 MB limit.", "",
               "## 1. Load the samples into RAM", "",
               f"New project, save it as {pname}. Then for each row: SAMPLES (FUNC + SAMPLING) > +DRIVE > open the "
               "folder, select all its samples, FUNC + YES and pick the RAM bank, LOAD TO PROJECT. Go in this order; "
               "the loader counts on each sample landing in the slot shown.", "",
               "| RAM bank | World | Folder | Samples | Slots |", "| --- | --- | --- | --- | --- |"]
        for bank, world, folders in plan:
            for folder, n, lo, hi in folders:
                out.append(f"| {bank} | {world} | /{folder} | {n} | {bank}{lo:03d}-{bank}{hi:03d} |")
        out += ["", "Check: open a folder in +DRIVE; loaded samples show their slot. Then `./djmono load --test`.", "",
                "## 2. Build the kits", "",
                "Pick the pattern, set the machines the kit sheet lists, run the load command, set LFO "
                "destinations, then PRESET/KIT > SAVE (KIT) with the kit's name.", "",
                "| Pattern | Kit | World | BPM | Load |", "| --- | --- | --- | --- | --- |"]
        for bank, kits in sorted(proj["banks"].items()):
            for i, kn in enumerate(kits, 1):
                k = self.kits.get(kn, {})
                out.append(f"| {bank}{i:02d} | {kn} | {k.get('world', '?')} | {k.get('tempo', '?')} | "
                           f"`./djmono load \"{kn}\"` |")
        out += ["", "## 3. Back up", "", "Save the project, then `./djmono backup`."]
        return "\n".join(out) + "\n"
