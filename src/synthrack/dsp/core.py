"""DSP building blocks shared by every module.

Audio is float32 blocks shaped ``(2, n)``; voices work in mono float64 and are
vectorised with numpy so they are cheap enough for a Python audio callback.
Resonant filters and reverb come from Spotify's ``pedalboard`` (stateful,
called with ``reset=False``).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

F32 = np.float32
TWO_PI = 2.0 * math.pi


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def midi_hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


def decay_seconds(norm: float) -> float:
    """Knob position -> envelope time constant, 12 ms .. 3 s."""
    return 0.012 * 250.0 ** norm


def cutoff_hz(norm: float) -> float:
    """Knob position -> filter cutoff, 30 Hz .. 20 kHz."""
    return 30.0 * (20000.0 / 30.0) ** min(1.0, max(0.0, norm))


def pan_gains(pan: float) -> tuple[float, float]:
    """Equal-power pan, -1 .. +1; unity in the centre."""
    theta = (min(1.0, max(-1.0, pan)) + 1.0) * math.pi / 4.0
    return math.cos(theta) * math.sqrt(2.0), math.sin(theta) * math.sqrt(2.0)


def run(plugin, x: np.ndarray, sr: float, reset: bool = False) -> np.ndarray:
    """Run a pedalboard plugin on one block, keeping its internal state."""
    x = np.ascontiguousarray(x, dtype=F32)
    return plugin.process(x, sr, buffer_size=x.shape[-1], reset=reset)


def silence(n: int) -> np.ndarray:
    return np.zeros((2, n), dtype=F32)


@dataclass(frozen=True)
class Param:
    """A user-facing control. Continuous unless ``choices`` is given."""

    key: str
    label: str
    lo: float = 0.0
    hi: float = 1.0
    default: float = 0.5
    unit: str = "%"
    skew: float = 1.0  # >1 gives the low end of the range more knob travel
    choices: tuple = ()

    @property
    def is_choice(self) -> bool:
        return bool(self.choices)

    def clamp(self, value: float):
        if self.is_choice:
            return int(min(len(self.choices) - 1, max(0, round(float(value)))))
        value = float(min(self.hi, max(self.lo, float(value))))
        return float(round(value)) if self.unit in ("st", "int") else value

    def to_norm(self, value: float) -> float:
        if self.hi == self.lo:
            return 0.0
        t = (self.clamp(value) - self.lo) / (self.hi - self.lo)
        return t ** (1.0 / self.skew)

    def from_norm(self, t: float):
        t = min(1.0, max(0.0, t))
        return self.clamp(self.lo + (self.hi - self.lo) * t ** self.skew)

    def format(self, value: float) -> str:
        if self.is_choice:
            return str(self.choices[int(value)])
        if self.unit == "%":
            return f"{100 * (value - self.lo) / (self.hi - self.lo):.0f}%"
        if self.unit == "ms":
            return f"{value:.0f} ms"
        if self.unit == "s":
            return f"{value * 1000:.0f} ms" if value < 1 else f"{value:.2f} s"
        if self.unit == "Hz":
            return f"{value:.2f} Hz"
        if self.unit == "dB":
            return f"{value:+.1f} dB"
        if self.unit == "st":
            return f"{value:+.0f} st"
        if self.unit == "int":
            return f"{value:.0f}"
        if self.unit == "±":
            return f"{value:+.2f}"
        if self.unit == "cut":
            hz = cutoff_hz(value)
            return f"{hz / 1000:.1f} kHz" if hz >= 1000 else f"{hz:.0f} Hz"
        if self.unit == "env":
            return "hold" if value >= 0.98 else Param.format(_SECONDS, decay_seconds(value))
        if self.unit == "dec":
            return Param.format(_SECONDS, decay_seconds(value))
        if self.unit == "pan":
            return "C" if abs(value) < 0.02 else f"{'L' if value < 0 else 'R'}{abs(value) * 100:.0f}"
        return f"{value:.2f}"


_SECONDS = Param("_", "_", unit="s")


class Module:
    """Base class: named parameter values, jacks and a block processor."""

    TYPE = "module"
    NAME = "Module"
    TAGLINE = ""
    FINISH = "slate"
    WIDTH = 200                  # panel width in pixels
    INPUTS: tuple = ("in",)
    OUTPUTS: tuple = ("out",)
    PARAMS: tuple = ()
    REMOVABLE = True

    def __init__(self, sr: float = 48000.0):
        self.sr = float(sr)
        self.uid = ""                    # unique within a rack; set by the rack
        self.finish: str | None = None   # None -> the module's default finish
        self.values = {p.key: p.default for p in self.PARAMS}
        self._commands: deque = deque()
        self._build()

    # -- parameters ---------------------------------------------------
    @classmethod
    def param(cls, key: str) -> Param:
        for p in cls.PARAMS:
            if p.key == key:
                return p
        raise KeyError(f"{cls.NAME} has no parameter '{key}'")

    def set(self, key: str, value: float) -> None:
        self.values[key] = self.param(key).clamp(value)

    def get(self, key: str) -> float:
        return self.values[key]

    # -- commands: UI thread -> audio thread ---------------------------
    def command(self, *cmd) -> None:
        self._commands.append(cmd)

    def _drain(self):
        while True:
            try:
                yield self._commands.popleft()
            except IndexError:
                return

    # -- lifecycle ----------------------------------------------------
    def _build(self) -> None:
        """(Re)create all DSP state for the current sample rate."""

    def set_sample_rate(self, sr: float) -> None:
        if float(sr) != self.sr:
            self.sr = float(sr)
            self._build()

    def process(self, ins: dict, clock) -> dict:
        """``ins`` maps input jack -> block or None. Returns output jack -> block."""
        return {}

    # -- persistence --------------------------------------------------
    def state(self) -> dict:
        """Extra, module-specific state for the rack file."""
        return {}

    def load_state(self, data: dict) -> None:
        pass

    def to_dict(self) -> dict:
        return {"type": self.TYPE, "id": self.uid, "finish": self.finish,
                "params": dict(self.values), **self.state()}

    def load_dict(self, data: dict) -> None:
        self.finish = data.get("finish")
        for key, value in (data.get("params") or {}).items():
            try:
                self.set(key, value)
            except (KeyError, TypeError, ValueError):
                pass  # unknown or malformed values in old files are ignored
        try:
            self.load_state(data)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            pass

    def save_assets(self, folder: Path) -> None:
        """Write audio that belongs to this module (tape) under ``folder``."""

    def load_assets(self, folder: Path) -> None:
        pass


class Ramp:
    """Linear per-block smoothing for gains, so knob moves don't zipper."""

    def __init__(self, value: float | None = None):
        self.value = value  # None: snap to the first target instead of ramping

    def block(self, target: float, n: int):
        target = float(target)
        if self.value is None or abs(target - self.value) < 1e-7:
            self.value = target
            return F32(target)
        out = np.linspace(self.value, target, n + 1, dtype=F32)[1:]
        self.value = target
        return out


