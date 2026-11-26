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
racks/ samples/ recordings/   user data, created on demand
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
- Scripts must set `SYNTHRACK_HOME` to a temp dir so `~/.synth-rack`, `racks/` and `samples/` are
  not touched. Tests do this in `conftest.py`.
- Opening a real stream makes sound: use the "BlackHole 2ch" output in scripts. Prefer
  `QT_QPA_PLATFORM=offscreen`; a real window takes keyboard focus from whoever is at the machine.
