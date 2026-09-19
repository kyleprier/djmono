"""The rig: presets, kits and projects as plain-text specs, checked against the samples djmono builds.

  presets/recipes.txt          recipe | machine | settings (starting points)
  presets/<BANK>-<NAME>.txt    slot | NAME | recipe | tags | WORLD/FN/sample
  kits/<WORLD>/<KIT-NAME>.txt  key = value header, then  track | BANK:PRESET NAME | sample-lock globs
  projects/<NAME>.txt          key = value (load = folders, bank X = kits)

The DT2's preset and kit files aren't documented, so djmono doesn't write them. It checks the specs are
complete and consistent, counts RAM, and prints the sheets you build from on the device.
"""
import fnmatch
import re
from pathlib import Path

# preset slot ranges by role (the same in every bank) and the kit tracks each role plays
ROLES = [
    ("perc", 1, 64, tuple(range(1, 9))),
    ("bass", 65, 96, (9,)),
    ("stab", 97, 144, (10,)),
    ("keys", 145, 176, (11,)),
    ("lead", 177, 208, (12,)),
    ("pad", 209, 232, (13,)),
    ("scape", 233, 244, (14,)),
    ("noise", 245, 248, (15,)),
    ("fx", 249, 256, (16,)),
]
TRACK_ROLE = {t: r for r, _, _, ts in ROLES for t in ts}
TRACK_NAME = {1: "low", 2: "snap", 3: "hat", 4: "metal", 5: "hand A", 6: "hand B", 7: "wood/shake", 8: "loop",
              9: "bass", 10: "stab", 11: "keys", 12: "lead", 13: "pad", 14: "scape", 15: "noise", 16: "fx"}
BANKS = {"A": "CORE", "B": "DUB", "C": "RITE", "D": "DRIFT", "E": "LIVE", "F": "OWN", "G": "PACKS", "H": "SCRATCH"}
WORLD_BANK = {"CORE": "A", "DUB": "B", "RITE": "C", "DRIFT": "D"}
TAGS = {"kick", "snare", "rimshot", "clap", "tom", "percussion", "hi-hat", "cymbal", "cowbell", "synth", "bass",
        "lead", "pad", "texture", "chord", "sound fx", "electronic", "metallic", "acoustic", "atmosphere", "noisy",
        "glitch", "hard", "soft", "dark", "bright", "vintage", "epic", "fail", "loop", "mine", "favourite"}
NAME_OK = re.compile(r"^[A-Z0-9 ~!@#$%^&()_+=-]{1,15}$")
MAX_PRESETS, MAX_KITS = 2048, 1024


def slot_role(slot):
    for role, lo, hi, _ in ROLES:
        if lo <= slot <= hi:
            return role
    return None


def _rows(path):
    for i, line in enumerate(path.read_text().splitlines(), 1):
        s = line.strip()
        if s and not s.startswith("#"):
            yield i, s


def _where(path, i, root):
    return f"{path.relative_to(root)}:{i}"


