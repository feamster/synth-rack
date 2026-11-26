"""Forge's synth machines: one monophonic voice per track.

Every machine reads the same five source parameters - tune, decay and three
macros (colour, shape, sweep) whose meaning it names in ``LABELS``. Drum
machines are closed-form in time since the trigger; melodic ones keep phase
accumulators so the pitch can move while a note sounds.
"""

from __future__ import annotations

import numpy as np

from .core import TWO_PI, decay_seconds, midi_hz, pulse, saw
from .library import band

_tables: dict = {}


def noise_tables(sr: float) -> dict:
    """Looping noise colours, so voices need no filters of their own."""
    key = int(sr)
    if key not in _tables:
        rng = np.random.default_rng(77)
        n = int(sr * 1.5)
        white = rng.standard_normal(n)
        t = np.arange(n) / sr
        metal = sum(np.sign(np.sin(TWO_PI * f * t)) for f in (263.0, 400.0, 421.0, 474.0, 587.0, 845.0))

        def norm(x):
            return (x / np.abs(x).max()).astype(np.float64)

        _tables[key] = {
            "white": norm(white),
            "mid": norm(band(white, sr, 400, 9000)),
            "bright": norm(band(white, sr, 6000, 16000)),
            "air": norm(band(white, sr, 10000, 20000)),
            "metal": norm(band(metal, sr, 3500, 16000)),
        }
    return _tables[key]


class Machine:
    NAME = "Machine"
    LABELS = ("Color", "Shape", "Sweep")
    MELODIC = False
    NOTE = 60          # the note a plain trig plays
    DEFAULTS: dict = {}

    def __init__(self, sr: float):
        self.sr = float(sr)
        self.noise = noise_tables(sr)
        self.active = False
        self.t = 0            # samples since the trigger
        self.p: dict = {}
        self.vel = 1.0
        self.note = 60.0
        self.hold = 0.0       # seconds the note is held before it decays
        self.seed = 0
        self.phase = np.zeros(4)

    def trigger(self, note: float, vel: float, p: dict, hold: float = 0.0) -> None:
        self.p = p
        self.note = float(note)
        self.vel = float(vel)
        self.hold = hold if self.MELODIC else 0.0
        self.t = 0
        self.seed = (self.seed * 7919 + 104729) % 50021
        self.phase = np.zeros(4)
        self.active = True

    # -- helpers ------------------------------------------------------
    def _time(self, n: int) -> np.ndarray:
        t = (self.t + np.arange(n)) / self.sr
        self.t += n
        return t

    def _amp(self, t: np.ndarray, scale: float = 1.0) -> np.ndarray:
        tau = decay_seconds(self.p["decay"]) * scale
        env = np.minimum(1.0, t * 1000.0) * np.exp(-np.maximum(t - self.hold, 0.0) / tau)
        if env[-1] < 1e-3:
            self.active = False
        return env * self.vel

    def _noise(self, name: str, n: int, rate: float = 1.0) -> np.ndarray:
        table = self.noise[name]
        idx = (self.seed * 31 + ((self.t - n + np.arange(n)) * rate).astype(np.int64)) % len(table)
        return table[idx]

    def _freq(self) -> float:
        return midi_hz(self.note + self.p["tune"])

    def _phase(self, k: int, freq, n: int) -> np.ndarray:
        """Advance oscillator ``k``; ``freq`` is a scalar or per-sample array."""
        if np.ndim(freq):
            inc = np.cumsum(freq) / self.sr
            out = self.phase[k] + inc - freq / self.sr
            self.phase[k] = (self.phase[k] + inc[-1]) % 1.0
            return out
        inc = freq / self.sr
        out = self.phase[k] + inc * np.arange(n)
        self.phase[k] = (self.phase[k] + inc * n) % 1.0
        return out

    def render(self, n: int) -> np.ndarray:
        raise NotImplementedError


def _swept_phase(t, f0, depth, rate):
    """Cycles of a sine whose pitch falls from f0*(1+depth) to f0 at ``rate``/s."""
    return f0 * t + f0 * depth * (1.0 - np.exp(-t * rate)) / rate


class Kick(Machine):
    NAME = "Kick"
    LABELS = ("Click", "Punch", "Sweep")
    NOTE = 33
    DEFAULTS = {"tune": 0, "decay": 0.58, "color": 0.3, "shape": 0.25, "sweep": 0.5}

    def render(self, n):
        p = self.p
        t = self._time(n)
        y = np.sin(TWO_PI * _swept_phase(t, self._freq(), 9.0 * p["sweep"], 42.0))
        g = 1.0 + 7.0 * p["shape"]
        y = np.tanh(y * g) / np.tanh(g)
        if p["color"] > 0.01:
            y = y + self._noise("mid", n) * np.exp(-t * 420.0) * p["color"] * 0.8
        return y * self._amp(t)


