"""Digitakt II sound parameters: what a recipe may set, and how each value travels over MIDI.

Values are written the way the device shows them (tune -3, pan -20, type bp) and encoded here. CC and NRPN
numbers follow the DT2 MIDI implementation as published on midi.guide (July 2026); the OS 1.01 manual's
appendix has a few wrong entries. `./djmono load --test` checks the ones that matter on your unit.

Not reachable over MIDI, so set by hand: the machine, the filter machine, LFO destinations, and Werp/Stretch
BARS. Sheets and the loader list these as manual touches.
"""
from __future__ import annotations

import re

MACHINES = ("Oneshot", "Werp", "Stretch", "Repitch", "Slice", "Grid")
DEFAULT_MACHINE = "Oneshot"
FILTERS = ("Multi-Mode", "Lowpass 4", "Legacy LP/HP", "Comb-", "Comb+", "Equalizer")
DEFAULT_FILTER = "Multi-Mode"

PLAY = ("rev", "revloop", "loop", "fwd")          # CC 17 order; fwd is the default (3)
WAVES = ("tri", "sine", "sqr", "saw", "exp", "ramp", "rnd")
TRIGS = ("free", "trig", "hold", "one", "half")
MULTS = tuple(f"x{m}" for m in ("1", "2", "4", "8", "16", "32", "64", "128", "256", "512", "1k", "2k")) + \
        tuple(f".{m}" for m in ("1", "2", "4", "8", "16", "32", "64", "128", "256", "512", "1k", "2k"))
GRIDS = (4, 8, 16, 32, 64)                       # Grid machine slice counts, CC 22 index
FTYPES = {"lp": 0, "bp": 64, "hp": 127}          # Multi-Mode morphs LP > BP > HP

# LFO destination CCs. Which value picks which destination isn't documented, so ./djmono learn reads the
# values off the device (turn the DEST knob, the DT2 sends the CC) into config/lfo-dest.txt.
LFO_DEST_CC = {1: 105, 2: 115, 3: 28}
# The names recipes use, and what to pick on the device.
# names as the DT2's own destination list prints them (the filter entries follow the filter machine,
# so Multi-Mode shows MM FREQUENCY and MM RESONANCE)
LFO_DEST = {
    "freq": "MM FREQUENCY", "reso": "MM RESONANCE", "type": "MM FILTER TYPE", "env": "ENV DEPTH",
    "tune": "SRC TUNE", "start": "SRC START (STRT)", "slice": "SRC SLICE", "level": "SRC LEVEL",
    "sample": "SRC SAMPLE SLOT", "pan": "AMP PAN", "vol": "AMP VOLUME", "dec": "AMP DECAY TIME",
    "delay": "FX DELAY SEND", "reverb": "FX REVERB SEND", "chorus": "FX CHORUS SEND",
    "od": "FX OVERDRIVE", "srr": "FX SRR", "bits": "FX BIT REDUCTION",
}


class Param:
    """One track parameter. kind: int (lo..hi as shown), center (shown -64..63, sent +64), tune (NRPN),
    choice (names). send: always = reset to default on every load; set = only when a recipe sets it."""

    def __init__(self, page, label, cc=None, lo=0, hi=127, default=None, kind="int", choices=(), send="always",
                 lsb=None, nrpn=None, machines=()):
        self.page, self.label, self.cc, self.lo, self.hi = page, label, cc, lo, hi
        self.default, self.kind, self.choices, self.send = default, kind, choices, send
        self.lsb, self.nrpn, self.machines = lsb, nrpn, machines


