# Synth Rack

A portable synth and drum-machine studio for the laptop: a rack of modules you patch with cables,
play from the computer keyboard, and run next to (or through) the
[pedalboard](../pedalboard). No instruments or hardware needed.

![The rack](docs/screenshot.png)

`SPEC.md` is the working spec: what is built, how it fits together, and the backlog.
[`tutorials/`](tutorials/) has short walk-throughs.

## Run it

```
git clone git@github.com:feamster/synth-rack.git && cd synth-rack
./install.sh
synth-rack                              # --play starts the music straight away
```

`install.sh` builds the virtualenv and links the launcher into `~/.local/bin`, so `synth-rack`
works from any terminal. It is safe to run again, and all the link amounts to is
`ln -sf "$(pwd)/bin/synth-rack" ~/.local/bin/synth-rack`. To run without installing:
`.venv/bin/python src/main.py`.

The window opens and the terminal prompt comes straight back; anything the app prints goes to
`~/.synth-rack/last-run.log`. `synth-rack --fg` keeps it attached to the terminal instead.

Press **Space**. The factory rack *First Light* plays a groove on both drum machines. Click
anywhere on Wander (its name gets an underline: that module now has the keyboard) and play over
it on `A W S E D F T G Y H U J K`; `Z` / `X` change octave. The same keys play whichever
module you clicked last: on a drum machine they play the selected track chromatically.

## The modules

| | |
|---|---|
| **Knockbox** | 8-track sample drum machine. 30 built-in sounds; LOAD or drop a file to import your own; SMPL records whatever is patched into its IN jack. |
| **Forge** | 8-track drum + synth machine: Kick, Snare, Hat, Clap, Tom, FM, Bass, Lead, Chord, Noise. RAND rolls a new sound. |
| **Wander** | 6-voice keyboard synth: Stack, Pulse, FM, Pluck, Organ, Sample engines, arp, hold. |
| **Reel** | 4-track tape loop (1–8 bars) that records its IN jack in time with the transport. |
| **Afterglow** | Tempo-synced echo into reverb. Patch the SEND jacks here. |
| **Summit** | 4-channel mixer. |
| **Pedal Loop** | Runs one of your saved pedalboard boards inside the rack. |
| **Line In** | Your audio interface input (guitar, mic, the hardware Digitakt). |
| **Main Out** | What you hear. |

### Working the grooveboxes

- Click a step key to place a trig for the selected track. Track pads (or `1`–`8`) select and audition.
- **Parameter locks:** right-click (or shift-click) a step to hold it; it gets a red outline. Any
  sound knob you turn now applies to that step only, and NOTE / VEL / LEN / PROB edit that trig.
  Double-click a knob to drop its lock. Right-click the step again (or `Esc`) to let go.
- `R` or REC: live record. What you play on the pads or piano keys is quantised into the pattern.
- DICE rolls a pattern for the track; CLEAR clears it (Shift: the whole pattern).
- PATTERN changes wait for the end of the bar while playing, and both boxes follow each other
  (right-click a box → *Link Pattern Changes* to turn that off).
- Up to 64 steps in four pages: set STEPS, then use the small page lamps or `←` `→`.

### Patching

Drag from any jack to another. Outputs have a filled label. One output can feed many inputs and
an input sums everything plugged into it. Drag a cable's end off an input to unplug it, or
right-click a jack. Press `C` to dim or hide the cables when they are in the way.

### Saving and recording

- **Save** stores the rack (modules, knobs, patterns, cables, tape) in `racks/`.
- **●** in the top bar records the main output to a `take-….wav`; Reel's BOUNCE writes the tape
  loop the same way. Recordings do not go in this folder: by default they go to
  `~/Dropbox/Synth Rack` (or `~/Music/Synth Rack` on a machine without Dropbox). To change that,
  right-click ● → *Choose Recordings Folder…*, or use **Settings…**. The choice is remembered per
  machine.
- Imported samples are copied to `samples/` in this folder, and every Knockbox and Wander sees
  them. You can also drop audio files there yourself. To **rename or delete** one, right-click
  the Knockbox or Wander that is using it: *Rename Sample…*, *Delete Sample…* (moves the file to
  the Trash) and *Show Samples Folder*. Renames are followed through into your saved racks. The
  30 built-in sounds are synthesised, so they can't be renamed or deleted.

### Keeping samples and racks somewhere else too

The project's own `samples/` and `racks/` folders are always used, so a fresh clone works by
itself. **Settings…** lets you add more folders for each (a Dropbox folder, a sample collection)
and choose which folder new ones are saved in:

- Everything in the listed folders shows up together in the sound lists and the RACK menu.
- Things are found by name, in the order listed, and the project's folder comes first, so a rack
  that names a sample finds it wherever it lives.
- *Save new ones in* decides where LOAD, SMPL and Save As write. A rack you loaded from another
  folder is saved back where it came from.
- Only the top level of each folder is read (no subfolders yet).

These choices are per machine (`~/.synth-rack/settings.json`).

## With the pedalboard

- **Inside the rack:** add *Pedal Loop*, choose a board, patch through it. It reads
  `../pedalboard/boards` and never writes there.
- **Into the pedalboard app:** Settings… → output to *BlackHole 2ch*, then choose BlackHole as the
  pedalboard's Live Input.
- **Guitar into the rack:** add *Line In* and patch it. Settings… sets the input device and channel.

## License

Apache 2.0, see `LICENSE`.

## Develop

```
.venv/bin/python -m pytest && .venv/bin/ruff check .
```
