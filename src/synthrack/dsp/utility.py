"""The small modules: echo/reverb, mixer, pedalboard host, line in, main out."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pedalboard as pb

from .core import F32, Echo, Module, Param, Ramp, db_to_lin, pan_gains, run

ECHO_TIMES = ("1/16", "1/8", "3/16", "1/4", "3/8", "1/2")
_ECHO_STEPS = (1, 2, 3, 4, 6, 8)


class Afterglow(Module):
    TYPE = "afterglow"
    NAME = "Afterglow"
    TAGLINE = "echo + reverb"
    FINISH = "slate"
    WIDTH = 180
    PARAMS = (
        Param("feedback", "Repeats", default=0.4),
        Param("tone", "Tone", default=0.55),
        Param("echo", "Echo", default=0.45),
        Param("size", "Size", default=0.6),
        Param("damp", "Damp", default=0.5),
        Param("reverb", "Reverb", default=0.4),
        Param("dry", "Dry", default=0.0),
        Param("time", "Echo time", default=2, choices=ECHO_TIMES),
    )

    def _build(self) -> None:
        self.echo = Echo(self.sr)
        self.verb = pb.Reverb(wet_level=1.0, dry_level=0.0, width=1.0)
        self.tail = 0
        self.gains = [Ramp(), Ramp(), Ramp()]

    def process(self, ins, clock):
        n = clock.n
        x = ins.get("in")
        if x is None:
            if self.tail <= 0:
                return {}
            self.tail -= n
            x = np.zeros((2, n), dtype=F32)
        else:
            self.tail = int(self.sr * 10.0)
        p = self.values
        delay = min(3.0, _ECHO_STEPS[int(p["time"])] * clock.sps / self.sr)
        wet = self.echo.process(x, delay, 0.92 * p["feedback"], damp_hz=500.0 * 30.0 ** p["tone"],
                                pingpong=True)
        echo, reverb, dry = (g.block(v, n) for g, v in zip(self.gains, (p["echo"], p["reverb"], p["dry"])))
        self.verb.room_size = p["size"]
        self.verb.damping = p["damp"]
        hall = run(self.verb, x + wet * echo, self.sr)
        return {"out": x * dry + wet * echo + hall * reverb}


class Summit(Module):
    TYPE = "summit"
    NAME = "Summit"
    TAGLINE = "4-channel mixer"
    FINISH = "slate"
    WIDTH = 260
    CHANNELS = 4
    INPUTS = ("in1", "in2", "in3", "in4")
    PARAMS = tuple(Param(f"pan{i}", "Pan", -1.0, 1.0, 0.0, "pan") for i in range(1, 5)) \
        + tuple(Param(f"level{i}", f"Ch {i}", default=0.75) for i in range(1, 5))

    def _build(self) -> None:
        if not hasattr(self, "mute"):
            self.mute = [False] * self.CHANNELS
        self.peaks = [0.0] * self.CHANNELS
        self.gains = [(Ramp(), Ramp()) for _ in range(self.CHANNELS)]

    def process(self, ins, clock):
        n = clock.n
        out = None
        for i in range(self.CHANNELS):
            x = ins.get(f"in{i + 1}")
            if x is None:
                continue
            level = 0.0 if self.mute[i] else 1.78 * self.values[f"level{i + 1}"] ** 2
            left, right = pan_gains(self.values[f"pan{i + 1}"])
            y = np.stack([x[0] * self.gains[i][0].block(level * left, n),
                          x[1] * self.gains[i][1].block(level * right, n)])
            self.peaks[i] = max(self.peaks[i], float(np.abs(y).max()))
            out = y if out is None else out + y
        return {} if out is None else {"out": out}

    def state(self) -> dict:
        return {"mute": list(self.mute)}

    def load_state(self, data: dict) -> None:
        self.mute = [bool(m) for m in (list(data.get("mute", [])) + [False] * 4)[:4]]


# -- the pedalboard, hosted ---------------------------------------------------
def pedalboard_root() -> Path:
    """Where the sibling pedalboard checkout is expected."""
    if "SYNTHRACK_PEDALBOARD" in os.environ:
        return Path(os.environ["SYNTHRACK_PEDALBOARD"])
    beside = Path(__file__).resolve().parents[4]
    for name in ("pedalboard", "pedalboard-effects"):     # the repo's name, then its old one
        if (beside / name / "src" / "pedalfx").is_dir():
            return beside / name
    return beside / "pedalboard"


def _pedalfx():
    """The pedalboard's DSP package, or None if it is not checked out next door."""
    src = pedalboard_root() / "src"
    if not (src / "pedalfx" / "dsp").is_dir():
        return None
    if str(src) not in sys.path:
        sys.path.append(str(src))
    try:
        import pedalfx.dsp
        import pedalfx.presets
    except Exception:
        return None
    return pedalfx


