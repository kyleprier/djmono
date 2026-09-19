# Crates

Each file is one folder on the Digitakt II's +Drive:

    crates/DUB/CHRD.txt   ->   /DUB/CHRD/

Worlds: `CORE` `DUB` `RITE` `DRIFT`. Functions (the file name) are fixed so every world reads the same on the device:

| Group  | Functions | Profile |
|--------|-----------|---------|
| Rhythm | `KICK` `SNR` `HAT` `HAND` `SHKR` `WOOD` | hit: mono, trimmed, 4 s max |
| Ring   | `BELL` `FX` | ring: stereo, 15 s max, long fade |
| Tone   | `BASS` `KEYS` `CHRD` `HORN` `TONE` `VOX` | tone: stereo, 8 s max |
| Air    | `PAD` `DRONE` `FIELD` `NOISE` | bed: stereo, 40 s max, -3 dB |
| Time   | `LOOP` `CHAIN` | loop: stereo, untrimmed, 5 min max |

Everything is rendered to 16-bit / 48 kHz WAV, peak-normalised, named `<code>_<fn>_<desc>` (32 characters max).

## Line format

    source:path/or/glob            | options

- `source` is a key from `config/paths.local` (`sfm`, `lib`, `rec`).
- Matching ignores case, and treats `_`, `-` and spaces the same. `*` matches across folders.
- Paths are matched from the top of the source (`sfm:JUNOS FROM MARS/...`), so the copies inside Essential WAV From Mars stay out.
- A path with no `*` is an exact pick (what `./djmono audition` writes).
- Skipped automatically: DAW/sampler format folders (Ableton, Kontakt, MPC, Apple Loops...), Synology `@eaDir`/`#recycle`, and SFM `Kits` folders (copies of the individual hits) unless the rule mentions "kit".
- Rules read `index/lib.tsv`, not the NAS, so `ls` is instant and works anywhere. Rescan after adding packs.

| Option | Does |
|--------|------|
| `limit=8` | keep 8 matches, spread evenly across the list (`pick=first` for the first 8) |
| `* c3*.wav` | the usual way to take one note from a multisampled patch; the DT2 plays it chromatically |
| `prefer=clean` | if any match sits in a folder with that word, keep only those. Default is `color` (SFM splits clean and color takes by folder); `prefer=any` keeps both |
| `exclude=bass,pad` | drop matches containing these |
| `code=luft` | name prefix when the pack isn't in `config/codes.txt` |
| `name=my-name` | exact name (single-file lines) |
| `keepname` | keep the file's own name (default for `rec:`) |
| `mono` `stereo` `len=12` `fade=80` `norm=-3` `trim` `notrim` | override the profile |
| `raw` | copy bytes untouched (files already 16/48 from the DT2) |

## Seeds vs picks

The seeded rules are broad on purpose. The loop that turns them into a library:

1. `./djmono ls DUB/CHRD -v`: see what a rule pulls.
2. `./djmono audition DUB/CHRD`: listen; `k` keeps. Picks are appended as exact lines.
3. Delete the broad rule once the picks cover it. Exact lines never drift when a pack changes.
