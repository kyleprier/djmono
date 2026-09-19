# The djmono framework

How the Digitakt II is organised for three styles, and why. Approved design: [djmono: Digitakt II setup design](https://claude.ai/code/artifact/e181c733-8ad6-4ed6-8b80-b66d0f764c17).

| World | Style | Pattern banks | Tempo home |
|-------|-------|---------------|-----------|
| **DUB** | Dub techno on jazz and soul: chord stabs, Rhodes, horns, reverb guitar, rides, tape | A (dub techno), B (jazz and soul) | 112–126, 88–114 |
| **RITE** | Tribal / shamanic: skin drums, shakers, bells, marimba, flute, drones | C (driving), D (slow, 6/8, half time) | 100–123, 80–140/2 |
| **DRIFT** | Ambient / new age: field recordings, bells, glass, pads, guitar and pedal steel swells | E (pulse), F (near beatless) | 60–96 |
| **BRIDGE** | Kits that cross worlds, for transitions | G | 88–122 |
| **CORE** | What two or more worlds share: machine drums, bells, noise beds, FX | n/a | n/a |

Pattern bank H is yours.

## The decisions

1. **One project, TRIAD, holds all three worlds.** A pattern carries its own kit, so changing worlds is a pattern change. Loading a project stops playback; changing patterns doesn't.
2. **The whole library fits in TRIAD.** 400 MB and 1016 slots per project. Budgets: CORE 30 MB, DUB 110, RITE 110, DRIFT 140, 10 MB spare. `build` and `check` enforce them. Beds are cut to 20 s.
3. **Every kit has the same 16-track shape.** Tracks 1–8 are drums, 9–16 are one tone role each, so the same mutes work in every kit.
4. **Presets are the instruments, and there are a lot of them.** About 900, one drums bank and one tones bank per world, every slot range meaning the same role in every bank. Kits are built from them; new kits start from them.
5. **Loops are marked.** In every drums bank, `SL` presets are loops cut into a slice grid (play them on the grid, at any tempo) and `LP` presets are whole loops stretched to tempo.
6. **The Mac dials sounds in over MIDI.** The DT2 won't take preset or kit files, but every sound parameter answers to MIDI, so `./djmono load` builds a kit in seconds and you save it on the device.
7. **The library stays on the NAS; git holds the choices; the DT2 gets a rendered subset.**
8. **Samples are immutable once they're on the device.** The DT2 finds samples by content hash. djmono never overwrites or deletes on the device.
9. **Shared means CORE.** A kit uses its own world's banks plus CORE's. BRIDGE kits may use any bank.
10. **Haze is played, not baked in.** Samples render clean. The analogue feel comes from filters, overdrive, SRR, LFO wow and send FX, plus prints through the Tascam 424.

## The kit shape

| Trk | Role | Takes |
|----:|------|-------|
| 1 | Low | any drum preset (banks A–D) |
| 2 | Snap | any drum preset |
| 3 | Hat / shake | any drum preset |
| 4 | Metal | any drum preset |
| 5–6 | Hand A, Hand B | any drum preset |
| 7 | Wood / shake | any drum preset |
| 8 | Loop | any drum preset, usually SL or LP |
| 9 | Bass | tone BASS |
| 10 | Stab | tone STAB |
| 11 | Keys | tone KEYS |
| 12 | Lead: horns, strings, guitar, steel, voice | tone LEAD |
| 13 | Pad | tone PAD |
| 14 | Scape: field recording or drone | tone SCAPE |
| 15 | Noise bed | tone NOISE |
| 16 | FX throw | tone FX |

Tracks 13–16 carry through pattern changes as each world's soundscape. Options come from **sample locks**: a kit lists the folders a track can step through, and they're all in RAM.

## Presets

| Bank | Drums | | Bank | Tones |
|------|-------|-|------|-------|
| A | CORE | | E | CORE |
| B | DUB | | F | DUB |
| C | RITE | | G | RITE |
| D | DRIFT | | H | DRIFT |

| Drums slots | Role | | Tones slots | Role |
|------|------|-|------|------|
| 001–024 | LOW | | 001–032 | BASS |
| 025–048 | SNAP | | 033–080 | STAB |
| 049–072 | HAT & SHAKE | | 081–112 | KEYS |
| 073–096 | METAL | | 113–160 | LEAD |
| 097–160 | HAND | | 161–192 | PAD |
| 161–192 | WOOD & FOUND | | 193–224 | SCAPE |
| 193–224 | **SL** slice grid | | 225–240 | NOISE |
| 225–256 | **LP** whole loop | | 241–256 | FX |

- **Recipes** (`presets/recipes.txt`) are the sound design: machine plus parameter values as the DT2 shows them. About 60, from `kick-dub` to `steel-swell`. A preset is a recipe plus a sample plus any tweaks.
- **Names:** 12 characters, upper case. `SL`/`LP` prefixes are enforced so loops can't hide.
- **Growth:** `presets/seed.txt` says which folders feed which ranges with which recipe. `./djmono presets --seed` fills free slots from new samples and never moves an existing preset. Each range keeps two slots free for your own.
- **On the device:** the library lives in git and loads onto any track from the Mac. Save the ones you love into their slot on the DT2 so they're there without the Mac.

## Kits and TRIAD

31 kits, each after a real record or scene (the `ref` line in each kit file, sources in [SOUND.md](SOUND.md)):

| Pattern | Kits |
|---------|------|
| A · DUB | ONE DROP DUB 126 · CHORD DUST 124 · FIELD ECHO 120 · CHORD ROOM 120 · DEEP ECHO 118 · STEEL SHADE 112 |
| B · DUB | LOOP DRIFT 114 · TRIO JAM 112 · CTI GROOVE 96 · BROKEN BEAT 94 · LATE NIGHT 90 · SLOW BURN 88 |
| C · RITE | ORGANIC 123 · FIRE CIRCLE 118 · EARTH PULSE 112 · ANDES STEP 108 · RAIN DANCE 100 |
| D · RITE | TOM RITUAL 140 (half time) · NIGHT RITUAL 90 · CHACARERA 80 |
| E · DRIFT | MALLET PHASE 96 · DAWN WATER 80 · HIGH DESERT 75 · GLASS GARDEN 72 |
| F · DRIFT | POSTCARDS 70 · CATHEDRAL 66 · SLOW LIGHT 60 |
| G · BRIDGE | SABAR DUB 122 · FOURTH WORLD 100 · RIVER DRONE 90 · MONTE CUMBIA 88 |

A kit file holds tempo, swing, the reference, how to play it, the four FX pages as values, and 16 tracks (preset, sample locks, per-kit tweaks). `./djmono check` fails on anything incomplete or out of role.

## From the Mac to the DT2

```
crates ─build─> build/drive ─sync─> +Drive folders ─load to project─> TRIAD RAM (state/slots.txt)
presets + kits ───────────────────── ./djmono load ──MIDI──> tracks ─save on the DT2─> kits
```

1. `build` and `sync` put samples on the +Drive.
2. `slots` plans which RAM slot each sample takes; you load folders into TRIAD in that order.
3. `load "KIT"` sets every track's sample and parameters over USB MIDI (tracks on channels 1–16). You set the machines first, LFO destinations after, then save the kit.
4. `browse` steps presets through one track while a pattern plays. Press `k` to write the one you like into a kit file. That's how new kits get made.

What MIDI can't reach: machines, filter machines, LFO destinations and loop BARS. The loader and the sheets list these per track.

## Growth

- **Vinyl cuts** (PCM-D100) go in `~/music production/recordings/vinyl`, named by hand. Add a `rec:` line to a crate, build, sync, `presets --seed`.
- **Field recordings** go in `recordings/field`, then into DRIFT/SCAPE or RITE/SCAPE.
- **Resamples made on the DT2** land in `/RECORDED`. Move them into a world folder on the device (hash-safe) and pull a copy back for the archive.
- **New packs** go unzipped into `audio/sample packs` on the NAS. `./djmono scan --only PACK`, add crate rules, audition, keep.
- **When a world outgrows TRIAD:** give it its own project (the world plus CORE, up to 400 MB) and keep TRIAD as the live cut.

## Maintenance

- Commit after every build, sync and slots run. `state/drive.lock` is what's on the device; `state/slots.txt` is what's in TRIAD's RAM.
- `./djmono backup` after every session on the device and before every OS update.