_SRC_PLAY = ("Oneshot", "Repitch", "Stretch")
TRACK = {
    # SRC
    "tune":     Param("SRC", "TUNE", nrpn=(1, 0), lo=-60, hi=60, default=0, kind="tune"),
    "play":     Param("SRC", "PLAY", cc=17, default="fwd", kind="choice", choices=PLAY),
    "level":    Param("SRC", "LEV", cc=23, default=100),
    "start":    Param("SRC", "STRT", cc=20, hi=120, default=0, machines=_SRC_PLAY),
    "length":   Param("SRC", "LEN", cc=21, hi=120, default=120, machines=_SRC_PLAY),
    "looppos":  Param("SRC", "LOOP", cc=22, hi=120, send="set", machines=("Oneshot",)),
    "slice":    Param("SRC", "SLIC", cc=20, hi=64, send="set", machines=("Slice", "Grid")),
    "slicelen": Param("SRC", "SLEN", cc=21, hi=63, send="set", machines=("Slice", "Grid")),
    "grid":     Param("SRC", "GRID", cc=22, default=16, kind="grid", choices=GRIDS, machines=("Grid",)),
    # FLTR (Multi-Mode)
    "freq":     Param("FLTR", "FREQ", cc=74, default=127),
    "reso":     Param("FLTR", "RESO", cc=75, default=0),
    "type":     Param("FLTR", "TYPE", cc=76, default="lp", kind="ftype"),
    "env":      Param("FLTR", "ENV", cc=77, lo=-64, hi=63, default=0, kind="center"),
    "fatk":     Param("FLTR", "ATK", cc=70, default=0),
    "fdec":     Param("FLTR", "DEC", cc=71, default=64),
    "fsus":     Param("FLTR", "SUS", cc=72, default=0),
    "frel":     Param("FLTR", "REL", cc=73, default=64),
    "fdelay":   Param("FLTR", "ENV DELAY", cc=91, default=0),
    "keytrk":   Param("FLTR", "KEY TRACK", cc=92, hi=100, default=0),
    # AMP
    "atk":      Param("AMP", "ATK", cc=79, default=0),
    "hold":     Param("AMP", "HOLD", cc=80, default=127),
    "dec":      Param("AMP", "DEC", cc=81, default=64),
    "sus":      Param("AMP", "SUS", cc=82, default=127),
    "rel":      Param("AMP", "REL", cc=83, default=32),
    "pan":      Param("AMP", "PAN", cc=90, lo=-64, hi=63, default=0, kind="center"),
    "vol":      Param("AMP", "VOL", cc=89, default=110),
    # FX sends and track distortion
    "od":       Param("FX", "OVERDRIVE", cc=57, default=0),
    "bits":     Param("FX", "BIT REDUCTION", cc=54, default=0),
    "srr":      Param("FX", "SRR", cc=55, default=0),
    "delay":    Param("FX", "DELAY", cc=84, default=0),
    "reverb":   Param("FX", "REVERB", cc=85, default=0),
    "chorus":   Param("FX", "CHORUS", cc=12, default=0),
}
_LFO_CC = {1: dict(speed=(102, 58), mult=103, fade=104, wave=106, phase=107, trig=108, depth=(109, 59)),
           2: dict(speed=(112, 60), mult=113, fade=114, wave=116, phase=117, trig=118, depth=(119, 61)),
           3: dict(speed=(78, 62), mult=52, fade=53, wave=29, phase=30, trig=31, depth=(86, 63))}
for _n, _c in _LFO_CC.items():
    _p = f"LFO{_n}"
    TRACK[f"lfo{_n}.wave"] = Param(_p, "WAVE", cc=_c["wave"], kind="choice", choices=WAVES, send="set")
    TRACK[f"lfo{_n}.speed"] = Param(_p, "SPD", cc=_c["speed"][0], lsb=_c["speed"][1], lo=-64, hi=63, kind="center", send="set")
    TRACK[f"lfo{_n}.mult"] = Param(_p, "MULT", cc=_c["mult"], kind="choice", choices=MULTS, send="set")
    TRACK[f"lfo{_n}.depth"] = Param(_p, "DEP", cc=_c["depth"][0], lsb=_c["depth"][1], lo=-64, hi=63, default=0, kind="center")
    TRACK[f"lfo{_n}.fade"] = Param(_p, "FADE", cc=_c["fade"], lo=-64, hi=63, kind="center", send="set")
    TRACK[f"lfo{_n}.trig"] = Param(_p, "MODE", cc=_c["trig"], kind="choice", choices=TRIGS, send="set")
    TRACK[f"lfo{_n}.phase"] = Param(_p, "SPH", cc=_c["phase"], send="set")

# Kit FX pages: key -> (CC on the FX CONTROL channel, init value). Only the values a kit sets are sent.
FX = {
    "delay":  {"time": (21, 24), "pp": (22, 0), "width": (23, 63), "fb": (24, 50), "hp": (25, 32), "lp": (26, 96),
               "rev": (27, 0), "mix": (28, 100)},
    "reverb": {"pre": (29, 16), "decay": (30, 32), "freq": (31, 64), "gain": (89, 50), "hp": (90, 32), "lp": (91, 96),
               "mix": (92, 110)},
    "chorus": {"depth": (16, 127), "speed": (9, 32), "hp": (70, 0), "width": (71, 127), "dly": (12, 0),
               "rev": (13, 0), "mix": (14, 100)},
    "comp":   {"thr": (111, 32), "atk": (112, 24), "rel": (113, 32), "gain": (114, 63), "mix": (118, 0)},
}
FX_LABEL = {"delay": "DELAY", "reverb": "REVERB", "chorus": "CHORUS", "comp": "COMPRESSOR"}

# CCs outside the sound: sample select (send bank, then slot, then give the DT2 a moment)
CC_SAMPLE_BANK, CC_SAMPLE_SLOT = 24, 19
CC_FILTER_TRIG, CC_LFO_TRIG = 13, 14


