# The djmono framework

How the Digitakt II is organised for three styles, and why.

| World | Style | Tempo home |
|-------|-------|-----------|
| **DUB** | Dub techno built on jazz and soul: chord stabs, Rhodes, horns, rides, tape and vinyl | 88–96 (jazz kits), 116–122 (dub techno) |
| **RITE** | Tribal / shamanic: hand drums, shakers, bells, kalimba, flute, drones | 100–120 |
| **DRIFT** | Ambient / new age: field recordings, bowls, bells, soft pads | 60–90 or free |
| **CORE** | Anything two worlds share: machine drums, noise beds, FX | n/a |

## The decisions

1. **The library stays on the NAS. Git holds the choices. The DT2 gets a rendered subset.** Every pack lives on `archive.meistervision.com` under `audio/sample packs`, one folder per collection; the Mac mounts it and renders from it. All the Samples From Mars is 75 GB; the +Drive is 20 GB and fills at about 30–35 min per GB. The DT2 carries a curated set, not an archive.
2. **The +Drive is organised by world, then function.** `/DUB/CHRD`, `/RITE/HAND`, `/DRIFT/FIELD`. The same function names appear in every world.
3. **CORE plus any one world fits in one project.** Budgets: CORE 100 MB / 250 files, each world 300 MB / 760 files. Together that's the DT2's per-project limit of 400 MB and 1016 slots. A world's whole palette can sit in RAM at once, and `./djmono build` warns if a crate outgrows it.
4. **Shared means CORE.** A sample used by two worlds moves to CORE. It is never duplicated.
5. **Samples are immutable once they're on the device.** The DT2 finds samples by content hash, not path. Moving or renaming on the device is safe. Changing a file's audio, or deleting it, breaks every preset and pattern that uses it. djmono never overwrites or deletes on the device. It lists retired samples for you to remove by hand.
6. **Haze is played, not baked in.** Crates render clean and consistent. The analogue feel comes from the DT2 (filters, overdrive, SRR, delay), resampling, and the Tascam 424. A print you love becomes a new sample with its own name.

## What was evaluated

**Folder layout**

| Option | Verdict |
|--------|---------|
| By pack (`Junos From Mars/...`) | ✗ Pack names mean nothing on the small screen. It mixes three styles in every folder and won't fit. |
| By function only (`KEYS/`, `PERC/`) | ~ Works for one style. With three, every browse digs through all of them. |
| **By world, then function** | ✓ You browse the world you're in plus CORE. Overlap has a home, and it maps 1:1 onto the project budget. |
| A folder per project | ✗ Clean deletes, but samples get duplicated and reuse across tracks breaks. |

**Where sounds live on the DT2**

| Unit | Holds | +Drive limit | Use it for |
|------|-------|--------------|-----------|
| Sample | audio | 20 GB | The crates |
| Preset | sample + all track settings, tags | 2048 (8 banks × 256) | Your honed sounds, a bank per world |
| Kit | 16 presets + mix, compressor, send FX | 1024 | Starting points per world |
| Project | 128 patterns, 16 songs, 400 MB of samples in RAM | 128 | One per track (studio), one per set (live) |

**Getting files onto the device**

| Tool | Verdict |
|------|---------|
| Elektron Transfer | ✓ Official. Drag and drop keeps folder trees and converts to 16/48. No automation, and it can't tell you what's new. |
| Elektroid CLI (open source, DT2 support since 3.1) | ✓ Scriptable, so djmono uses it for incremental sync when installed. It has to be built from source on macOS. |
| USB disk mode | ✗ Doesn't exist. Everything goes over USB-MIDI at about 0.5 MB/s. |

djmono does both. `./djmono sync` sends only new files, through Elektroid if it's installed, otherwise it stages exactly those files for a Transfer drag.

## The +Drive

```
/CORE    KICK SNR HAT HAND SHKR NOISE FX
/DUB     KICK SNR HAT CHRD KEYS HORN BASS PAD LOOP VOX
/RITE    KICK HAND SHKR WOOD BELL TONE DRONE LOOP VOX
/DRIFT   FIELD PAD KEYS BELL TONE DRONE
/FACTORY /INCOMING /RECORDED     (the DT2's own; djmono never touches them)
```

Names are `<code>_<fn>_<desc>`: `juno_chrd_warm-pad-c3`, `trt_kick_roomy`. The function is in the name because a project's sample list shows names without folders. Codes live in `config/codes.txt`; your record cuts use artist codes.

