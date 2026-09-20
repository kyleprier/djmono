# Digitakt II: facts that shape the design

Checked September 2026 against OS 1.16. Sources are at the bottom; ⚠ means community-measured, not an Elektron spec.

## Limits

| | |
|---|---|
| +Drive | 20 GB user samples (factory content doesn't count) · 128 projects · 1024 kits · 2048 presets (8 banks × 256) |
| Per project | 400 MB sample RAM · 1016 sample slots · 128 patterns (8 × 16) · 16 songs · 128-preset pool |
| Tracks | 16 (audio or MIDI), up to 128 steps |
| Sample format | Stored 16-bit / 48 kHz, mono or stereo. Transfer converts anything else (and resamples 44.1k). |
| On-device sampling | 66 s max |
| Largest file via Transfer | ⚠ about 59 MB (about 5 min stereo) |
| Transfer speed | ⚠ about 0.5 MB/s over USB-MIDI, roughly 30–35 min per GB. The sequencer stops while files move. |

## Behaviour that matters

- **Samples are found by content hash**, not by path or name.
  - Moving or renaming on the device is safe.
  - Deleting removes the sample from every preset and pattern.
  - Editing a WAV and sending it back makes a *different* sample.
- **Loading a preset or kit makes a copy** inside the pattern. Editing the loaded copy leaves the saved one untouched.
- **Only presets in a project's pool can be preset-locked.** PURGE ALL and SELECT UNUSED clear out unused presets and samples.
- **The sample browser can:** create folders, rename, move, multi-select, LOAD TO PROJECT, LOAD TO TRK, and preview about 10 s. Samples have no tags and no search; presets and kits do.
- **Naming characters** on the device are A–Z, 0–9, space and `~ ! @ # $ % ^ & ( ) _ + - =`. Sample names stay inside that set and under 32 characters; preset and kit names under 12 (the preset file's name field is 12 bytes). Keep names upper case: OS 1.10 dropped names with lower case.
- **Preset tags** are fixed: Kick, Snare, Rimshot, Clap, Tom, Percussion, Hi-Hat, Cymbal, Cowbell, Synth, Bass, Lead, Pad, Texture, Chord, Sound Fx, Electronic, Metallic, Acoustic, Atmosphere, Noisy, Glitch, Hard, Soft, Dark, Bright, Vintage, Epic, Fail, Loop, Mine, Favourite.
- **There is no USB disk mode.** Everything goes through Transfer, Elektroid or Overbridge.

## Machines

| Machine | Use |
|---------|-----|
| Oneshot | Hits, chord stabs |
| Werp | Cuts a sample into segments; reverse-loop segments for pads |
| Stretch | Tempo-follows long material (grains) |
| Repitch | Classic pitched sampler playback |
| Slice (1.15+) | Slice editor with transient detection. SLICE=NOTE plays slices chromatically; CREATE RANDOM LOCKS gives instant variations. Slice points are saved in the preset, not the WAV. |
| Grid | Equal slices (4, 8, 16, 32 or 64). The SL presets use it: 16 slices a bar, played on the grid |

## MIDI (what `./djmono load` relies on)

- **Every sound parameter has a CC or NRPN.** Tracks listen on their own channel (TRACK 1–16 in MIDI CONFIG > CHANNELS). The numbers come from the MIDI implementation on midi.guide; the OS 1.01 manual's appendix has a few wrong entries (it gives sample slot as CC 9, which is portamento).
- **Sample select:** CC 24 picks the RAM bank, CC 19 the slot, then the DT2 needs about 100 ms before the next message. The NRPN versions scale oddly; the CCs work.
- **Tune** goes as NRPN 1:0, 128 steps a semitone around 8192. That's the one 14-bit parameter the loader sends that way.
- **Not reachable over MIDI:** the machine, the filter machine, Werp/Stretch BARS, and saving (no command for "save this kit"). Set them by hand; the loader and sheets list them.
- **LFO destination** (CC 105/115/28 for LFO 1/2/3) has no documented value list, but the DT2 sends the CC when you turn the DEST knob with ENCODER DEST = INT + EXT. `./djmono learn` reads those values once into `config/lfo-dest.txt`, after which the loader sets destinations too.
- **Kit FX** (delay, reverb, chorus, compressor) listen on the FX CONTROL channel, and their CCs overlap the track CCs. With all 16 tracks on channels 1–16 there's no free channel, so `load --fx` asks you to swap track 16 off for a moment.
- **LOAD TO PROJECT** puts samples into the first empty slots, or into a chosen RAM bank with FUNC + YES. The +Drive browser shows the slot of every loaded sample, which is how `./djmono load --test` checks the plan.
- **Preset files (.dt2pst)** are a zip: manifest, the WAV, and a compressed binary. The binary looks like an LZ4 block with the header as its dictionary. chirashi writes slice points straight into that compressed stream, so its presets are unlikely to load. Writing real preset files would take a round of exported presets to map parameter offsets; the MIDI loader does the same job today.

## OS timeline

| OS | Added |
|----|-------|
| 1.10 | Comb+ filter; overdrive/SRR before or after the filter; key tracking; mono sampling; load a sample straight to a track; track swap; overdub; load a kit to all empty patterns |
| 1.15 | Slice machine; a filesystem check on first boot (back up first) |
| 1.16 | Current. Outbox 8 support, MIDI fix |

## Tools

- **Transfer 1.10.4:** drag and drop (folders and zips keep their tree). EXPLORE page for backup and restore. Projects are `.dt2prj`, presets `.dt2pst`; both carry their user samples.
- **Overbridge 2.26:** all 16 tracks in stereo, plus FX returns and the external input, into a DAW. Sample slot assignment and a tag-filtered preset browser in the plugin.
- **Elektroid 3.4 (optional):** scriptable sample upload that djmono uses for `sync`.
  - It's not in Homebrew. Build it CLI-only:
    ```
    brew install automake libtool pkg-config libsndfile libsamplerate gettext zlib json-glib libzip rtmidi rtaudio rubberband
    git clone https://github.com/dagargo/elektroid && cd elektroid
    autoreconf --install && ./configure BUILD_GUI=no && make && sudo make install
    elektroid-cli ld          # the Digitakt II should be listed
    ```
  - Quit Transfer first, because it holds the MIDI port.
  - Not tested on this Mac yet. If the build fights you, `./djmono sync --transfer` does the same job by hand.
- **DigiChain** (browser) builds sample chains padded to the DT2's slice grid.

## Sources

- Digitakt II manual, OS 1.16: https://www.elektron.se/wp-content/uploads/2026/09/Digitakt-2-User-Manual_ENG_OS1.16_260909.pdf
- MIDI CC and NRPN map: https://midi.guide/d/elektron/digitakt-ii/ · https://github.com/pencilresearch/midi
- Sample select over MIDI: https://www.elektronauts.com/t/controlling-sample-slot-on-digitakt-2-via-midi/222058
- OS release notes: https://www.elektron.se/release-notes/digitakt-ii-os-release-notes
- Transfer manual: https://www.elektron.se/wp-content/uploads/2026/03/Transfer-User-Manual_ENG_OS1.10_260304.pdf
- Overbridge manual: https://www.elektron.se/wp-content/uploads/2026/08/Overbridge-User-Manual_260826.pdf
- Elektroid: https://github.com/dagargo/elektroid · CLI: https://dagargo.github.io/elektroid/cli/
- ⚠ File size ceiling: https://www.elektronauts.com/t/digitakt-2-max-file-size-for-transferring/239503
- ⚠ Transfer speed: https://www.elektronauts.com/t/os-update-digitakt-ii-1-02-transfer/216059
- DigiChain: https://github.com/brian3kb/digichain
