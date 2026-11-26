# Playing samples in pitch

Any sample can be played at different pitches. The built-in tonal sounds (Bass Pluck, Stab Minor,
Bell, Keys, Vox Ah, Sub Drop) are all tuned to C, so they stay in key with each other. Stab Minor
is itself a C minor 7 chord: play it five semitones up and you get F minor 7.

Pitch is changed by playing the sample faster or slower, as on a hardware sampler, so high notes
are shorter and low notes longer.

## 1. Play it from the keys

On Knockbox, click the track's pad (pad 8 is Stab Minor), then play `A W S E D F T G Y H U J K`.
`A` is the sample's own pitch; the rest go up like a piano. `Z` / `X` shift an octave.

Press `R` while the pattern is playing and what you play is recorded into it.

## 2. Set the pitch of one step

To make the stab play C minor on beat 1 and F minor on beat 3:

1. Click pad **8**.
2. Left-click step keys **1** and **9** so both are lit.
3. Right-click step **9**. It gets a red outline.
4. Turn the small **NOTE** knob up five semitones (C4 to F4).
5. Right-click step 9 again, or press `Esc`.

## 3. Tune the whole track

TUNE moves everything on the track by up to two octaves either way. Useful for dropping a kick,
or putting a sample in the key of a song.

## 4. Play chords with it on Wander

Wander can use any sample as its sound, and it plays several notes at once:

1. Click Wander, set ENGINE to **Sample**.
2. Choose the sample in the SAMPLE window (click its middle for the full list).
3. Play chords on the keys. Wander's envelope (ATTACK … RELEASE), filter and chorus all apply.

Try *Vox Ah* with a slow ATTACK for a choir pad, or one of your own recordings.

## Using your own sounds

- Knockbox **LOAD**, or drag an audio file onto Knockbox: the file is copied into `samples/` and
  appears in every sound list, including Wander's.
- Knockbox **SMPL** records whatever is patched into its IN jack onto the selected track.
- Right-click a Knockbox or Wander to rename or delete the sample it is using.
