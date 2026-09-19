# The djmono framework

How the Digitakt II is organised for three styles, and why. Approved design: [djmono: Digitakt II setup design](https://claude.ai/code/artifact/e181c733-8ad6-4ed6-8b80-b66d0f764c17).

| World | Style | Pattern banks | Tempo home |
|-------|-------|---------------|-----------|
| **DUB** | Dub techno on jazz and soul: chord stabs, Rhodes, horns, reverb guitar, rides, tape | A (dub techno), B (jazz and soul) | 112–122, 88–96 |
| **RITE** | Tribal / shamanic: hand drums, shakers, bells, marimba, flute, drones | C (driving), D (slow, 6/8) | 110–120, 90–100 |
| **DRIFT** | Ambient / new age: field recordings, bells, glass, pads, guitar and pedal steel swells | E (pulse), F (beatless) | 60–80 |
| **CORE** | What two or more worlds share: machine drums, noise beds, FX | n/a | n/a |

## The decisions

1. **One project, TRIAD, holds all three worlds.** A pattern carries its own kit (16 sounds plus send FX and mix), so changing worlds is a pattern change. Loading a project stops playback; changing patterns doesn't.
2. **The whole library fits in TRIAD.** The limit is 400 MB and 1016 slots per project. Budgets: CORE 30 MB, DUB 110 MB, RITE 90 MB, DRIFT 150 MB, plus 20 MB for resampling. `build` and `check` enforce them. Beds are cut to 20 s.
3. **Every kit has the same 16-track shape.** The same mutes work in every world.
4. **Presets are the instruments.** Each world has its own bank, and a slot range means the same role in every bank.
5. **The library stays on the NAS; git holds the choices; the DT2 gets a rendered subset.**
6. **Samples are immutable once they're on the device.** The DT2 finds samples by content hash. Moving or renaming on the device is safe; changing audio or deleting breaks presets. djmono never overwrites or deletes on the device.
7. **Shared means CORE.** A kit uses its own world plus CORE, so a world can later move to its own project intact.
8. **Haze is played, not baked in.** Samples render clean. The analogue feel comes from each kit's filters, overdrive, SRR, LFO wow and send FX, plus prints through the Tascam 424.

## The kit shape

| Trk | Role | Preset slots | +Drive folders it draws on |
|----:|------|--------------|----------------------------|
| 1 | Low | 001–064 | KICK |
| 2 | Snap | 001–064 | SNR, HAND (slaps), WOOD |
| 3 | Hat | 001–064 | HAT, SHKR |
| 4 | Metal | 001–064 | HAT (rides), BELL |
| 5–6 | Hand A, Hand B | 001–064 | HAND |
| 7 | Wood / shake | 001–064 | WOOD, SHKR |
| 8 | Loop | 001–064 | LOOP (Slice), SCAPE (Werp) |
| 9 | Bass | 065–096 | BASS |
| 10 | Stab | 097–144 | STAB |
| 11 | Keys | 145–176 | KEYS |
| 12 | Lead: horns, strings, guitar, pedal steel | 177–208 | HORN, GTR, VOX |
| 13 | Pad | 209–232 | PAD |
| 14 | Scape | 233–244 | SCAPE |
| 15 | Noise | 245–248 | NOISE |
| 16 | FX | 249–256 | FX |

Tracks 13–16 plus the kit's delay and reverb are each world's analog soundscape. Options come from **sample locks**: a kit spec lists the folders each track can step through, and they're all in RAM. **Preset locks** swap whole presets per step from the project's 128-preset pool.

## The +Drive

```
/CORE    KICK SNR HAT HAND SHKR NOISE FX
/DUB     KICK SNR HAT LOOP · BASS STAB KEYS HORN GTR VOX · PAD SCAPE
/RITE    KICK HAND SHKR WOOD BELL LOOP · BASS STAB HORN VOX · SCAPE
/DRIFT   WOOD BELL · BASS KEYS HORN GTR VOX · PAD SCAPE
/FACTORY /INCOMING /RECORDED     (the DT2's own; djmono never touches them)
```

Names are `<code>_<fn>_<desc>`: `mirg_keys_e-piano-c3`, `pres_hand_udu-tone-01`, `trt_kick_roomy`. The function is in the name because a project's sample list shows names without folders.

## Presets, kits, projects

| Layer | In git | On the DT2 |
|-------|--------|-----------|
| Preset banks | `presets/A-CORE.txt` … `D-DRIFT.txt`: slot, name, recipe, tags, sample | Built by hand from `./djmono sheet`, saved to the slot |
| Recipes | `presets/recipes.txt`: machine and starting settings per sound type | n/a |
| Kits | `kits/<WORLD>/<KIT>.txt`: pattern bank, tempo, kit FX, 16 tracks, sample locks | Assembled from presets, saved as kits |
| Projects | `projects/TRIAD.txt`: folders to load, kits per pattern bank | Built once, backed up with Transfer |

| Bank | Presets |
|------|---------|
| A | CORE |
| B | DUB |
| C | RITE |
| D | DRIFT |
| E | Live-tuned variants |
| F | Built from your own recordings |
| G | Third-party (DigiSphere II) |
| H | Scratch |

- **Names:** role, then character, 15 characters max: `STAB DUB M9`, `UDU TONE`.
- **Tags:** one function tag plus one character tag from the DT2's fixed 32. `Favourite` marks keepers.
- **Keeping it honest:** `./djmono check` fails if a kit is missing a track, a preset sits outside its role's slot range, a sample doesn't exist, or a project won't fit in RAM.
- **Capturing sounds:** hold a trig and press [PRESET/KIT] to save that sound, p-locks included, as a new preset. Then write it into the bank file so git knows.

## Growth

- **Vinyl cuts** (PCM-D100) go in `~/music production/recordings/vinyl`, named by hand (`trt_keys_rhodes-vamp`). Add a `rec:` line in the right crate, a preset in bank F, then build and sync.
- **Field recordings** go in `recordings/field`, then into DRIFT/SCAPE or RITE/SCAPE.
- **Resamples made on the DT2** land in `/RECORDED`. Move them into a world folder on the device (hash-safe) and pull a copy back for the archive. Don't re-render them.
- **New packs** go unzipped into `audio/sample packs` on the NAS. Run `./djmono scan`, add rules, then audition and keep.
- **When a world outgrows TRIAD:** give it a LAB project (the world plus CORE, up to 400 MB) and keep TRIAD as the live cut.

## Maintenance

- Commit after every build, sync and preset session. `state/drive.lock` is the record of what's on the device.
- `./djmono backup` after every session on the device and before every OS update. It files Transfer backups (`.dt2prj`, `.dt2pst`) under `backups/` and copies them to the NAS.
