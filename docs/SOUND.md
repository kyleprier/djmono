# Sound: getting each world to feel right on the DT2

These are starting points. Parameter values are approximate on the 0–127 scale. Save anything good as a preset in that world's bank.

## Everywhere: the analogue haze

- **Filter:** Lowpass 4 or the Legacy filter. Pull the cutoff down until the top end sounds like a record.
- **Wow and flutter:** LFO2 with a random wave, slewed, slow, and a few cents of depth on TUNE.
- **Grit:** a little SRR (1–4) and bit reduction.
  - On OS 1.10+, SRR after a resonant filter sweep gives vowel tones.
  - A random LFO on SRR or bit reduction keeps it moving.
- **Resample, then re-pitch** for real aliasing.
- **Tape print:** DT2 out → Tascam 424, recorded hot and pitched a touch → back into the DT2 input. Sample it in mono to save RAM, then move the result from `/RECORDED` into a world folder.
- **Noise bed:** track 15 plays a CORE/NOISE loop (crackle or hiss) quietly under everything.

## DUB

**Chord preset (track 10).**

- **Source:** Oneshot machine with a CHRD sample (minor 7/9/11).
- **Filter:** Lowpass 4, cutoff about 40, a little resonance, envelope depth +25, short decay.
- **Amp:** short hold, so the stab is clipped.
- **Sends:** delay 70+, reverb 30.
- **Movement:** LFO1 as a slow sine on cutoff, small depth.
- **To build a chord from single notes:** tune three tracks to root, third and seventh, then resample the mix.

**Delay (pattern FX).**

- **Time:** 12 is a dotted 1/16, 24 a dotted 1/8.
- **Feedback:** 60–80.
- **Tone:** raise the delay's high-pass and lower its low-pass, so repeats darken as they fade.
- **Routing:** send the delay into the reverb.

**Throws.**

- P-lock the delay send on single stabs.
- Delay feedback can't be locked per trig. For runaway echoes, push it by hand, then snap back with temporary save and reload ([FUNC]+[YES] saves, [FUNC]+[NO] reloads).
- For sequenced FX, use the FX CONTROL MIDI channel from a controller.

**Groove.**

- Chords on the offbeat, using A:B and probability conditions so they breathe.
- The ride carries the time, the rim is soft, and the kick is round and low.
- Micro-time the rim a hair late.

## RITE

- **Polymeter:** in PER TRACK mode each track gets its own length and speed.
  - Shaker at 12 steps with 3/4 speed for the triplet feel against the 16s.
  - Bells at 5 or 7 steps.
- **Euclidean mode** gives two pulse generators with rotation. To edit by hand, hold [FUNC] while turning it off; the pattern becomes normal trigs you can micro-time.
- **Strokes on one track:** sample-lock open, slap and muted hits of the same drum. Velocity does the rest.
- **Call and response:** PRE and NEI conditions between the conga and djembe tracks.
- **Loops:** use the Slice machine with transient detection, then CREATE RANDOM LOCKS for instant variations.
- **Room:** a short reverb on the hand drums and very little delay. Save the space for the drone and the field bed.
- **True 5-against-4** needs micro-timing workarounds. Polymeter lengths are the easy win.

## DRIFT

- **Long samples:**
  - Werp on field recordings; reverse-loop segments turn them into pads.
  - Stretch keeps long beds in tempo.
  - Loop play mode sustains drones.
- **Generative:**
  - Odd track lengths (13, 15, 16, 17) with pattern RESET at INF.
  - Probability at 20–50% on bells and chimes.
  - A slow random LFO on sample start.
- **LFO chains:** LFO2 and LFO3 can modulate LFO1. The fixed-120 speed setting gives drift that ignores tempo.
- **Tone:** key tracking (1.10+) on the filter keeps high bells bright and low ones soft.
- **Space:** long reverb, and delay as texture rather than rhythm.

## Live: DJ plus DT2

- **Sync:** the DT2 has no Ableton Link. Your options:
  - **By ear:** hold [LEFT] or [RIGHT] on the main screen to nudge tempo; the manual suggests this for turntables.
  - **Mixer clock:** DJM mixers send MIDI clock from BPM detection.
  - **rekordbox:** it only speaks Link, so bridge Link to MIDI clock (Link to MIDI app or Ableton).
  - **CDJs:** Beat Link Trigger turns Pro DJ Link into clock.
- **Dub the records:** run the DJ mixer into the DT2's inputs. The EXTERNAL MIXER page sends the record into the DT2's delay and reverb, so your chord throws and the vinyl share one echo.
- **Transitions:** keep bridge patterns in bank G that carry the outgoing world's bed and the incoming world's pulse. Put cue notes in pattern names.
- **Performance controls:** Perform Kit ([FUNC]+[PRESET/KIT]) keeps tweaks across pattern changes. Page loop (hold [PAGE]) and pattern volume keep levels steady.
- **Stopping:** press STOP twice to cut delay tails.