class Phasor:
    """Phase accumulator; returns per-sample phase in cycles."""

    def __init__(self, sr: float, phase: float = 0.0):
        self.sr = sr
        self.phase = phase

    def block(self, rate_hz, n: int) -> np.ndarray:
        """``rate_hz`` is a scalar or an ``(n,)`` array."""
        if np.ndim(rate_hz):
            inc = np.cumsum(rate_hz) / self.sr
            out = self.phase + inc - rate_hz / self.sr
            self.phase = float((self.phase + inc[-1]) % 1.0)
            return out
        inc = rate_hz / self.sr
        out = self.phase + inc * np.arange(n)
        self.phase = (self.phase + inc * n) % 1.0
        return out

    def sine(self, rate_hz: float, n: int, offset: float = 0.0) -> np.ndarray:
        return np.sin(TWO_PI * (self.block(rate_hz, n) + offset))


# -- band-limited oscillators ---------------------------------------------
def polyblep(t: np.ndarray, dt) -> np.ndarray:
    a = t / dt
    b = (t - 1.0) / dt
    return np.where(t < dt, a + a - a * a - 1.0, np.where(t > 1.0 - dt, b * b + b + b + 1.0, 0.0))


def saw(phase: np.ndarray, dt) -> np.ndarray:
    """Band-limited sawtooth. ``phase`` in cycles (any range), ``dt`` = freq / sr."""
    t = phase % 1.0
    return 2.0 * t - 1.0 - polyblep(t, dt)


def pulse(phase: np.ndarray, dt, width: float = 0.5) -> np.ndarray:
    return saw(phase, dt) - saw(phase + width, dt)


