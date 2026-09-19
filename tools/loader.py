"""Send kits and presets to the Digitakt II over USB MIDI, and keep the map of which RAM slot holds which sample.

The DT2 can't take preset or kit files from the Mac, but every sound parameter answers to MIDI. So a kit is
built by dialling each track over its own channel (tracks 1-16 on channels 1-16), then saving the kit on the
device. Samples are picked by RAM slot, which is why the load order into the project matters: state/slots.txt
records where every sample lands, and the project sheet lists the order.
"""
import re
import time
import wave
from pathlib import Path

import dt2
import rig

RAM_BANKS = {"CORE": "A", "DUB": "BC", "RITE": "DEF", "DRIFT": "G"}  # H stays free for your own sampling
BANK_SLOTS = 127
SLOTS_HEADER = ("# RAM slot -> sample in the TRIAD project. ./djmono slots keeps this in step with the crates;\n"
                "# load samples in the order the project sheet gives and they land in these slots.\n")
MIDI_DEFAULTS = {"port": "Digitakt", "slot_base": "0", "bank_base": "0", "sort": "ascii", "gap_ms": "3",
                 "sample_ms": "100", "fx_channel": "16"}


def natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def read_midi_config(path):
    cfg = dict(MIDI_DEFAULTS)
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, _, v = (x.strip() for x in line.partition("="))
                cfg[k] = v
    return cfg


# --- RAM slots --------------------------------------------------------------------------------------
class SlotMap:
    def __init__(self, path, sort="ascii"):
        self.path = Path(path)
        self.sort = natural if sort == "natural" else (lambda s: s)
        self.slots = {}  # "B014" -> "DUB/STAB/..."
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line and not line.startswith("#"):
                    slot, _, sample = line.partition("\t")
                    self.slots[slot.strip()] = sample.strip()

    @property
    def of(self):
        return {s: k for k, s in self.slots.items()}

    def update(self, samples):
        """Keep assigned slots, free retired ones, place new samples. Returns (added, retired) lists of
        (slot, sample) in load order."""
        samples = set(samples)
        retired = sorted((k, s) for k, s in self.slots.items() if s not in samples)
        for k, _ in retired:
            del self.slots[k]
        have = set(self.slots.values())
        new = sorted((s for s in samples if s not in have),
                     key=lambda s: (s.rsplit("/", 1)[0], self.sort(s.rsplit("/", 1)[1])))
        groups = {}
        for s in new:
            groups.setdefault(s.rsplit("/", 1)[0], []).append(s)
        added = []
        for folder, files in groups.items():
            world = folder.split("/")[0]
            banks = RAM_BANKS.get(world)
            if not banks:
                raise ValueError(f"{folder}: no RAM bank for world {world}")
            free = {b: [n for n in range(1, BANK_SLOTS + 1) if f"{b}{n:03d}" not in self.slots] for b in banks}
            home = [b for b in banks if any(v.startswith(folder + "/") for k, v in self.slots.items() if k[0] == b)]
            fits = [b for b in home + list(banks) if len(free[b]) >= len(files)]
            order = fits[:1] + [b for b in banks if b not in fits[:1]]
            queue = list(files)
            for b in order:
                while queue and free[b]:
                    slot = f"{b}{free[b].pop(0):03d}"
                    self.slots[slot] = queue.pop(0)
                    added.append((slot, self.slots[slot]))
            if queue:
                raise ValueError(f"{world} needs more than RAM banks {banks}: {len(queue)} samples don't fit")
        return added, retired

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(self.slots.items())
        self.path.write_text(SLOTS_HEADER + "".join(f"{k}\t{v}\n" for k, v in rows))

    def runs(self, items=None):
        """[(bank, world, [(folder, count, first, last)])]: consecutive slots per folder, in slot order."""
        items = sorted(items if items is not None else self.slots.items())
        out = []
        for slot, sample in items:
            bank, n, folder = slot[0], int(slot[1:]), sample.rsplit("/", 1)[0]
            if not out or out[-1][0] != bank:
                out.append((bank, folder.split("/")[0], []))
            runs = out[-1][2]
            if runs and runs[-1][0] == folder and runs[-1][3] == n - 1:
                runs[-1] = (folder, runs[-1][1] + 1, runs[-1][2], n)
            else:
                runs.append((folder, 1, n, n))
        return out