class Rig:
    def __init__(self, root):
        self.root = Path(root)
        self.errors, self.warnings = [], []
        self.recipes, self.presets, self.kits, self.projects = {}, {}, {}, {}

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    # --- load --------------------------------------------------------------------------
    def load(self):
        pdir, kdir, jdir = self.root / "presets", self.root / "kits", self.root / "projects"
        rfile = pdir / "recipes.txt"
        if rfile.exists():
            for i, s in _rows(rfile):
                parts = [p.strip() for p in s.split("|")]
                if len(parts) != 3:
                    self.err(f"{_where(rfile, i, self.root)}: expected  recipe | machine | settings")
                    continue
                if parts[0] in self.recipes:
                    self.err(f"{_where(rfile, i, self.root)}: recipe '{parts[0]}' defined twice")
                self.recipes[parts[0]] = {"machine": parts[1], "settings": parts[2]}
        for f in sorted(pdir.glob("[A-H]-*.txt")):
            bank = f.name[0]
            for i, s in _rows(f):
                where = _where(f, i, self.root)
                parts = [p.strip() for p in s.split("|")]
                if len(parts) != 5 or not parts[0].isdigit():
                    self.err(f"{where}: expected  slot | NAME | recipe | tags | WORLD/FN/sample")
                    continue
                slot, name, recipe, tags, sample = int(parts[0]), parts[1], parts[2], parts[3], parts[4]
                key = f"{bank}:{name}"
                if not 1 <= slot <= 256:
                    self.err(f"{where}: slot {slot} is outside 1-256")
                if any(p["bank"] == bank and p["slot"] == slot for p in self.presets.values()):
                    self.err(f"{where}: slot {bank}{slot:03d} is used twice")
                if key in self.presets:
                    self.err(f"{where}: preset name {key} is used twice")
                if not NAME_OK.match(name):
                    self.err(f"{where}: '{name}' needs to be 1-15 characters, A-Z 0-9 space and ~!@#$%^&()_+=-")
                self.presets[key] = dict(bank=bank, slot=slot, name=name, recipe=recipe, sample=sample,
                                         tags=[t.strip() for t in tags.split(",") if t.strip()], where=where)
        for f in sorted(kdir.glob("*/*.txt")):
            world, name = f.parent.name, f.stem.replace("-", " ")
            kit = dict(world=world, name=name, patterns=None, tempo=None, feel="", fx="", tracks={}, where=str(f.relative_to(self.root)))
            for i, s in _rows(f):
                where = _where(f, i, self.root)
                if "|" in s:
                    parts = [p.strip() for p in s.split("|")]
                    if not parts[0].isdigit() or len(parts) not in (2, 3):
                        self.err(f"{where}: expected  track | BANK:PRESET NAME | sample-lock globs")
                        continue
                    trk = int(parts[0])
                    if trk in kit["tracks"]:
                        self.err(f"{where}: track {trk} is listed twice")
                    locks = [g.strip() for g in parts[2].split(",") if g.strip()] if len(parts) == 3 else []
                    kit["tracks"][trk] = dict(preset=parts[1], locks=locks, where=where)
                elif "=" in s:
                    k, _, v = (x.strip() for x in s.partition("="))
                    if k in ("patterns", "tempo", "feel", "fx"):
                        kit[k] = v
                    else:
                        self.err(f"{where}: unknown key '{k}' (patterns, tempo, feel, fx)")
                else:
                    self.err(f"{where}: can't read this line")
            self.kits[name] = kit
        for f in sorted(jdir.glob("*.txt")):
            proj = dict(name=f.stem, load=[], banks={}, tempo="", where=str(f.relative_to(self.root)))
            for i, s in _rows(f):
                k, _, v = (x.strip() for x in s.partition("="))
                if k == "load":
                    proj["load"] = v.split()
                elif k.startswith("bank "):
                    proj["banks"][k.split()[1]] = [x.strip() for x in v.split(",") if x.strip()]
                elif k == "tempo":
                    proj["tempo"] = v
                else:
                    self.err(f"{_where(f, i, self.root)}: unknown key '{k}' (load, tempo, bank X)")
            self.projects[f.stem] = proj
        return self

    # --- check -------------------------------------------------------------------------
    def check(self, samples):
        """samples: {"WORLD/FN/name": bytes} for everything the crates produce."""
        names = sorted(samples)
        world_of = lambda path: path.split("/", 1)[0]
        for key, p in self.presets.items():
            if p["recipe"] not in self.recipes:
                self.err(f"{p['where']}: recipe '{p['recipe']}' isn't in presets/recipes.txt")
            if p["sample"] not in samples:
                self.err(f"{p['where']}: sample {p['sample']} isn't produced by any crate")
            bad = [t for t in p["tags"] if t.lower() not in TAGS]
            if bad:
                self.err(f"{p['where']}: unknown tag(s) {', '.join(bad)}")
            home = BANKS[p["bank"]]
            if home in WORLD_BANK and world_of(p["sample"]) not in (home, "CORE"):
                self.warn(f"{p['where']}: bank {p['bank']} ({home}) preset uses a {world_of(p['sample'])} sample")
        for name, k in self.kits.items():
            if len(name) > 15:
                self.err(f"{k['where']}: kit name '{name}' is over 15 characters")
            if k["patterns"] not in BANKS:
                self.err(f"{k['where']}: patterns = A-H (the TRIAD pattern bank) is required")
            missing = [t for t in range(1, 17) if t not in k["tracks"]]
            if missing:
                self.err(f"{k['where']}: incomplete, no track {', '.join(map(str, missing))}")
            for trk, t in sorted(k["tracks"].items()):
                if not 1 <= trk <= 16:
                    self.err(f"{t['where']}: track {trk} is outside 1-16")
                    continue
                p = self.presets.get(t["preset"])
                if not p:
                    self.err(f"{t['where']}: preset {t['preset']} isn't in presets/")
                    continue
                if slot_role(p["slot"]) != TRACK_ROLE[trk]:
                    self.err(f"{t['where']}: track {trk} is {TRACK_ROLE[trk]}, but {t['preset']} sits in the "
                             f"{slot_role(p['slot'])} range (slot {p['slot']})")
                if BANKS[p["bank"]] in WORLD_BANK and BANKS[p["bank"]] not in (k["world"], "CORE"):
                    self.err(f"{t['where']}: {k['world']} kit uses a {BANKS[p['bank']]} preset; share it through CORE")
                for g in t["locks"]:
                    hits = fnmatch.filter(names, g)
                    if not hits:
                        self.err(f"{t['where']}: sample lock '{g}' matches no sample")
                    elif any(world_of(h) not in (k["world"], "CORE") for h in hits):
                        self.warn(f"{t['where']}: sample lock '{g}' reaches outside {k['world']} and CORE")
        for pname, proj in self.projects.items():
            for bank, kits in proj["banks"].items():
                for kn in kits:
                    kit = self.kits.get(kn)
                    if not kit:
                        self.err(f"{proj['where']}: kit '{kn}' isn't in kits/")
                    elif kit["patterns"] != bank:
                        self.warn(f"{proj['where']}: kit '{kn}' says patterns {kit['patterns']} but sits in bank {bank}")
            loaded = [n for n in names if world_of(n) in proj["load"]]
            ram = sum(samples[n] for n in loaded)
            proj["ram"], proj["slots"] = ram, len(loaded)
            for kn in (k for ks in proj["banks"].values() for k in ks):
                kit = self.kits.get(kn)
                for t in (kit or {}).get("tracks", {}).values():
                    p = self.presets.get(t["preset"])
                    if p and world_of(p["sample"]) not in proj["load"]:
                        self.err(f"{proj['where']}: {kn} needs {p['sample']}, which isn't loaded")
        if len(self.presets) > MAX_PRESETS:
            self.err(f"{len(self.presets)} presets; the +Drive holds {MAX_PRESETS}")
        if len(self.kits) > MAX_KITS:
            self.err(f"{len(self.kits)} kits; the +Drive holds {MAX_KITS}")
        return self

    def coverage(self):
        """Rows of (bank, role, count) for the four world banks."""
        out = []
        for bank in "ABCD":
            for role, *_ in ROLES:
                n = sum(1 for p in self.presets.values() if p["bank"] == bank and slot_role(p["slot"]) == role)
                out.append((bank, role, n))
        return out

    # --- sheets ------------------------------------------------------------------------
    def preset_line(self, key):
        p = self.presets[key]
        r = self.recipes.get(p["recipe"], {"machine": "?", "settings": "?"})
        return p, r

    def sheet_bank(self, bank):
        rows = sorted((p for p in self.presets.values() if p["bank"] == bank), key=lambda p: p["slot"])
        out = [f"# Preset bank {bank}: {BANKS[bank]}", "",
               "Build each preset on a free track: load the sample, set the machine and settings, "
               "tag it, then save it to the slot. Settings are starting points on the 0-127 scale.", "",
               "| Slot | Name | Sample (+Drive) | Machine | Settings | Tags |", "| --- | --- | --- | --- | --- | --- |"]
        for p in rows:
            r = self.recipes.get(p["recipe"], {"machine": "?", "settings": "?"})
            out.append(f"| {bank}{p['slot']:03d} | {p['name']} | {p['sample']} | {r['machine']} | "
                       f"{r['settings']} | {', '.join(p['tags'])} |")
        return "\n".join(out) + "\n"

    def sheet_kit(self, name, samples):
        k = self.kits[name]
        names = sorted(samples)
        out = [f"# Kit {name} ({k['world']})", "",
               f"Pattern bank {k['patterns']} · {k['tempo']} BPM · {k['feel']}", "", f"**Kit FX:** {k['fx']}", "",
               "| Trk | Role | Preset | Sample | Sample locks |", "| --- | --- | --- | --- | --- |"]
        for trk in range(1, 17):
            t = k["tracks"].get(trk)
            if not t:
                out.append(f"| {trk} | {TRACK_NAME[trk]} | MISSING | | |")
                continue
            p = self.presets.get(t["preset"], {})
            ref = f"{p.get('bank', '?')}{p.get('slot', 0):03d} {p.get('name', t['preset'])}"
            locks = []
            for g in t["locks"]:
                hits = fnmatch.filter(names, g)
                locks.append(f"{g} ({len(hits)})")
            out.append(f"| {trk} | {TRACK_NAME[trk]} | {ref} | {p.get('sample', '')} | {'; '.join(locks)} |")
        return "\n".join(out) + "\n"

    def sheet_project(self, pname):
        proj = self.projects[pname]
        out = [f"# Project {pname}", "",
               f"{proj.get('slots', 0)} samples, {proj.get('ram', 0) / 1e6:,.0f} MB of the 400 MB limit.", "",
               f"1. New project, save as {pname}. Tempo: {proj['tempo']}.",
               f"2. Sample browser: open each subfolder of {', '.join('/' + w for w in proj['load'])}, "
               "select all, LOAD TO PROJECT.",
               "3. Load each kit into its own pattern:", ""]
        for bank, kits in sorted(proj["banks"].items()):
            worlds = sorted({self.kits[kn]["world"] for kn in kits if kn in self.kits})
            out.append(f"   - Pattern bank {bank} ({', '.join(worlds)}): " + ", ".join(
                f"{kn} \u2192 {bank}{i:02d}" for i, kn in enumerate(kits, 1)))
        out += ["", "4. Save the project, then back it up with Transfer (./djmono backup)."]
        return "\n".join(out) + "\n"
