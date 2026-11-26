# Synth Rack — Spec

A portable synth / drum-machine studio for the laptop: a painted rack of modules you patch
together with cables, play from the computer keyboard, and run alongside (or into) the
sibling `pedalboard-effects` app. This is the living spec: section 1–7 describe what is built
(v0.1), section 8 is the backlog. Update it when behaviour changes.

## 1. Goals

- Make sounds and loops on the road with nothing but the laptop: no guitar, no hardware.
- Try the Elektron workflow (step trigs, parameter locks, per-track machines) on two boxes that
  share a clock, and an OP-1-style "play it, tape it" workflow next to them.
- Everything is a module in a rack. Modules are mixed, matched and patched; more get added over time.
- Same interaction feel as the pedalboard (custom-painted hardware, knobs you drag, no image
  assets) but a cleaner look: see *Look* below.
- Same audio I/O model as the pedalboard: pick devices, input channel, sample rate, buffer;
  power button, meters, soft-clipped output.
- Import your own samples.

Non-goals for now: being a DAW, plugin hosting, emulating any specific product's sound or panel.
The modules are original designs that borrow workflows, not clones.

## 2. The rack

- The window is: transport bar (top), rack (middle, scrolls), module shelf (bottom).
- Modules are full-height panels of different widths that flow left to right and wrap into rows.
  Drag a panel to reorder; drag it off the rack (or right-click) to remove. Order is visual only.
- **Signal flow is the cables.** Every module has jacks. Drag from one jack to another to patch.
  Outputs fan out to any number of inputs; several cables into one input are summed. Drag a
  cable's end off an input to unplug it; right-click a jack to clear it. Loops are refused.
- Only what reaches **MAIN OUT** is heard. MAIN OUT is always on the rack.
- A **rack** (modules, every knob, patterns, cables, skin, tempo) saves as JSON in `racks/`,
  versioned with the repo. Factory racks are built in and never overwritten. The session
  (last rack state, audio settings) lives in `~/.synth-rack/`.

### Look

Clean, simple, modern, in the spirit of Elektron and Teenage Engineering hardware. The rules,
which new modules must follow (they live in `ui/theme.py` and `ui/widgets.py`):

- Flat matte panels: no gloss, bevels, gradients or drop shadows. Five finishes only: carbon and
  slate (dark), fog, paper and sand (light). Instruments get their own tone; utility modules are slate.
- One accent colour per module, used sparingly (source knobs, lit steps, the selected track).
  Red means record or a parameter lock, everywhere. The only other colour on a panel is Wander's
  four coloured encoders.
- One encoder design at every size: flat cap, thin pointer, thin value arc. No tick marks.
- Small, letter-spaced, medium-weight captions; screens are white on black with the accent for titles.
- Explanatory text goes in tooltips and the README, not on the panel.
- Cables are thin and muted. The Cables button (or `C`) cycles full / dim / hidden; starting to
  patch brings them back.
- Cases: graphite (default), walnut, aluminum.

### Transport (shared clock)

One transport for the whole rack: play/stop, tempo 40–220 BPM, swing. All sequenced modules
follow it, sample-accurately, which is how the boxes "chain". Pattern changes on a groovebox
are queued to the end of its pattern, and boxes with *Link patterns* on change together.

### Keyboard

Space = play/stop (starts the engine if it is off). `[` `]` = select previous/next module.
`C` = show / dim / hide cables.
The selected module gets the rest of the keys:

| Module | Keys |
|---|---|
| Knockbox / Forge | `1`–`8` trigger + select track · piano keys `A W S E D F T G Y H U J K O L P` play the selected track chromatically · `Z` `X` octave · `R` live-record · `←` `→` step page · `Esc` leave step edit |
| Wander | piano keys play · `Z` `X` octave |
| Reel | `1`–`4` select track · `R` record |

## 3. Modules (v0.1)