## Presets

| Bank | Holds |
|------|-------|
| A | CORE |
| B | DUB |
| C | RITE |
| D | DRIFT |
| E | Live-tuned versions for sets |
| F | Built from your own recordings |
| G | Third-party packs (HexCells, DigiSphere II...) |
| H | Scratch |

- **Name** a preset for its function plus character: `CHRD DUSTY M9`, `HAND UDU LOW`. The bank already says the world.
- **Tags** are a fixed list of 32; you can't add your own. Use one function tag (Chord, Percussion, Pad, Texture...) and one character tag (Vintage, Acoustic, Atmosphere, Dark, Soft...).
- `Favourite` marks keepers and `Mine` marks your own sources. The FILTER screen combines tags.
- **Save a preset from a trig:** hold the trig and press [PRESET/KIT]. It keeps the sound plus its p-locks. This is how a happy accident becomes a keeper.

## Kits and projects

**Templates.** Each world has a template project: `DUB TMPL`, `RITE TMPL`, `DRIFT TMPL`. Each one has the world plus CORE loaded into RAM, a starter kit, and send FX set. A new track starts with load template, then save as `DUB 004 NIGHTBUS`. On OS 1.10+ you can load one kit into all empty patterns at once.

**Kits.** Your four jazz kits (Slow Burn, Late Night, Broken Beat, CTI Groove) become DUB kits. Add a dub techno kit (chord, rim, ride, sub) and one starter kit each for RITE and DRIFT.

**Track map.** The same shape in every world: rhythm on 1–8, tone on 9–14, the air bed on 15, FX throws on 16. Live mutes stay in your hands across projects.

| Trk | DUB | RITE | DRIFT |
|----:|-----|------|-------|
| 1 | Kick | Low drum (surdo, floor) | Soft pulse |
| 2 | Rim / snare | Djembe | Shaker |
| 3 | Closed hat | Conga / bongo | Chime |
| 4 | Ride | Tabla / darbuka | Bowl / bell |
| 5 | Shaker / conga | Shaker / rattle | Field A |
| 6 | Ghost perc | Agogo / bell | Field B |
| 7 | Break (Slice) | Wood / clave | Field C (Werp) |
| 8 | Resample | Perc loop (Slice) | Field D |
| 9 | Sub bass | Drone bass | Low drone |
| 10 | Dub chord | Kalimba / mbira | FM bells / keys |
| 11 | Chord, 2nd voicing | Flute | Pad A |
| 12 | Rhodes / keys | Berimbau / harp | Pad B |
| 13 | Horn | Gong / drone | Flute / kalimba |
| 14 | Pad | Voice / chant | Voice |
| 15 | Vinyl / tape bed | Field bed | Long bed |
| 16 | FX / siren throw | FX | FX / reverse |

**Studio.** One track per project, so edits to one song never break another. Record into a DAW over Overbridge, which streams all 16 tracks in stereo plus the FX returns.

**Live sets.** One project per set: loading a project stops playback, and loading its samples can take a minute.

- Banks A–B hold DUB, C–D RITE, E–F DRIFT, G bridge patterns that blend two worlds, H spare.
- Use per-pattern tempo. For samples, take CORE plus about 100 MB from each world.
- Song mode handles a planned set; queued patterns handle an open one. Perform Kit keeps your tweaks across pattern changes.

## Growth

- **Vinyl cuts** (PCM-D100) go in `~/music production/recordings/vinyl`, named by hand (`trt_keys_rhodes-vamp`). A `rec:` line in the right crate, then build and sync.
- **Field recordings** go in `recordings/field`, then into DRIFT/FIELD, or RITE/VOX for breath and chant.
- **Resamples made on the DT2** land in `/RECORDED`. Move them into a world folder on the device (hash-safe). Pull a copy back with Transfer or `elektroid-cli elektron:sample:dl` for the archive. Don't re-render them.
- **New packs** go unzipped into `audio/sample packs` on the NAS, in their own folder. Add a rule to the crate, audition, then keep.

## Maintenance

- Commit after every build and sync. `state/drive.lock` is the record of what's on the device.
- Back up projects and presets with Transfer (`.dt2prj`, `.dt2pst`; they include their samples) into `backups/`, and copy that to the NAS. Do this before every OS update; 1.15+ runs a filesystem check that can mean reformatting.
- `./djmono status` shows budgets, what's waiting to sync, and retired samples. Delete a retired sample on the device only once nothing uses it.