# --- parsing ------------------------------------------------------------------------------
LFO_RE = re.compile(r"^(?P<wave>[a-z]+)/(?P<speed>[-+]?\d+)/(?P<mult>[x.]\w+)/(?P<depth>[-+]?\d+)(?:>(?P<dest>[\w.]+))?$")


def parse_params(text):
    """'freq=40 reso=25 lfo1=sine/8/x2/+8>freq' -> ({key: value}, [problems]). Values stay as written
    (ints or names); encode() checks and converts them."""
    out, bad = {}, []
    for tok in text.split():
        k, eq, v = tok.partition("=")
        if not eq or not v:
            bad.append(f"'{tok}' isn't key=value")
            continue
        m = re.fullmatch(r"lfo([123])", k)
        if m:
            lm = LFO_RE.match(v)
            if not lm:
                bad.append(f"'{tok}': write lfoN=wave/speed/mult/depth>dest, e.g. lfo1=sine/8/x2/+8>freq")
                continue
            n = m.group(1)
            out[f"lfo{n}.wave"], out[f"lfo{n}.speed"] = lm["wave"], int(lm["speed"])
            out[f"lfo{n}.mult"], out[f"lfo{n}.depth"] = lm["mult"], int(lm["depth"])
            if lm["dest"]:
                out[f"lfo{n}.dest"] = lm["dest"]
            continue
        m = re.fullmatch(r"lfo([123])(fade|trig|phase)", k)
        if m:
            k = f"lfo{m.group(1)}.{m.group(2)}"
        if k not in TRACK:
            bad.append(f"unknown parameter '{k}'")
            continue
        out[k] = int(v) if re.fullmatch(r"[-+]?\d+", v) else v
    return out, bad


def check_value(key, value, machine):
    """None if fine, else a message."""
    if key.endswith(".dest"):
        return None if value in LFO_DEST else f"LFO destination '{value}' (use {', '.join(LFO_DEST)})"
    p = TRACK[key]
    if p.machines and machine not in p.machines:
        return f"{key} needs the {'/'.join(p.machines)} machine (this is {machine})"
    if p.kind == "choice":
        return None if value in p.choices else f"{key}={value} (use {', '.join(p.choices)})"
    if p.kind == "grid":
        return None if value == "auto" or value in GRIDS else f"grid={value} (use auto or {', '.join(map(str, GRIDS))})"
    if p.kind == "ftype":
        if value in FTYPES or (isinstance(value, int) and 0 <= value <= 127):
            return None
        return f"type={value} (use lp, bp, hp or 0-127)"
    if not isinstance(value, int):
        return f"{key}={value} needs a number"
    if not p.lo <= value <= p.hi:
        return f"{key}={value} is outside {p.lo}..{p.hi}"
    return None


def resolve(machine, params):
    """Every parameter the loader sends for one track: defaults for the 'always' ones, then the recipe's."""
    out = {}
    for k, p in TRACK.items():
        if p.machines and machine not in p.machines:
            continue
        if p.send == "always" and p.default is not None:
            out[k] = p.default
    out.update({k: v for k, v in params.items() if not k.endswith(".dest")})
    return out


def encode(key, value):
    """[(kind, number, value)] messages for one parameter: ('cc', n, v) or ('nrpn', (msb, lsb), 14-bit)."""
    p = TRACK[key]
    if p.kind == "tune":
        return [("nrpn", p.nrpn, 8192 + 128 * value)]
    if p.kind == "choice":
        v = p.choices.index(value)
    elif p.kind == "grid":
        v = GRIDS.index(value)
    elif p.kind == "ftype":
        v = FTYPES.get(value, value)
    elif p.kind == "center":
        v = value + 64
    else:
        v = value
    msgs = [("cc", p.cc, max(0, min(127, v)))]
    if p.lsb is not None:
        msgs.append(("cc", p.lsb, 0))
    return msgs


def show(key, value):
    """How the value reads on the device screen (for sheets and the test checklist)."""
    if key.endswith(".dest"):
        return LFO_DEST.get(value, value)
    p = TRACK[key]
    if p.kind in ("center", "tune") and isinstance(value, int):
        return f"{value:+d}" if value else "0"
    if key == "play":
        return {"fwd": "FWD", "rev": "REV", "loop": "FWD LOOP", "revloop": "REV LOOP"}[value]
    if p.kind == "ftype" and isinstance(value, str):
        return value.upper()
    return str(value).upper() if isinstance(value, str) else str(value)


def parse_fx(text):
    """'time=24 fb=70' for one FX page -> ({key: int}, [problems])."""
    out, bad = {}, []
    for tok in text.split():
        k, eq, v = tok.partition("=")
        if not eq or not re.fullmatch(r"\d+", v):
            bad.append(f"'{tok}' isn't key=number")
        else:
            out[k] = int(v)
    return out, bad
