"""Racks (modules + cables + every setting) and session persistence."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from .dsp import REGISTRY, MainOut, module_from_dict
from .dsp.transport import BPM_MAX, BPM_MIN, SWING_MAX
from .engine import valid_cables

FORMAT_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]


def app_dir() -> Path:
    """Per-machine state (session, session tape): ``~/.synth-rack``."""
    return Path(os.environ.get("SYNTHRACK_HOME", Path.home() / ".synth-rack"))


def racks_dir() -> Path:
    """Saved racks live in ``racks/`` in the repository so they are versioned
    with the code. ``SYNTHRACK_HOME`` moves them too."""
    if "SYNTHRACK_HOME" in os.environ:
        return Path(os.environ["SYNTHRACK_HOME"]) / "racks"
    return REPO_ROOT / "racks"


def recordings_dir() -> Path:
    if "SYNTHRACK_HOME" in os.environ:
        return Path(os.environ["SYNTHRACK_HOME"]) / "recordings"
    return REPO_ROOT / "recordings"


# -- factory racks ------------------------------------------------------------
_VEL = {"X": 1.0, "x": 0.75, "o": 0.4}


def _row(text: str, note: float = 60, prob: float = 1.0) -> dict:
    """'X..x..o.' -> steps; X accent, x normal, o ghost."""
    return {str(i): [note, _VEL[ch], 1, prob, {}] for i, ch in enumerate(text) if ch in _VEL}


def _notes(*notes) -> dict:
    """(step, note[, length[, vel[, prob[, locks]]]]) tuples -> steps."""
    out = {}
    for item in notes:
        step, note, *rest = item
        length, vel, prob, locks = (list(rest) + [1, 0.8, 1.0, {}][len(rest):])[:4]
        out[str(step)] = [note, vel, length, prob, locks]
    return out


def _pattern(*rows, length: int = 16) -> dict:
    return {"length": length, "tracks": [dict(r) for r in rows]}


def _track(sound: str | None = None, **params) -> dict:
    entry: dict = {"params": params}
    if sound:
        entry["sound"] = sound
    return entry


_KNOCK_A1 = _pattern(
    _row("X......x..X....."), _row("....X.......X..."), _row("x.xox.x.x.xox.xo"),
    _row("..............x."), {}, _row(".......o.....o..", prob=0.5), {},
    _notes((2, 60, 1, 0.7), (10, 65, 1, 0.6)))
_KNOCK_A2 = _pattern(
    _row("X..x...x..X..x.."), _row("....X.......X..o"), _row("xoxoxoxoxoxoxoxo"),
    _row("......x.......x."), _row("............X..."), _row("..o....o.o...o..", prob=0.6), {},
    _notes((2, 60, 1, 0.7), (6, 60, 1, 0.5), (10, 67, 1, 0.6), (13, 65, 1, 0.5)))
_KNOCK_TRACKS = [
    _track(level=0.78), _track(send=0.22), _track(level=0.5, pan=-0.25), _track(level=0.45, pan=0.25),
    _track(send=0.35, level=0.6), _track(send=0.45, pan=0.4, level=0.55), _track(),
    _track(send=0.55, cutoff=0.66, level=0.55, decay=0.62),
]
_BASS_LINE = _notes((0, 36, 2, 0.9), (3, 36, 1, 0.7), (6, 39, 1, 0.8, 1.0, {"cutoff": 0.72}),
                    (8, 36, 2, 0.9), (11, 34, 1, 0.7), (14, 31, 2, 0.8, 1.0, {"cutoff": 0.62}))
_BELLS = _notes((0, 75, 1, 0.6, 0.8), (6, 72, 1, 0.5, 0.7), (9, 79, 1, 0.6, 0.8), (12, 74, 1, 0.5, 0.6))
_FORGE_A1 = _pattern({}, {}, {}, {}, _row("......x......o.x", note=45, prob=0.6), _BELLS, _BASS_LINE, {})
_FORGE_A2 = _pattern(
    {}, {}, _row("..x...x...x...x."), {}, _row("......x......o.x", note=45, prob=0.6), _BELLS,
    _notes((0, 36, 2, 0.9), (3, 36, 1, 0.7), (6, 39, 1, 0.8), (8, 43, 2, 0.9, 1.0, {"cutoff": 0.8}),
           (11, 41, 1, 0.7), (12, 39, 1, 0.7), (14, 34, 2, 0.8)),
    _notes((0, 72, 3, 0.6), (4, 75, 2, 0.6), (8, 79, 4, 0.6), (14, 77, 2, 0.5)))
_FORGE_TRACKS = [
    _track(), _track(send=0.2), _track(level=0.45, pan=0.3, decay=0.12), _track(send=0.3),
    _track(send=0.3, pan=-0.35, level=0.6), _track(send=0.6, level=0.5, pan=0.2),
    _track(cutoff=0.44, reso=0.42, fenv=0.42, fdec=0.3, level=0.72),
    _track(cutoff=0.62, reso=0.2, fenv=0.25, send=0.4, level=0.5),
]


def _knockbox(uid="knockbox-1", patterns=(_KNOCK_A1, _KNOCK_A2)) -> dict:
    return {"type": "knockbox", "id": uid, "params": {"volume": 0.8},
            "tracks": _KNOCK_TRACKS, "patterns": list(patterns)}


def _forge(uid="forge-1", patterns=(_FORGE_A1, _FORGE_A2)) -> dict:
    return {"type": "forge", "id": uid, "params": {"volume": 0.8},
            "tracks": _FORGE_TRACKS, "patterns": list(patterns)}


FACTORY_RACKS = [
    {"name": "First Light", "skin": "graphite", "bpm": 104, "swing": 0.14,
     "modules": [
         _knockbox(), _forge(),
         {"type": "wander", "id": "wander-1", "params": {"engine": 3, "level": 0.7}},
         {"type": "reel", "id": "reel-1", "params": {"bars": 1}},
         {"type": "afterglow", "id": "afterglow-1", "params": {"time": 2, "reverb": 0.45}},
         {"type": "summit", "id": "summit-1", "params": {"level3": 0.7, "level4": 0.7}},
         {"type": "mainout", "id": "mainout-1"},
     ],
     "cables": [
         ["knockbox-1", "out", "summit-1", "in1"], ["forge-1", "out", "summit-1", "in2"],
         ["wander-1", "out", "reel-1", "in"], ["reel-1", "out", "summit-1", "in3"],
         ["knockbox-1", "send", "afterglow-1", "in"], ["forge-1", "send", "afterglow-1", "in"],
         ["afterglow-1", "out", "summit-1", "in4"], ["summit-1", "out", "mainout-1", "in"],
     ]},
    {"name": "Drum Lab", "skin": "graphite", "bpm": 96, "swing": 0.2,
     "modules": [
         _knockbox(),
         {"type": "afterglow", "id": "afterglow-1", "params": {"dry": 1.0, "reverb": 0.18, "echo": 0.12}},
         {"type": "mainout", "id": "mainout-1"},
     ],
     "cables": [["knockbox-1", "out", "afterglow-1", "in"], ["afterglow-1", "out", "mainout-1", "in"]]},
    {"name": "Machine Room", "skin": "graphite", "bpm": 124, "swing": 0.0,
     "modules": [
         {"type": "forge", "id": "forge-1", "params": {"volume": 0.68}, "tracks": _FORGE_TRACKS,
          "patterns": [_pattern(
              _row("X...X...X...X...", note=33), _row("....X.......X...", note=54),
              _row("..x...x...x...xo"), _row("............x..."), {}, _BELLS, _BASS_LINE, {})]},
         {"type": "afterglow", "id": "afterglow-1", "params": {"time": 2}},
         {"type": "summit", "id": "summit-1"},
         {"type": "mainout", "id": "mainout-1"},
     ],
     "cables": [["forge-1", "out", "summit-1", "in1"], ["forge-1", "send", "afterglow-1", "in"],
                ["afterglow-1", "out", "summit-1", "in2"], ["summit-1", "out", "mainout-1", "in"]]},
    {"name": "Synth Sketchpad", "skin": "graphite", "bpm": 90, "swing": 0.0,
     "modules": [
         {"type": "wander", "id": "wander-1", "params": {"engine": 0, "attack": 0.02, "release": 0.8}},
         {"type": "afterglow", "id": "afterglow-1", "params": {"dry": 1.0, "reverb": 0.35, "echo": 0.3}},
         {"type": "reel", "id": "reel-1", "params": {"bars": 2}},
         {"type": "mainout", "id": "mainout-1"},
     ],
     "cables": [["wander-1", "out", "afterglow-1", "in"], ["afterglow-1", "out", "reel-1", "in"],
                ["reel-1", "out", "mainout-1", "in"]]},
    {"name": "Through the Pedalboard", "skin": "graphite", "bpm": 104, "swing": 0.1,
     "modules": [
         _forge(patterns=(_FORGE_A2,)),
         {"type": "pedalloop", "id": "pedalloop-1", "board": "Shoegaze Wash", "params": {"mix": 0.8}},
         {"type": "mainout", "id": "mainout-1"},
     ],
     "cables": [["forge-1", "out", "pedalloop-1", "in"], ["pedalloop-1", "out", "mainout-1", "in"]]},
    {"name": "Empty Rack", "skin": "graphite", "bpm": 120, "swing": 0.0,
     "modules": [{"type": "mainout", "id": "mainout-1"}], "cables": []},
]


# -- building and saving ------------------------------------------------------
def new_uid(type_name: str, taken) -> str:
    taken = set(taken)
    i = 1
    while f"{type_name}-{i}" in taken:
        i += 1
    return f"{type_name}-{i}"


def build_rack(data: dict, sr: float = 48000.0, assets: Path | None = None) -> tuple[list, list]:
    """(modules, cables) for a rack dict. Unknown module types are skipped and
    a Main Out is added if the rack has none."""
    modules = []
    for entry in data.get("modules", []):
        if entry.get("type") not in REGISTRY:
            continue
        try:
            module = module_from_dict(entry, sr)
        except (KeyError, TypeError, ValueError):
            continue
        if not module.uid or module.uid in {m.uid for m in modules}:
            module.uid = new_uid(module.TYPE, [m.uid for m in modules])
        if assets is not None and assets.is_dir():
            try:
                module.load_assets(assets)
            except Exception:
                pass
        modules.append(module)
    if not any(isinstance(m, MainOut) for m in modules):
        out = MainOut(sr)
        out.uid = new_uid("mainout", [m.uid for m in modules])
        modules.append(out)
    return modules, valid_cables(modules, data.get("cables", []))


def rack_to_dict(name: str, modules, cables, skin: str, bpm: float, swing: float) -> dict:
    return {"version": FORMAT_VERSION, "name": name, "skin": skin,
            "bpm": round(float(bpm), 1), "swing": round(float(swing), 3),
            "modules": [m.to_dict() for m in modules], "cables": [list(c) for c in cables]}


def rack_tempo(data: dict) -> tuple[float, float]:
    bpm = min(BPM_MAX, max(BPM_MIN, float(data.get("bpm", 120.0))))
    swing = min(SWING_MAX, max(0.0, float(data.get("swing", 0.0))))
    return bpm, swing


def save_assets(modules, folder: Path) -> None:
    """Write module audio (tape) into ``folder``; remove the folder if there is none."""
    folder.mkdir(parents=True, exist_ok=True)
    for module in modules:
        module.save_assets(folder)
    wanted = {m.uid for m in modules}
    for path in folder.glob("*.wav"):
        if path.stem.rsplit("-t", 1)[0] not in wanted:
            path.unlink()
    if not any(folder.iterdir()):
        folder.rmdir()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "rack"


class RackStore:
    """Factory racks plus the user's racks (``racks/*.json`` in the repo)."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else app_dir()
        self.racks_dir = self.root / "racks" if root else racks_dir()
        self.session_path = self.root / "session.json"
        self.session_assets = self.root / "session.tape"

    def _user_racks(self) -> dict:
        racks = {}
        if self.racks_dir.is_dir():
            for path in sorted(self.racks_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text())
                    racks[data["name"]] = data
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return racks

    def factory_names(self) -> list[str]:
        return [r["name"] for r in FACTORY_RACKS]

    def user_names(self) -> list[str]:
        return sorted(self._user_racks())

    def is_user(self, name: str) -> bool:
        return name in self._user_racks()

    def load(self, name: str) -> dict:
        user = self._user_racks()
        if name in user:
            return user[name]
        for rack in FACTORY_RACKS:
            if rack["name"] == name:
                return rack
        raise KeyError(name)

    def assets_dir(self, name: str) -> Path:
        return self.racks_dir / f"{_slug(name)}.tape"

    def save(self, rack: dict, modules=()) -> Path:
        self.racks_dir.mkdir(parents=True, exist_ok=True)
        path = self.racks_dir / f"{_slug(rack['name'])}.json"
        path.write_text(json.dumps(rack, indent=1))
        save_assets(modules, self.assets_dir(rack["name"]))
        return path

    def delete(self, name: str) -> bool:
        path = self.racks_dir / f"{_slug(name)}.json"
        shutil.rmtree(self.assets_dir(name), ignore_errors=True)
        if path.exists():
            path.unlink()
            return True
        return False

    def rename_sample(self, old: str, new: str) -> int:
        """Point saved racks at a renamed sample. Returns how many files changed."""
        changed = 0
        if not self.racks_dir.is_dir():
            return 0
        for path in sorted(self.racks_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            hit = False
            for module in data.get("modules", []):
                if module.get("sample") == old:
                    module["sample"], hit = new, True
                for track in module.get("tracks", []):
                    if isinstance(track, dict) and track.get("sound") == old:
                        track["sound"], hit = new, True
            if hit:
                path.write_text(json.dumps(data, indent=1))
                changed += 1
        return changed

    # session ---------------------------------------------------------
    def load_session(self) -> dict:
        try:
            return json.loads(self.session_path.read_text())
        except (OSError, ValueError):
            return {}

    def save_session(self, session: dict, modules=()) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(json.dumps(session, indent=1))
        save_assets(modules, self.session_assets)