def available_boards() -> dict:
    """Board name -> board dict: the pedalboard's saved boards, then its factory ones. Read-only."""
    fx = _pedalfx()
    if fx is None:
        return {}
    boards = {}
    try:
        folder = fx.presets.boards_dir()             # wherever the pedalboard keeps them
    except AttributeError:
        folder = pedalboard_root() / "boards"        # an older pedalboard: in its own repo
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                boards[data["name"]] = data
            except (OSError, ValueError, KeyError, TypeError):
                continue
    for board in fx.presets.FACTORY_BOARDS:
        boards.setdefault(board["name"], board)
    return boards


class PedalLoop(Module):
    TYPE = "pedalloop"
    NAME = "Pedal Loop"
    TAGLINE = "your pedalboard, in the rack"
    FINISH = "slate"
    WIDTH = 260
    SKIP = ("tuner", "looper")     # pedals that need the pedalboard's own UI
    PARAMS = (
        Param("mix", "Mix", default=1.0),
        Param("level", "Level", -18.0, 12.0, 0.0, "dB"),
    )

    def _build(self) -> None:
        if not hasattr(self, "board"):
            self.board = ""
            self.chain: tuple = ()
        for pedal in self.chain:
            pedal.set_sample_rate(self.sr)
        self.tail = 0
        self.gain = Ramp()
        self.mix = Ramp()
        self.error = ""

    def boards(self) -> list[str]:
        return list(available_boards())

    def load_board(self, name: str) -> bool:
        fx = _pedalfx()
        data = available_boards().get(name)
        if fx is None or data is None:
            self.error = "pedalboard repo not found" if fx is None else f"no board '{name}'"
            self.board = name
            self.chain = ()
            return False
        pedals = [p for p in fx.presets.pedals_from_board(data, self.sr) if p.TYPE not in self.SKIP]
        self.chain, self.board, self.error = tuple(pedals), name, ""
        return True

    def process(self, ins, clock):
        n = clock.n
        x = ins.get("in")
        if x is None:
            if self.tail <= 0:
                return {}
            self.tail -= n
            x = np.zeros((2, n), dtype=F32)
        else:
            self.tail = int(self.sr * 8.0)
        y = np.array(x, dtype=F32, order="C")     # pedals may work in place; x is shared
        for pedal in self.chain:
            if pedal.enabled:
                y = np.ascontiguousarray(pedal.process(y), dtype=F32)
                pedal.aux = None
        mix = self.mix.block(self.values["mix"], n)
        return {"out": (x + (y - x) * mix) * self.gain.block(db_to_lin(self.values["level"]), n)}

    def state(self) -> dict:
        return {"board": self.board,
                "pedals": [{"type": p.TYPE, "enabled": p.enabled} for p in self.chain]}

    def load_state(self, data: dict) -> None:
        if data.get("board"):
            self.load_board(data["board"])
            for pedal, saved in zip(self.chain, data.get("pedals", [])):
                if saved.get("type") == pedal.TYPE:
                    pedal.enabled = bool(saved.get("enabled", True))


class LineIn(Module):
    TYPE = "linein"
    NAME = "Line In"
    TAGLINE = "audio input"
    FINISH = "slate"
    WIDTH = 100
    INPUTS = ()
    PARAMS = (Param("gain", "Gain", -24.0, 24.0, 0.0, "dB"),)

    def _build(self) -> None:
        self.feed = None       # the engine puts the hardware input block here
        self.peak = 0.0
        self.gain = Ramp()

    def process(self, ins, clock):
        if self.feed is None:
            return {}
        y = self.feed * self.gain.block(db_to_lin(self.values["gain"]), clock.n)
        self.peak = max(self.peak, float(np.abs(y).max()))
        return {"out": y}


class MainOut(Module):
    TYPE = "mainout"
    NAME = "Main Out"
    TAGLINE = "to the speakers"
    FINISH = "carbon"
    WIDTH = 100
    OUTPUTS = ()
    REMOVABLE = False

    def _build(self) -> None:
        self.mix = None        # what arrived this block; the engine picks it up
        self.scope = np.zeros(8, dtype=F32)
        self.peaks = [0.0, 0.0]

    def process(self, ins, clock):
        self.mix = ins.get("in")
        return {}
