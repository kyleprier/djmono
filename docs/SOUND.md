# Sound: getting each world to feel right on the DT2

The recipes in `presets/recipes.txt` hold these settings as numbers. This is the why, plus what can't be dialled in: sequencing, trig conditions, playing.

## Everywhere: the analogue haze

- **Filter:** Multi-Mode (the default filter machine). The TYPE knob morphs low-pass to band-pass to high-pass. Pull cutoff down until the top end sounds like a record.
- **Wow and flutter:** a slow random LFO on TUNE, a few cents deep (`lfo2=rnd/16/x4/+2>tune` in the stab and keys recipes).
- **Grit:** a little SRR (1–4) and bit reduction. SRR after a resonant filter sweep gives vowel tones.
- **Resample, then re-pitch** for real aliasing.
- **Tape print:** DT2 out → Tascam 424, recorded hot → back into the DT2 input. Sample in mono, move the result from `/RECORDED` into a world folder.
- **Noise bed:** track 15 runs a noise loop quietly under everything.

## Loops: SL and LP

Every drums bank ends with two loop ranges, named so you can't miss them.

- **SL (slots 193–224): slice grid.** The loop sits on the Grid machine, cut into 16 slices a bar (the loader works out the bar count from the loop's tempo and length). Put a trig on each step and p-lock SLIC, or use the Slice TRIG mode in step recording (OS 1.15) to play slices from the trig keys. Because every slice is triggered on the grid, the loop plays in time at any tempo, and you can re-order it, drop hits, or swing it with the pattern. Set the machine to GRID before loading.
- **LP (slots 225–256): whole loop.** The loop sits on the Stretch machine and follows the tempo. One trig at the start of the bar, trig length to the end. Set BARS to the loop's length. The field loops in bank D use Werp instead.
- **Both from one loop:** most Skins loops are in both ranges. Use LP to hear the groove, SL to play it.
- **Slice machine** (not Grid) is there for breaks that don't sit on a grid: transient detection, then CREATE RANDOM LOCKS.

## DUB

**Chord stab (track 10)**, after Attack Magazine's Basic Channel breakdown:

- `stab-dub`: low-pass around 40, some resonance, envelope +25 with a short decay, short hold so the stab is clipped. Delay 75, reverb 30. Slow sine LFO on cutoff.
- `stab-bp` (the `BP` presets): bit-crushed, then band-passed near 450 Hz, with a slow LFO moving the band. Dotted-1/8 delay, short reverb.
- To build a chord from single notes: tune three tracks to root, third and seventh, then resample.

**Delay.** TIME 24 is a dotted 1/8, 12 a dotted 1/16, 32 a quarter. Feedback 60–80. Raise the delay's high-pass and lower its low-pass so repeats darken. Send the delay into the reverb.

**Throws.** P-lock the delay send up on single stabs. Feedback can't be locked per trig: push it by hand, then snap back with temporary save and reload ([FUNC]+[YES] saves, [FUNC]+[NO] reloads).

**Groove.** Chords on the off-beat with A:B and probability so they breathe. The ride carries the time, the rim sits a hair late, the kick is round and low.

**Ghost voice (ONE DROP DUB).** Rhythm & Sound shadow a singer with a quieter, recessed copy of themselves. Put the same vocal on track 12 (`VOX THROW`) and 14 (`VOX GHOST`: band-passed, quieter, all reverb).

## RITE

- **Polymeter:** in PER TRACK mode each track gets its own length and speed. Shaker at 12 steps with 3/4 speed for triplets against the 16s. Bells at 5 or 7.
- **3 against 2 (CHACARERA):** bombo on a 12-step track against a 16-step low tom.
- **Euclidean mode** gives two pulse generators with rotation. Hold [FUNC] while turning it off to keep the trigs as normal steps you can micro-time.
- **Strokes on one track:** sample-lock open, slap and muted hits of the same drum (the kit files list the lock folders). Velocity does the rest.
- **One hit, three tracks (TOM RITUAL):** Shackleton chops a single hit across channels with different tone, reverb and pitch. `TAMA`, `TAMA DEEP` (-5, darker, more room) and `TAMA ROOM` are the same drum.
- **Organic house (ORGANIC 123):** 122–125 BPM, 60–65% swing, a 16th shaker with a velocity lock on every step, the clap micro-timed a few ticks early.
- **Room:** short reverb on the hand drums, little delay. Save the space for the drone and the field bed.

## DRIFT

- **Long samples:** Werp on field recordings (reverse-loop segments turn them into pads); Stretch keeps long beds in tempo; loop play mode sustains drones.
- **Generative:** odd track lengths (13, 15, 17), probability at 20–50% on bells, a slow random LFO on sample start.
- **Phasing (MALLET PHASE):** the same figure on two tracks, one 12 steps long, one 13.
- **Barely there (POSTCARDS):** trig conditions 1:4, 3:7 and 50% so notes come back unevenly, and the whole kit at conversation volume.
- **Tone:** key tracking on the filter keeps high bells bright and low ones soft.
- **Space:** long reverb, delay as texture rather than rhythm.

## Guitar and pedal steel

Track 12 in STEEL SHADE, LATE NIGHT, HIGH DESERT, CATHEDRAL and RIVER DRONE. The samples stay dry; the space comes from the DT2.

- **Reverb guitar (`gtr-verb`, the `GTR` presets):** chorus 45, delay 50, reverb 70, a triangle LFO on volume for tremolo.
- **Pedal steel swell (`steel-swell`, the `STEEL` presets):** long attack and hold so each note blooms like a volume pedal, a sine LFO on tune for the steel's vibrato, a slow one on pan. Play long overlapping notes, micro-timed a step early so the swell lands on the beat. P-lock TUNE on the next step for a bend.
- **Print it** through the 424 with the reverb up, then resample. A washed-out print makes a better scape than any raw sample.

## Transitions and live

- **Consistent tracks:** 13–16 are the soundscape in every kit, so the bed and the throws carry through a pattern change.
- **Half-time pivots:** 126 dub techno sits over a 63 one-drop feel (ONE DROP DUB); 140 half time (TOM RITUAL) is 70, next to POSTCARDS.
- **3:2 pivot:** a dotted quarter at 120 is 80, the CHACARERA and El Buho tempo.
- **Beatless bridge (RIVER DRONE):** no kick. Change the tempo while only 13–15 play.
- **BRIDGE kits** borrow from two worlds: SABAR DUB is dub techno with RITE drums on 5–7, FOURTH WORLD is RITE drums with DUB horns and DRIFT air.
- **Sync:** no Ableton Link. By ear (hold [LEFT]/[RIGHT] to nudge), a DJM mixer's MIDI clock, or a Link-to-MIDI bridge from rekordbox.
- **Dub the records:** DJ mixer into the DT2's inputs; the EXTERNAL MIXER page sends the record into the DT2's delay and reverb.
- **Performance:** Perform Kit ([FUNC]+[PRESET/KIT]) keeps tweaks across pattern changes. STOP twice cuts delay tails.

## What the kits are built on

Tempos marked *algo* come from BPM-detection sites and can be off by a factor of two.

| Kit | After | Sources |
|-----|-------|---------|
| DEEP ECHO, CHORD DUST | Basic Channel: crushed stab, band-pass near 450 Hz, slow LFO, dotted-1/8 delay; parts added and taken away on the faders | [Attack: Basic Channel style](https://www.attackmagazine.com/technique/beat-dissected/basic-channel-style-dub-techno/) · [Attack: dub techno chords](https://www.attackmagazine.com/technique/synth-secrets/dub-techno-synth-chords/) · [Quietus](https://thequietus.com/interviews/strange-world-of/the-strange-and-frightening-world-of-basic-channel/) |
| ONE DROP DUB | Rhythm & Sound: deep bass loops, insistent hats, singers with recessed versions of themselves; 122–126 *algo* | [The Wire](https://teletype.in/@alxpsr/rhythmnsoundwire) · [SongBPM](https://songbpm.com/@rhythm-sound) |
| TRIO JAM | Moritz von Oswald Trio: ride and hi-hat, dry clap, reverb snare, Rhodes; recorded from the first note | [LWE](http://www.littlewhiteearbuds.com/feature/lwe-interviews-moritz-von-oswald/) · [RA](https://ra.co/reviews/6316) |
| FIELD ECHO | Deepchord / Echospace: field recordings and drones first, beats and bass last; dirty tape echo | [FACT](https://www.factmag.com/2015/11/25/deepchord-ultraviolet-music-stream-interview/) · [Textura](https://www.textura.org/archives/interviews/tenquestions_deepchord_soultek.htm) |
| LOOP DRIFT | Jan Jelinek: jazz fragments looped unsynchronised; odd track lengths approximate it | [Inverted Audio](https://inverted-audio.com/feature/jan-jelinek-on-loop-finding-jazz-records/) · [MusicRadar](https://www.musicradar.com/news/10-ways-to-get-more-out-of-elektron-digitakt-1) |
| ORGANIC 123 | Organic house: 122–125 BPM, 60–65% swing, velocity-varied 16th shaker, early clap | [Attack: organic house](https://www.attackmagazine.com/technique/beat-dissected/organic-house/) |
| ANDES STEP | Nicola Cruz: bombo, flutes, charango; loops at 90–124 through a Space Echo | [Metal](https://metalmagazine.eu/en/post/nicola-cruz-mystic-sounds-from-the-andes-arnau-salvado) · [Bandcamp](https://nicolacruz.bandcamp.com/album/pandemic-percussion-2020-loops-and-samples) |
| MONTE CUMBIA | El Buho, Chancha Via Circuito: 80–95 BPM, birdsong, guiro, charango, stones as percussion | [Metal](https://metalmagazine.eu/en/post/el-buho-cumbia-andean-sounds-and-beats) · [Remezcla](https://remezcla.com/features/music/chancha-via-circuito-profile/) · [Bandcamp Daily](https://daily.bandcamp.com/features/future-folkloric) |
| CHACARERA | Chacarera: bombo alternating 6/8 and 3/4 | [Wikipedia](https://en.wikipedia.org/wiki/Chacarera) |
| TOM RITUAL | Shackleton: 140 at half time, triplet toms, one hit across channels | [Textura](https://www.textura.org/archives/interviews/shackleton_interview.htm) · [LWE](http://www.littlewhiteearbuds.com/review/shackleton-three-eps/) |
| MALLET PHASE | Midori Takada: marimba, cowbell, gongs, bells, reed organ, blown bottles | [Vinyl Factory](https://www.thevinylfactory.com/features/through-the-looking-glass-midori-takada-interview) · [RBMA](https://daily.redbullmusicacademy.com/2018/07/midori-takada-interview/) |
| POSTCARDS | Hiroshi Yoshimura: keyboard and Rhodes at home; *Green* with rain and birds | [Wikipedia](https://en.wikipedia.org/wiki/Music_for_Nine_Post_Cards) · [Quietus](https://thequietus.com/quietus-reviews/reissue-of-the-week/hiroshi-yoshimura-surround-reissue-review/) |
| FOURTH WORLD | Jon Hassell: hand drums, looped trumpet, harmonizer fifths, night creatures | [Furious](https://www.furious.com/perfect/hassell.html) · [Ableton](https://www.ableton.com/en/blog/jon-hassell-possible-musics/) · [Wikipedia](https://en.wikipedia.org/wiki/Fourth_World,_Vol._1:_Possible_Musics) |
| SABAR DUB | Mark Ernestus' Ndagga Rhythm Force: sabar drummers, mixed dubwise | [In Sheep's Clothing](https://insheepsclothinghifi.com/mark-ernestus-dubwise-rhythm-sound-architect/) · [Cafe OTO](https://www.cafeoto.co.uk/events/mark-ernestus-ndagga-rhythm-force-25/) |
| RIVER DRONE | Beatless bridges: Acid Pauli's kickless set, Deepchord's drone layer | [DHA](https://www.deephouseamsterdam.com/interview-acid-pauli/) · [FACT](https://www.factmag.com/2015/11/25/deepchord-ultraviolet-music-stream-interview/) |

The older kits (CHORD ROOM, STEEL SHADE, SLOW BURN, LATE NIGHT, BROKEN BEAT, CTI GROOVE, FIRE CIRCLE, EARTH PULSE, RAIN DANCE, NIGHT RITUAL, DAWN WATER, HIGH DESERT, GLASS GARDEN, CATHEDRAL, SLOW LIGHT) are genre sketches rather than one artist's method.
