# djmono

Sample library → Digitakt II, managed with git.

The packs live on the NAS (`archive.meistervision.com`, `audio/sample packs`, one folder per collection). This repo holds the choices: which samples, what they're called, how each one is played. `djmono` renders samples for the DT2, sends only what's new, and dials kits and presets in over USB MIDI.

| World | Style |
|-------|-------|
| `DUB` | Dub techno on jazz and soul: chord stabs, Rhodes, horns, reverb guitar, rides, tape |
| `RITE` | Tribal / shamanic: skin drums, shakers, bells, marimba, flute, drones |
| `DRIFT` | Ambient / new age: field recordings, bells, glass, pads, guitar and pedal steel swells |
| `CORE` | What two or more worlds share |

One project, **TRIAD**, holds all of it: about 790 samples in 380 MB, 907 presets and 31 kits: 16 of them modelled on specific artists and records, four of them BRIDGE kits for moving between worlds. Changing worlds is changing patterns. Why it's shaped this way: [docs/FRAMEWORK.md](docs/FRAMEWORK.md). How to play it: [docs/SOUND.md](docs/SOUND.md).

## Setup (once)

Mount the NAS first: Finder > Go > Connect to Server (⌘K) > `smb://apollo@archive.meistervision.com`, then open the share that holds `audio/sample packs`.

```sh
cd ~ && git clone git@github.com:kyleprier/djmono.git && cd djmono
brew install sox
python3 -m venv .venv && .venv/bin/pip install mido python-rtmidi   # MIDI for load and browse
./djmono doctor      # finds the sample packs, writes config/paths.local, checks MIDI
./djmono scan        # indexes the library into index/lib.tsv (commit it); slow over SMB
```

On the DT2: SETTINGS > MIDI CONFIG > PORT CONFIG: INPUT FROM USB, RECEIVE CC/NRPN on. CHANNELS: TRACK 1–16 on channels 1–16, FX CONTROL CH OFF. Quit Transfer before using `load` if the port isn't found.

## Samples: crates to the +Drive

```sh
./djmono ls DUB                # what each crate rule pulls
./djmono audition DUB/STAB     # listen: k keep, enter skip, r replay, b back, q quit
./djmono build                 # render, check budgets, update state/drive.lock
./djmono sync                  # send new files (elektroid), or: ./djmono sync --transfer
./djmono status                # budgets, pending, retired
```

## TRIAD: RAM, kits, presets

```sh
./djmono slots                 # which RAM slot each synced sample takes; prints the load order
./djmono sheet                 # build/sheets/: project load order, one sheet per kit, the preset banks
./djmono load --test           # checks MIDI and the slot plan with a test sound on track 1
./djmono load "DEEP ECHO"      # dials all 16 tracks of a kit; then save the kit on the DT2
./djmono load "DEEP ECHO" --fx # sends the kit's delay/reverb/chorus/comp (asks you to free a channel)
./djmono load --preset "C:TAMA DEEP" --track 6   # one preset onto one track
./djmono browse hand rite --track 5 --kit RITE/NEW-KIT   # step through presets live; k writes into a kit
./djmono presets steel         # search the library
./djmono presets --seed        # new samples get presets (rules in presets/seed.txt)
./djmono check                 # every kit complete and in role, every preset has a sample, TRIAD fits
./djmono backup                # file a Transfer backup under backups/ and copy it to the NAS
```

First time: build and sync everything, `slots`, then make a new project called TRIAD and load the folders in the order `slots` prints (each into its RAM bank). After that, `load --test`, then one kit per pattern as the project sheet lists.

In the drums banks (A–D), **SL** presets are loops on a 16-slices-a-bar grid (play them on the grid, any tempo) and **LP** presets are whole loops stretched to tempo.

## Layout

```
crates/<WORLD>/<FN>.txt   one file per +Drive folder: the curation (crates/README.md)
presets/recipes.txt       how each kind of sound is dialled in, as DT2 parameter values
presets/<B>-<WORLD>-<KIND>.txt   banks A-D drums, E-H tones: slot, name, recipe, tags, sample
presets/seed.txt          which folders grow which ranges
kits/<WORLD>/<KIT>.txt    tempo, reference, how to play it, FX, 16 tracks
projects/TRIAD.txt        worlds to load, kits per pattern bank
config/midi.txt           how the loader talks to the DT2
config/paths.example      where the library lives (copied to paths.local, not in git)
state/drive.lock          every sample built, where it came from, when it reached the DT2
state/slots.txt           which RAM slot holds which sample in TRIAD
index/                    scans of the library, so crates can be curated from anywhere
docs/                     FRAMEWORK · SOUND · SOURCES · DEVICE
tools/                    djmono.py (commands) · rig.py (specs) · dt2.py (parameters, MIDI) · loader.py · seed.py
```

## Rules of the road

- Never edit or delete a sample on the device that a preset might use. The DT2 tracks samples by content.
- Shared by two worlds → CORE.
- Everything must fit TRIAD: 400 MB and 1016 samples. `build` and `check` warn you.
- Keep djmono's +Drive folders djmono-only: `slots` assumes each folder holds exactly what the lock says.
- Commit after every build, sync, slots run and preset session.