class Snare(Machine):
    NAME = "Snare"
    LABELS = ("Noise", "Bright", "Bend")
    NOTE = 54
    DEFAULTS = {"tune": 0, "decay": 0.42, "color": 0.6, "shape": 0.4, "sweep": 0.3}

    def render(self, n):
        p = self.p
        t = self._time(n)
        f = self._freq()
        ph = _swept_phase(t, f, 1.2 * p["sweep"], 70.0)
        tone = np.sin(TWO_PI * ph) + 0.5 * np.sin(TWO_PI * 1.62 * ph)
        noise = self._noise("mid", n) * (1.0 - p["shape"]) + self._noise("bright", n) * p["shape"] * 1.4
        amp = self._amp(t)
        body = tone * (1.0 - p["color"]) * np.exp(-t * 18.0) * self.vel
        return (body + noise * p["color"] * 1.3 * amp) * 0.8


class Hat(Machine):
    NAME = "Hat"
    LABELS = ("Metal", "Air", "Snap")
    NOTE = 60
    DEFAULTS = {"tune": 0, "decay": 0.2, "color": 0.5, "shape": 0.3, "sweep": 0.4}

    def render(self, n):
        p = self.p
        t = self._time(n)
        rate = 2.0 ** ((self.note - 60 + p["tune"]) / 12.0)
        y = self._noise("metal", n, rate) * p["color"] + self._noise("bright", n, rate) * (1.0 - p["color"])
        y = y * (1.0 - 0.7 * p["shape"]) + self._noise("air", n) * 1.6 * p["shape"]
        amp = self._amp(t)
        return y * (amp + p["sweep"] * np.exp(-t * 900.0) * self.vel) * 0.5


class Clap(Machine):
    NAME = "Clap"
    LABELS = ("Bright", "Spread", "Room")
    NOTE = 60
    DEFAULTS = {"tune": 0, "decay": 0.4, "color": 0.35, "shape": 0.4, "sweep": 0.5}

    def render(self, n):
        p = self.p
        t = self._time(n)
        rate = 2.0 ** ((self.note - 60 + p["tune"]) / 12.0)
        y = self._noise("mid", n, rate) * (1.0 - p["color"]) \
            + self._noise("bright", n, rate) * p["color"] * 1.5
        gap = 0.006 + 0.016 * p["shape"]
        bursts = sum(np.where(t >= d, np.exp(-(t - d) * 260.0), 0.0) for d in (0.0, gap, 2 * gap))
        tail = np.where(t >= 2 * gap, 1.0, 0.0) * self._amp(t) * p["sweep"]
        return y * (bursts * self.vel * 0.6 + tail)


class Tom(Machine):
    NAME = "Tom"
    LABELS = ("Skin", "Growl", "Bend")
    NOTE = 45
    DEFAULTS = {"tune": 0, "decay": 0.5, "color": 0.15, "shape": 0.2, "sweep": 0.35}

    def render(self, n):
        p = self.p
        t = self._time(n)
        ph = TWO_PI * _swept_phase(t, self._freq(), 2.0 * p["sweep"], 28.0)
        y = np.sin(ph + 2.5 * p["shape"] * np.sin(ph))
        if p["color"] > 0.01:
            y = y + self._noise("mid", n) * np.exp(-t * 90.0) * p["color"]
        return y * self._amp(t) * 0.9


class FM(Machine):
    NAME = "FM"
    LABELS = ("Ratio", "Depth", "Pluck")
    MELODIC = True
    NOTE = 72
    DEFAULTS = {"tune": 0, "decay": 0.6, "color": 0.5, "shape": 0.35, "sweep": 0.7}
    RATIOS = (0.5, 1.0, 1.5, 2.0, 3.0, 3.5, 4.0, 5.0, 7.0)

    def render(self, n):
        p = self.p
        t = self._time(n)
        f = self._freq()
        ratio = self.RATIOS[min(len(self.RATIOS) - 1, int(p["color"] * len(self.RATIOS)))]
        tau = decay_seconds(p["decay"])
        index = 9.0 * p["shape"] * ((1.0 - p["sweep"]) + p["sweep"] * np.exp(-t / (0.35 * tau)))
        mod = np.sin(TWO_PI * self._phase(1, f * ratio, n))
        y = np.sin(TWO_PI * self._phase(0, f, n) + index * mod)
        return y * self._amp(t) * 0.7