| Name | What | Jacks |
|---|---|---|
| **Knockbox** | 8-track sample drum machine (Digitakt-style workflow) | in, out, send |
| **Forge** | 8-track drum + synth machine (Syntakt-style workflow) | in, out, send |
| **Wander** | 6-voice keyboard synth with six engines and an arp (OP-1-style) | out |
| **Reel** | 4-track tape loop synced to the transport | in, out |
| **Afterglow** | tempo-synced echo into reverb | in, out |
| **Summit** | 4-channel mixer with pan and mutes | in 1–4, out |
| **Pedal Loop** | runs a saved board from `../pedalboard-effects` inside the rack | in, out |
| **Line In** | the audio interface input (guitar, mic, the real Digitakt) | out |
| **Main Out** | to the audio device; scope and meters | in |

### Knockbox and Forge (shared groovebox core)

- 8 mono tracks, each: source → filter (LP24/LP12/HP/BP, resonance, envelope) → drive → crush →
  level/pan, plus a send level to the module's **send** jack (patch it to Afterglow).
- 8 patterns per box (A1–A8), 16–64 steps in four pages. A trig has note, velocity, length,
  probability and **parameter locks**: right-click (or shift-click) a step to hold it, then any
  sound knob you turn is locked for that step only. Double-click a knob to drop its lock.
- Live record (`R`): what you play is quantised into the pattern.
- Pads: REC, MUTE (selected track), DICE (random pattern for the track), CLEAR (track; shift = pattern).
- The kit (track sounds) belongs to the module; patterns hold trigs and locks.
- Audio at the **in** jack is mixed to the output, so boxes can be daisy-chained.

**Knockbox** tracks play samples: tune, start, length, attack, decay. LOAD imports an audio
file for the selected track (or drop a file on the module); SMPL records the **in** jack into
the track. Imported files are copied to `samples/` and are then in every Knockbox's sound list
next to the synthesised factory library.

**Forge** tracks are synthesised by a machine: Kick, Snare, Hat, Clap, Tom, FM, Bass, Lead,
Chord, Noise. Each machine has tune, decay and three macro knobs whose meaning it names.
RAND rolls a new sound for the track; INIT resets it.

### Wander

Engines: Stack (detuned saws), Pulse (PWM), FM, Pluck, Organ, Sample (any library sample played
chromatically). Two macro knobs per engine, ADSR, resonant filter with envelope, LFO to
pitch/filter/colour, chorus, arp (up/down/up-down/random/as-played, 1/8–1/16, hold). On-panel
keyboard; the screen is a live scope.

### Reel

Four stereo tracks over a loop of 1/2/4/8 bars. REC records the **in** jack onto the selected
track while the transport runs (overdubs add). Speed: 1×, ½×, 2×, reverse. The tape remembers the
tempo it was recorded at and follows the transport like tape: change tempo and pitch moves with
it. BOUNCE writes the loop to `recordings/`. Tape audio is saved with the session and with racks.

### Recording

The ● button in the transport bar records MAIN OUT to `recordings/take-YYYYMMDD-HHMMSS.wav`.

## 4. Working with the pedalboard

- **Inside the rack:** add *Pedal Loop*, pick one of your boards, patch through it. Read-only:
  it loads the factory boards and `../pedalboard-effects/boards/*.json`, never writes there.
  (`SYNTHRACK_PEDALBOARD` overrides the path. Tuner and looper pedals are skipped.)
- **Into the pedalboard app:** set this app's output to BlackHole and the pedalboard's Live Input
  to BlackHole.
- **In parallel:** run both apps on the same output device.
- **Guitar/pedalboard into the rack:** add *Line In* and patch it (opens the input device).

The exact interface Pedal Loop relies on is written down on the pedalboard side, in
`../pedalboard-effects/SPEC.md` section 4. New pedals added there show up here with no changes.
When that interface changes, update `dsp/utility.py` (`PedalLoop`, `available_boards`) and
`ui/theme.PEDAL_FINISHES` here; `test_pedal_loop_runs_a_saved_pedalboard` catches a break.

## 5. Architecture

Python 3.12, PyQt6, numpy, Spotify `pedalboard` (filters, reverb, file I/O), sounddevice. No scipy.

