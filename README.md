# djmono

Sample library → Digitakt II, managed with git.

The library stays on the Mac. This repo holds the choices: which samples, which folder, what they're called. `djmono` renders those choices to 16-bit / 48 kHz and sends only what's new to the DT2.

Three worlds plus a shared core, mirrored on the +Drive:

| Folder | World |
|--------|-------|
| `DUB` | Dub techno on jazz and soul: chord stabs, Rhodes, horns, rides, tape |
| `RITE` | Tribal / shamanic: hand drums, shakers, bells, kalimba, drones |
| `DRIFT` | Ambient / new age: field recordings, bowls, soft pads |
| `CORE` | What two or more worlds share |

Why it's shaped this way: [docs/FRAMEWORK.md](docs/FRAMEWORK.md).

## Setup (once)

```sh
cd ~ && git clone git@github.com:kyleprier/djmono.git && cd djmono
brew install sox
./djmono doctor      # finds Samples From Mars and writes config/paths.local
./djmono scan        # indexes the library into index/ (commit it)
```

Optional: build `elektroid-cli` for one-command sync ([docs/DEVICE.md](docs/DEVICE.md#tools)). Without it, sync stages a folder for Transfer.

## The loop

```sh
./djmono ls DUB                # what each crate rule pulls
./djmono audition DUB/CHRD     # listen: k keep, enter skip, r replay, b back, q quit
./djmono build                 # render, check budgets, update state/drive.lock
./djmono sync                  # send new files (elektroid), or: ./djmono sync --transfer
./djmono status                # budgets, pending, retired
git add -A && git commit -m "DUB: chords from Vinyl Synths" && git push
```

## Layout

```
crates/<WORLD>/<FN>.txt   one file per +Drive folder: the curation (docs: crates/README.md)
config/paths.example      where the library lives (copied to paths.local, not in git)
config/codes.txt          source codes used as name prefixes
state/drive.lock          every sample built, where it came from, when it reached the DT2
index/                    scans of the library, so crates can be curated from anywhere
docs/                     FRAMEWORK · SOUND · SOURCES · DEVICE
tools/djmono.py           the tool (Python 3.9+, stdlib only, needs sox)
build/  backups/          local only
```

## Rules of the road

- Never edit or delete a sample on the device that a preset might use. The DT2 tracks samples by content, so djmono never overwrites.
- Shared by two worlds → CORE.
- CORE plus one world must fit one project: 400 MB and 1016 samples. `build` warns you.
- Commit after every build and sync.
