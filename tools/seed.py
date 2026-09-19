"""Grow the preset banks from presets/seed.txt: every rule turns matching samples into presets.

A rule adds presets for samples that don't already have one with that recipe in that bank, into the free
slots of its role range. Existing presets never move or change, so slots stay put once they're on the device.
When there are more samples than slots, the pick alternates between instrument types so the range stays varied.
"""
import fnmatch
import re
from pathlib import Path

import rig

MODEL = {"808": "808", "909": "909", "cr78": "CR78", "lm1": "LM1", "505": "505", "sp12": "SP12", "101": "101",
         "juno": "JUNO", "dx1": "DX", "vp33": "VP330", "s612": "S612", "sh5": "SH5", "ob": "OB", "808l": "808",
         "vdrm": "VINYL"}
DROP = {"color", "clean", "standard", "trim", "repaired", "no", "filt", "full", "std", "sat", "bd", "sd", "hh",
        "perc", "hit", "hits", "long", "the", "and", "of", "in", "fx", "wav", "various", "vari", "attack"}
ABBR = {"DRUM": "DR", "DRUMS": "DR", "SIDE": "SD", "CHOKE": "CHK", "CHOKED": "CHK", "SOFT": "SFT", "GHOST": "GST",
        "ROLL": "RL", "HIGH": "HI", "LOW": "LO", "SHAKER": "SHK", "GUITAR": "GTR", "TRUMPET": "TPT",
        "TRUMPETS": "TPT", "STRINGS": "STR", "STRING": "STR", "PIANO": "PNO", "VIBRATO": "VIB", "TREMOLO": "TREM",
        "CHORUS": "CHR", "ACOUSTIC": "AC", "ELECTRIC": "EL", "DEGRADED": "DGR", "MEDIUM": "MED", "SHORT": "SHT",
        "FILTER": "FLT", "ORGAN": "ORG", "ENSEMBLE": "ENS", "FEMALE": "FEM", "CINEMATIC": "CINE", "CINEMA": "CINE",
        "REVERSE": "REV", "RATTLE": "RTL", "TAMBOURINE": "TAMB", "TAMBORIM": "TAMBRM", "CABASA": "CABS",
        "DJEMBE": "DJMB", "DARABUKA": "DRBK", "PANDIERO": "PNDRO", "REPENIQUE": "REPQ", "WATERPHONE": "WTRPH",
        "FINGER": "FNGR", "CYMBALS": "CYM", "CYMBAL": "CYM", "TRIANGLE": "TRI", "COWBELL": "CBEL",
        "WOODBLOCK": "WBLK", "BLOCK": "BLK", "BONGOS": "BONGO", "MARACAS": "MARACA", "SWEEP": "SWP",
        "RESONANCE": "RES", "TELAHARMONIC": "TELAH", "ELEMENTS": "ELEM", "DARKMODULATOR": "DARKMOD",
        "MODULATOR": "MOD", "VORTEX": "VRTX", "MALLET": "MLLT", "CELESTE": "CLST", "VIBRAPHONE": "VIBES",
        "SAXOPHONE": "SAX", "CLARINET": "CLAR", "QUARTET": "QRT", "PRISTINECELESTE": "CELESTE",
        "WARBLECELESTE": "WRBL CLST", "ANKLUNGS": "ANKLUNG", "SHEKERE": "SHEKR", "CAXIXI": "CAXIXI",
        "EXPLOSION": "XPLD", "BREAK": "BRK", "SINGLE": "SGL", "VINYL": "VNL", "CHORDAL": "CHRD", "LINDRUM": "LINN",
        "DRUMULATOR": "DRMLTR", "MACHINEDRUM": "MD", "SAKATA": "SKT", "PERKONS": "PRKNS", "XBASE": "XB",
        "CRASHING": "CRASH", "TAKEOFF": "TKOFF", "BABIES": "BABY", "STATIC": "STAT"}
