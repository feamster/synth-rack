# synth-rack Development Guidelines

A patchable rack of drum machines, synths and tape: PyQt6 UI (custom painted) over a numpy +
Spotify-pedalboard DSP graph. Sibling of `../pedalboard`, whose conventions it follows.
**`SPEC.md` is the living spec: read it first and update it when behaviour changes.**

## Technologies
- Python 3.12, PyQt6, pedalboard (Spotify), sounddevice, numpy. No scipy.

## Project Structure
```
src/main.py              launcher
src/synthrack/dsp/       modules + DSP; must not import Qt
src/synthrack/engine.py  audio stream, patch graph, master recorder
src/synthrack/racks.py   factory racks, user racks, session
src/synthrack/ui/        theme, widgets, module faceplates, rack view, main window
tests/                   pytest (pythonpath = src)
ui/sound_browser.py      packs / sounds / search dialog
tutorials/               walk-throughs; update them when the UI they describe changes
```

## Commands
```
.venv/bin/python -m pytest && .venv/bin/ruff check .
.venv/bin/python src/main.py
QT_QPA_PLATFORM=offscreen .venv/bin/python src/main.py --screenshot out.png   # render without a window
```

## Conventions
- Audio blocks are float32 `(2, n)`; `Module.process(ins, clock) -> {jack: block}`. Never modify an
  input block in place: one output block is shared by every cable leaving that jack.
- No per-sample Python loops. Voices are vectorised; split blocks at event offsets for timing.
- The UI thread writes plain values and replaces whole objects (a `Step`, a step list, the plan).
  Anything stateful goes through `module.command(...)`.
- A new module = a `Module` subclass + an entry in `MODULE_CLASSES` (+ a `ModuleWidget` subclass
  in `ui/modules.py` if the generic face is not enough). Parametrised tests pick it up.
- Look: follow the rules under *Look* in SPEC.md. Flat, neutral finishes, one accent, no gloss.
- Nothing the user makes lives in this repo. Racks are in the sibling **`../gear-presets`** repo
  (`synth-rack/`; read its README, it also holds the pedalboard's boards and is how the Pedal
  Loop finds them); samples, takes and tape are under `~/Dropbox/Synth Rack/`. SPEC.md "Where
  things live" is the reference. Never add audio or user racks here.
- Saving a rack commits it in `gear-presets` automatically (local only). Don't push that repo
  unless asked.
- Scripts must set `SYNTHRACK_HOME` to a temp dir so `~/.synth-rack`, the presets repo and the
  Dropbox folders are not touched. Tests do this in `conftest.py`.
- Opening a real stream makes sound: use the "BlackHole 2ch" output in scripts. Prefer
  `QT_QPA_PLATFORM=offscreen`; a real window takes keyboard focus from whoever is at the machine.