class ADSR:
    """Envelope generator rendered a block at a time."""

    def __init__(self, sr: float):
        self.sr = sr
        self.level = 0.0
        self.stage = 0   # 0 idle, 1 attack, 2 decay/sustain, 3 release

    @property
    def active(self) -> bool:
        return self.stage != 0

    def gate(self, on: bool) -> None:
        if on:
            self.stage = 1
        elif self.stage:
            self.stage = 3

    def render(self, n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
        out = np.zeros(n)
        i = 0
        while i < n and self.stage:
            m = n - i
            if self.stage == 1:
                step = 1.0 / (max(a, 0.0005) * self.sr)
                k = min(m, max(1, int(math.ceil((1.0 - self.level) / step))))
                out[i:i + k] = np.minimum(1.0, self.level + step * np.arange(1, k + 1))
                self.level = float(out[i + k - 1])
                if self.level >= 1.0 - 1e-9:
                    self.stage = 2
                i += k
            elif self.stage == 2:
                seg = s + (self.level - s) * np.exp(-np.arange(1, m + 1) / (max(d, 0.002) * self.sr))
                out[i:] = seg
                self.level = float(seg[-1])
                i = n
            else:
                seg = self.level * np.exp(-np.arange(1, m + 1) / (max(r, 0.003) * self.sr))
                out[i:] = seg
                self.level = float(seg[-1])
                if self.level < 1e-4:
                    self.level, self.stage = 0.0, 0
                i = n
        return out


class DelayLine:
    """Circular buffer with fractional (linear-interpolated) reads."""

    def __init__(self, max_samples: int, channels: int = 2):
        size = 1 << int(math.ceil(math.log2(max_samples + 8)))
        self.buf = np.zeros((channels, size), dtype=F32)
        self.mask = size - 1
        self.max_delay = size - 4
        self.w = 0
        self._ch = np.arange(channels)[:, None]

    def clear(self) -> None:
        self.buf[:] = 0.0

    def write(self, x: np.ndarray) -> None:
        n = x.shape[1]
        idx = (self.w + np.arange(n)) & self.mask
        self.buf[:, idx] = x
        self.w = (self.w + n) & self.mask

    def read(self, delay, n: int, ahead: bool = False) -> np.ndarray:
        """Read ``n`` samples ``delay`` samples in the past.

        ``delay`` is a scalar, an ``(n,)`` array or a ``(channels, n)`` array.
        With ``ahead=False`` the current block has already been written; with
        ``ahead=True`` it is about to be (feedback loops), so ``delay`` must
        stay greater than ``n``.
        """
        base = self.w + np.arange(n) - (0 if ahead else n)
        pos = base - np.asarray(delay, dtype=np.float64)
        i0 = np.floor(pos).astype(np.int64)
        frac = (pos - i0).astype(F32)
        if pos.ndim == 1:
            a = self.buf[:, i0 & self.mask]
            b = self.buf[:, (i0 + 1) & self.mask]
        else:
            a = self.buf[self._ch, i0 & self.mask]
            b = self.buf[self._ch, (i0 + 1) & self.mask]
        return a + (b - a) * frac


class Echo:
    """Feedback delay whose repeats are filtered. Returns only the wet signal.

    Delay-time changes glide like a tape machine changing speed instead of
    clicking, and delays shorter than the block are processed in chunks so the
    result does not depend on buffer size.
    """

    def __init__(self, sr: float, max_seconds: float = 3.2):
        from pedalboard import LowpassFilter

        self.sr = sr
        self.line = DelayLine(int(sr * max_seconds))
        self.lp = LowpassFilter(cutoff_frequency_hz=5000)
        self.d: float | None = None

    def process(self, x, delay_s, feedback, damp_hz=None, pingpong=False) -> np.ndarray:
        n = x.shape[1]
        target = min(self.line.max_delay - 64.0, max(96.0, delay_s * self.sr))
        if self.d is None:
            self.d = target
        step = min(0.5 * n, max(-0.5 * n, target - self.d))
        d = self.d + step * np.arange(1, n + 1) / n
        self.d += step
        limit = max(16, int(d.min()) - 2)
        pieces = -(-n // limit)
        size = -(-n // pieces)
        if damp_hz:
            self.lp.cutoff_frequency_hz = float(damp_hz)
        out = np.empty((2, n), dtype=F32)
        for s in range(0, n, size):
            e = min(n, s + size)
            rd = self.line.read(d[s:e], e - s, ahead=True)
            out[:, s:e] = rd
            fb = run(self.lp, rd, self.sr) if damp_hz else rd
            if pingpong:
                fb = fb[::-1]
            self.line.write(x[:, s:e] + fb * feedback)
        return out