```
src/main.py                 launcher
src/synthrack/dsp/          modules + DSP; must not import Qt
    core.py                 Param, Module, Ramp, DelayLine, Echo, ADSR, oscillators
    transport.py            Transport -> per-block Clock (step events with sample offsets)
    library.py              sample library: synthesised factory sounds + imported files
    machines.py             Forge's synth machines
    groovebox.py            Step/Pattern/Track, GrooveBox, Knockbox, Forge
    wander.py  reel.py  utility.py
src/synthrack/engine.py     audio stream, patch graph, master recorder
src/synthrack/racks.py      factory racks, user racks, session
src/synthrack/ui/           theme, widgets, module widgets, rack view, main window
```

- Blocks are float32 `(2, n)`. `Module.process(ins, clock) -> {jack: block}`. No per-sample
  Python loops; voices are vectorised and closed-form in time since trigger wherever possible.
- The engine holds an immutable **plan** (modules in dependency order + their input cables),
  rebuilt and swapped whenever modules or cables change.
- Thread safety by convention, as in the pedalboard: the UI writes plain values and replaces
  whole objects (a step, the plan); anything stateful goes through a module's `command()` queue
  and is applied at the top of the next block.
- Sequencing is sample-accurate: the transport reports each 16th's sample offset in the block and
  tracks split the block there, so output does not depend on buffer size.
- Resonant filters are `pedalboard.LadderFilter`. It smooths cutoff over 50 ms, so voices reset
  it on trigger to get the envelope's attack; decays then trail by a few tens of ms.
- Default buffer is 256 (Python audio callback; idle tracks cost nothing). Measured on the
  factory rack with everything playing and a knob moving at 60 Hz: about 1 ms per 5.8 ms block,
  no dropouts. At 128 it mostly holds but an occasional block is late.
- The two grooveboxes are 700 px wide so both fit side by side in a 1440 px window; a row of
  modules is 1400 px.

### Adding a module

1. Subclass `Module` in `dsp/` (TYPE, NAME, TAGLINE, FINISH, WIDTH, INPUTS, OUTPUTS, PARAMS,
   `_build`, `process`). Add it to `MODULE_CLASSES` in `dsp/__init__.py`.
2. If the generic knob-grid face is not enough, subclass `ModuleWidget` and register it in
   `ui/modules.py`.

## 6. Rack file format

```json
{"version": 1, "name": "First Light", "skin": "graphite", "bpm": 104, "swing": 0.14,
 "modules": [{"type": "forge", "id": "forge-1", "finish": null, "params": {}, "...": "module state"}],
 "cables": [["forge-1", "out", "summit-1", "in1"]]}
```

Unknown module types, jacks and params are skipped on load; values are clamped.

## 7. Testing

`pytest` (DSP offline through `engine.render`, UI under Qt offscreen) and `ruff check .`.
`python src/main.py --screenshot out.png` renders the UI without audio. Scripts set
`SYNTHRACK_HOME` to a temp dir so the real session is untouched.

## 8. Backlog (not built)

- MIDI: notes in from a controller, clock/transport out to the real Digitakt, pattern dump to it
  via the existing digitakt-midi tools.
- CV-style modulation cables (LFO / envelope / random modules), per-track LFOs.
- Per-track pattern length (polymeter), conditional trigs (1:2, fill), retrigs, micro-timing.
- Sample slicing and time-stretch for imported loops; stereo samples; reverse.
- Resample: bounce Reel or MAIN OUT straight into a Knockbox track.
- Wander "endless" step sequencer; more engines; Wander FX slot.
- More modules: scope/analyser, compressor, standalone filter, granular, drone.
- Song mode / pattern chains; undo.
- Tape and step-key polish: per-track tape waveforms in stereo, undo for the last tape take.
- Knob control from the keyboard (as on the pedalboard) and from MIDI CCs.
- Faster DSP core if Python becomes the limit (numba or a small C extension), which would also
  lift the filter-envelope limitation.