NOTE = re.compile(r"^[a-g]s?-?\d?$")
# words inside glued names (ballkickbounce, fmbellfx), so they can be split and shortened
VOCAB = set("""ball kick bounce big plastic bin bottle crinkle clap damp glass smash garden fork snare metal gate no
attack impact skip crash twig snap water slap splash wine breath chopping boards board gulp keys drop carpet squelch
melon wood bell bells hat tom floor coins click pot inner side open closed vortex fm fx chirp bass drone hiss machine
ensemble female male vibe pristine celeste warble star piano dream like vibes digi pianet jazzy organ soft horns pan
flute box cello deep planet resonant steel drums drum old banjo pads pad dive plava laguna fancy chair lovely some
studs walter becker combo udu igbo monkey high timp caps shekere bamboo slit china block turtle shell spring guiro
pocket padel tin single large rattle tama toca mini agu hair fire gnawa peg quinto riq sabar tubano low hit choke ch
ghost roll strings string voice voices""".split())
# what a name's prefix already says, so the description doesn't repeat it
IMPLIED = {"BD": {"KICK"}, "SD": {"SNARE", "SD"}, "CP": {"CLAP", "CLAPS"}, "HH": {"HAT", "HH"}, "OH": {"OH", "HAT"},
           "RD": {"RIDE"}, "RIM": {"RIM", "RIMSHOT", "SHOT"}, "GTR": {"GUITAR"}, "STEEL": {"GUITAR"},
           "VOX": {"VOX", "VOICE"}, "PAD": {"PAD", "PADS"}, "FX": {"FX"}, "DRONE": {"DRONE", "DRONES"}}


def split_glued(t):
    """'ballkickbounce' -> ['ball', 'kick', 'bounce']; 'tom2openpotwood' -> ['tom', '2', 'open', 'pot', 'wood']."""
    if re.fullmatch(r"[a-z]{1,2}\d+|\d+[a-z]", t):
        return [t]  # lm1, m44, 70s: model names, keep whole
    out = []
    for piece in re.findall(r"\d+|[a-z]+", t):
        if len(piece) < 7 or piece in VOCAB or piece.isdigit():
            out.append(piece)
            continue
        best = {0: []}
        for i in range(1, len(piece) + 1):
            for j in range(max(0, i - 10), i):
                if j in best and piece[j:i] in VOCAB and (i not in best or len(best[j]) + 1 < len(best[i])):
                    best[i] = best[j] + [piece[j:i]]
        out += best.get(len(piece), [piece])
    return out


def words(sample):
    """Descriptive words for a sample name: model code first, then its description, noise removed."""
    stem = sample.rsplit("/", 1)[-1]
    code, _, rest = stem.partition("_")
    fn, _, desc = rest.partition("_")
    out = [MODEL[code]] if code in MODEL else []
    parts = [p for p in re.split(r"[-_\s]+", desc) if p]
    if parts and len(parts[-1]) >= 3 and any(d.startswith(parts[-1]) and d != parts[-1] for d in DROP):
        parts.pop()  # a word like 'clean' cut short by the 32-character name limit
    for part in parts:
        for t in split_glued(part):
            if t and t not in DROP and t != fn and not NOTE.match(t):
                out.append(t.upper())
    return out if len(out) > (code in MODEL) else out + [fn.upper()]


def fit(ws, room, loop=False):
    """Join words into at most `room` characters: abbreviate, drop variant letters and numbers, then drop words
    (a loop keeps its tempo and its last word, anything else keeps its first words), then squeeze vowels."""
    ws = [w for i, w in enumerate(ws) if w and w not in ws[:i]]
    size = lambda: len(" ".join(ws))
    for i in sorted(range(len(ws)), key=lambda i: -len(ws[i])):
        if size() <= room:
            break
        ws[i] = ABBR.get(ws[i], ws[i])
    ws = " ".join(ws).split()
    keep = 1 if loop and ws and ws[0].isdigit() else 0
    for weak in (lambda w: len(w) == 1 and w.isalpha(), lambda w: w.isdigit()):
        for i in reversed(range(keep, len(ws))):
            if size() > room and len(ws) > 1 and weak(ws[i]):
                del ws[i]
    while size() > room and len(ws) > (2 if loop else 1):
        del ws[-2 if loop else -1]
    while size() > room:
        i = max(range(len(ws)), key=lambda i: len(ws[i]))
        if len(ws[i]) <= 4:
            break
        ws[i] = ws[i][0] + re.sub(r"[AEIOU]", "", ws[i][1:]) if re.search(r"[AEIOU]", ws[i][1:]) else ws[i][:4]
    return " ".join(ws)[:room].strip()


def make_name(template, sample, loop, taken):
    """Fill {d} in the template, fit to 12 characters, keep it unique in the bank."""
    head, _, tail = template.partition("{d}")
    room = 12 - len(head) - len(tail)
    fixed = set(template.replace("{d}", " ").split())
    fixed |= {w for f in fixed for w in IMPLIED.get(f, ())}
    base = (head + fit([w for w in words(sample) if w not in fixed], room, loop) + tail).strip()
    name, n = base, 2
    while name in taken:
        suffix = f" {n}"
        name = base[:12 - len(suffix)].rstrip() + suffix
        n += 1
    return name