# --- MIDI ---------------------------------------------------------------------------------------------
class Port:
    """A MIDI output (mido), or a recorder for dry runs and tests."""

    def __init__(self, cfg, dry=False):
        self.cfg, self.dry, self.sent = cfg, dry, []
        self.gap = int(cfg["gap_ms"]) / 1000
        self.out = None
        if not dry:
            try:
                import mido
            except ImportError:
                raise SystemExit("MIDI needs mido: python3 -m venv .venv && .venv/bin/pip install mido python-rtmidi"
                                 " (./djmono then uses it automatically)")
            try:
                names = mido.get_output_names()
            except Exception as e:  # no MIDI backend (python-rtmidi missing or broken)
                raise SystemExit(f"MIDI isn't working ({e}). Try: .venv/bin/pip install --upgrade python-rtmidi")
            hits = [n for n in names if cfg["port"].lower() in n.lower()]
            if not hits:
                raise SystemExit(f"no MIDI port matching '{cfg['port']}' (found: {', '.join(names) or 'none'}). "
                                 "Is the Digitakt on USB and in USB MIDI mode (or Overbridge)?")
            self.mido, self.out = mido, mido.open_output(hits[0])

    def cc(self, ch, num, val):
        self.sent.append(("cc", ch, num, val))
        if self.out:
            self.out.send(self.mido.Message("control_change", channel=ch - 1, control=num, value=val))
            time.sleep(self.gap)

    def nrpn(self, ch, msb, lsb, value):
        self.sent.append(("nrpn", ch, (msb, lsb), value))
        for num, val in ((99, msb), (98, lsb), (6, value >> 7), (38, value & 127)):
            if self.out:
                self.out.send(self.mido.Message("control_change", channel=ch - 1, control=num, value=val))
                time.sleep(self.gap)

    def pause(self, ms):
        if self.out:
            time.sleep(ms / 1000)

    def close(self):
        if self.out:
            self.out.close()


def wav_seconds(path):
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    except (OSError, wave.Error, EOFError):
        return None


def dial(port, track, slot, machine, params, cfg, seconds=None, sample=""):
    """Send one sound to one track: sample first, then every parameter. Returns what was sent, for display."""
    bank, n = "ABCDEFGH".index(slot[0]), int(slot[1:])
    port.cc(track, dt2.CC_SAMPLE_BANK, bank + int(cfg["bank_base"]))
    port.pause(int(cfg["sample_ms"]))
    port.cc(track, dt2.CC_SAMPLE_SLOT, n - 1 + int(cfg["slot_base"]))
    port.pause(int(cfg["sample_ms"]))
    values = dt2.resolve(machine, params)
    if values.get("grid") == "auto":
        values["grid"], _ = rig.grid_for(sample, seconds)
    for key, value in values.items():
        for kind, num, val in dt2.encode(key, value):
            if kind == "cc":
                port.cc(track, num, val)
            else:
                port.nrpn(track, *num, val)
    return values


def send_fx(port, ch, fx):
    for page, vals in fx.items():
        for k, v in vals.items():
            port.cc(ch, dt2.FX[page][k][0], v)


def fx_lines(fx):
    return [f"  {dt2.FX_LABEL[p]:<11} " + "  ".join(f"{k} {v}" for k, v in vals.items()) for p, vals in fx.items()]


# --- the test sound ------------------------------------------------------------------------------------
TEST_PARAMS = {"tune": -3, "play": "rev", "level": 90, "freq": 64, "reso": 20, "type": "bp", "env": 10,
               "atk": 10, "dec": 50, "pan": -20, "vol": 100, "od": 10, "srr": 5, "delay": 30, "reverb": 40,
               "chorus": 20, "lfo1.wave": "sine", "lfo1.speed": 16, "lfo1.mult": "x4", "lfo1.depth": 10}
TEST_SCREEN = [
    ("SRC", "SMP shows {sample} · TUNE -3 · PLAY REV · LEV 90"),
    ("FLTR", "FREQ 64 · RESO 20 · TYPE about half way (band-pass) · ENV DEPTH +10"),
    ("AMP", "ATK 10 · DEC 50 · PAN L20 · VOL 100"),
    ("FX", "OVERDRIVE 10 · SRR 5 · DELAY 30 · REVERB 40 · CHORUS 20"),
    ("LFO1", "WAVE SINE · SPD 16.00 · MULT x4 · DEP 10.00"),
]