class Bass(Machine):
    NAME = "Bass"
    LABELS = ("Wave", "Sub", "Zap")
    MELODIC = True
    NOTE = 36
    DEFAULTS = {"tune": 0, "decay": 0.5, "color": 0.2, "shape": 0.4, "sweep": 0.1}

    def render(self, n):
        p = self.p
        t = self._time(n)
        f = self._freq()
        if p["sweep"] > 0.01:
            f = f * (1.0 + 3.0 * p["sweep"] * np.exp(-t * 35.0))
        dt = f / self.sr
        ph = self._phase(0, f, n)
        y = saw(ph, dt) * (1.0 - p["color"]) + pulse(ph, dt) * p["color"]
        y = y * 0.7 + np.sin(TWO_PI * self._phase(1, f * 0.5, n)) * p["shape"]
        return y * self._amp(t) * 0.8


class Lead(Machine):
    NAME = "Lead"
    LABELS = ("Detune", "Pulse", "Vibrato")
    MELODIC = True
    NOTE = 60
    DEFAULTS = {"tune": 0, "decay": 0.55, "color": 0.3, "shape": 0.3, "sweep": 0.2}

    def render(self, n):
        p = self.p
        t = self._time(n)
        f = self._freq()
        if p["sweep"] > 0.01:
            f = f * (1.0 + 0.03 * p["sweep"] * np.sin(TWO_PI * 5.6 * t) * np.minimum(1.0, t * 4.0))
        f2 = f * 2.0 ** (p["color"] * 0.5 / 12.0)
        y = saw(self._phase(0, f, n), f / self.sr)
        y2 = pulse(self._phase(1, f2, n), f2 / self.sr, 0.5 - 0.42 * p["shape"])
        return (y * (1.0 - 0.5 * p["shape"]) + y2 * (0.4 + 0.6 * p["shape"])) * self._amp(t) * 0.5


class Chord(Machine):
    NAME = "Chord"
    LABELS = ("Chord", "Detune", "Sub")
    MELODIC = True
    NOTE = 60
    DEFAULTS = {"tune": 0, "decay": 0.6, "color": 0.15, "shape": 0.3, "sweep": 0.2}
    CHORDS = ((0, 4, 7, 12), (0, 3, 7, 12), (0, 2, 7, 12), (0, 5, 7, 12), (0, 4, 7, 11),
              (0, 3, 7, 10), (0, 4, 7, 10), (0, 3, 10, 14), (0, 7, 12, 19))
    CHORD_NAMES = ("maj", "min", "sus2", "sus4", "maj7", "min7", "7", "min9", "5th")

    def render(self, n):
        p = self.p
        t = self._time(n)
        f0 = self._freq()
        chord = self.CHORDS[min(len(self.CHORDS) - 1, int(p["color"] * len(self.CHORDS)))]
        y = np.zeros(n)
        for k, semi in enumerate(chord):
            f = f0 * 2.0 ** ((semi + (k - 1.5) * 0.09 * p["shape"]) / 12.0)
            y += saw(self._phase(k, f, n), f / self.sr)
        if p["sweep"] > 0.01:
            y += 2.0 * p["sweep"] * np.sin(TWO_PI * f0 * 0.5 * t)
        return y * self._amp(t) * 0.25


class Noise(Machine):
    NAME = "Noise"
    LABELS = ("Color", "Grain", "Swell")
    NOTE = 60
    DEFAULTS = {"tune": 0, "decay": 0.5, "color": 0.5, "shape": 0.0, "sweep": 0.0}

    def render(self, n):
        p = self.p
        t = self._time(n)
        rate = 2.0 ** ((self.note - 60 + p["tune"]) / 12.0) / (1.0 + 30.0 * p["shape"] ** 2)
        y = self._noise("mid", n, rate) * (1.0 - p["color"]) + self._noise("bright", n, rate) * p["color"]
        swell = p["sweep"] * 1.5
        if swell <= 0.002:
            return y * self._amp(t) * 0.7
        tau = decay_seconds(p["decay"])
        amp = np.minimum(1.0, t / swell) ** 2 * np.exp(-np.maximum(t - swell, 0.0) / tau)
        if t[-1] > swell and amp[-1] < 1e-4:
            self.active = False
        return y * amp * self.vel * 0.7


MACHINES = {cls.NAME: cls for cls in (Kick, Snare, Hat, Clap, Tom, FM, Bass, Lead, Chord, Noise)}
MACHINE_NAMES = tuple(MACHINES)