def kind_of(sample):
    """Instrument type, for picking a varied set: the first descriptive word."""
    ws = words(sample)
    ws = [w for w in ws if w not in MODEL.values()] or ws
    return ws[0] if ws else ""


def parse_rules(path):
    rules = []
    for i, line in enumerate(Path(path).read_text().splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split("|")]
        head = parts[0].split()
        if len(parts) not in (5, 6) or len(head) != 2 or head[0] not in rig.BANKS:
            raise ValueError(f"{path}:{i}: expected  BANK role | samples | recipe | tags | name | options")
        bank, role = head
        opts = dict(o.split("=", 1) for o in parts[5].split()) if len(parts) == 6 else {}
        rules.append(dict(bank=bank, role=role, glob=parts[1], recipe=parts[2], tags=parts[3], name=parts[4],
                          limit=int(opts.get("limit", 999)), prefer=opts.get("prefer"), line=i))
    return rules


def plan(r, samples, rules, reserve=2):
    """New preset lines per bank: {bank: [(slot, name, recipe, tags, sample)]}, plus notes."""
    added, notes = {}, []
    names = sorted(samples)
    for rule in rules:
        bank, role = rule["bank"], rule["role"]
        try:
            lo, hi = rig.role_range(bank, role)
        except KeyError:
            notes.append(f"seed.txt:{rule['line']}: bank {bank} has no role '{role}'")
            continue
        if rule["recipe"] not in r.recipes:
            notes.append(f"seed.txt:{rule['line']}: recipe '{rule['recipe']}' isn't in recipes.txt")
            continue
        existing = [p for p in r.presets.values() if p["bank"] == bank] + \
                   [dict(slot=s, name=n, recipe=rc, sample=sm) for s, n, rc, _, sm in added.get(bank, [])]
        have = {(p["sample"], p["recipe"]) for p in existing}
        used_slots = {p["slot"] for p in existing}
        taken = {p["name"] for p in existing}
        cands = [s for s in fnmatch.filter(names, rule["glob"]) if (s, rule["recipe"]) not in have]
        if not cands:
            continue  # limit counts what the rule already made, so reruns don't keep adding
        # varied order: one of each instrument type, then the next of each, ...
        pref = rule["prefer"]
        by_kind = {}
        for s in sorted(cands, key=lambda s: (not (pref and pref in s), s)):
            by_kind.setdefault(kind_of(s), []).append(s)
        order = []
        while any(by_kind.values()):
            for k in sorted(by_kind):
                if by_kind[k]:
                    order.append(by_kind[k].pop(0))
        free = [s for s in range(lo, hi + 1 - reserve) if s not in used_slots]
        already = sum(1 for p in existing if p["recipe"] == rule["recipe"] and fnmatch.fnmatch(p["sample"], rule["glob"]))
        room = max(0, min(len(free), rule["limit"] - already))
        wanted = min(len(order), max(0, rule["limit"] - already))
        if wanted > len(free):
            notes.append(f"seed.txt:{rule['line']}: {bank} {role} is full; {wanted - len(free)} of {rule['glob']} left out")
        loop = role in ("slice", "loop")
        for slot, s in zip(free, order[:room]):
            name = make_name(rule["name"], s, loop, taken)
            taken.add(name)
            added.setdefault(bank, []).append((slot, name, rule["recipe"], rule["tags"], s))
    return added, notes


def write(root, added):
    """Append new presets to the bank files, keeping each file in slot order."""
    for bank, rows in added.items():
        f = Path(root) / "presets" / rig.bank_file(bank)
        lines = f.read_text().splitlines() if f.exists() else header(bank)
        for slot, name, recipe, tags, sample in rows:
            lines.append(f"{slot:03d} | {name:<12} | {recipe:<13} | {tags:<22} | {sample}")
        f.write_text("\n".join(sort_lines(lines)) + "\n")


def header(bank):
    world, kind = rig.BANKS[bank]
    ranges = " · ".join(f"{lo:03d}-{hi:03d} {role}" for role, lo, hi in rig.roles(bank))
    return [f"# Preset bank {bank}: {world} {kind.lower()}", f"# {ranges}",
            "# slot | NAME (12 max) | recipe        | tags                   | sample on the +Drive | parameters"]


def sort_lines(lines):
    """Comments at the top stay; preset rows sort by slot."""
    head = [l for l in lines if not re.match(r"^\s*\d", l)]
    rows = sorted((l for l in lines if re.match(r"^\s*\d", l)), key=lambda l: int(l.split("|")[0]))
    return head + rows
