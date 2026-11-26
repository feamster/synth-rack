"""Wander: a six-voice keyboard synth with switchable engines and an arp.

Voices are summed into one resonant filter (paraphonic) and a stereo chorus.
Notes arrive through ``command("on" | "off" | "panic", ...)``.
"""

from __future__ import annotations

import math

import numpy as np
import pedalboard as pb

from .core import ADSR, F32, TWO_PI, DelayLine, Module, Param, Ramp, cutoff_hz, midi_hz, pulse, run, saw
from .library import LIBRARY

VOICES = 6
ENGINES = ("Stack", "Pulse", "FM", "Pluck", "Organ", "Sample")
ENGINE_LABELS = {"Stack": ("Detune", "Sub"), "Pulse": ("PWM", "Width"), "FM": ("Ratio", "Depth"),
                 "Pluck": ("Ring", "Pick"), "Organ": ("Bright", "Click"), "Sample": ("Start", "Tone")}
ARP_MODES = ("Off", "Up", "Down", "Up-Dn", "Random", "Played")
ARP_RATES = ("1/4", "1/8", "1/16")
_ARP_STEPS = (4, 2, 1)
LFO_DESTS = ("Pitch", "Filter", "Color")
OCTAVES = ("-2", "-1", "0", "+1", "+2")
FM_RATIOS = (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0)
TABLE = 2048
_tables: dict = {}


def wavetables(sr: float) -> dict:
    """Band-limited single cycles, one per octave, for the Pluck and Organ engines."""
    key = int(sr)
    if key not in _tables:
        recipes = {
            "bright": lambda h: 1.0 / h,
            "dull": lambda h: math.exp(-0.7 * (h - 1)) / h,
            "mellow": lambda h: {1: 1.0, 2: 0.5, 3: 0.3}.get(h, 0.0),
            "full": lambda h: {1: 1.0, 2: 0.8, 3: 0.7, 4: 0.5, 6: 0.4, 8: 0.3, 10: 0.15, 12: 0.1}.get(h, 0.0),
        }
        out = {}
        for name, amp in recipes.items():
            octaves = []
            for octave in range(11):
                top = midi_hz(12 * (octave + 1))
                spectrum = np.zeros(TABLE // 2 + 1, dtype=complex)
                for h in range(1, max(2, min(96, int(sr * 0.45 / top) + 1))):
                    spectrum[h] = -0.5j * TABLE * amp(h)
                wave = np.fft.irfft(spectrum, TABLE)
                wave = wave / max(1e-9, np.abs(wave).max())
                octaves.append(np.concatenate((wave, wave[:1])))
            out[name] = octaves
        _tables[key] = out
    return _tables[key]


def _lookup(table: np.ndarray, phase: np.ndarray) -> np.ndarray:
    pos = (phase % 1.0) * TABLE
    i0 = pos.astype(np.intp)
    frac = pos - i0
    return table[i0] * (1.0 - frac) + table[i0 + 1] * frac


class Voice:
    def __init__(self, sr: float):
        self.sr = sr
        self.env = ADSR(sr)
        self.note = 60.0
        self.vel = 0.8
        self.gate = False
        self.t = 0
        self.age = 0
        self.delay = 0          # samples to wait before the note starts (arp timing)
        self.phase = np.zeros(4)
        self.pos = 0.0

    def advance(self, k: int, freq, n: int) -> np.ndarray:
        if np.ndim(freq):
            inc = np.cumsum(freq) / self.sr
            out = self.phase[k] + inc - freq / self.sr
            self.phase[k] = (self.phase[k] + inc[-1]) % 1.0
            return out
        inc = freq / self.sr
        out = self.phase[k] + inc * np.arange(n)
        self.phase[k] = (self.phase[k] + inc * n) % 1.0
        return out


class Wander(Module):
    TYPE = "wander"
    NAME = "Wander"
    TAGLINE = "pocket keyboard synth"
    FINISH = "paper"
    WIDTH = 520
    INPUTS = ()
    OUTPUTS = ("out",)
    PARAMS = (
        Param("color", "Color", default=0.35),
        Param("shape", "Shape", default=0.3),
        Param("cutoff", "Cutoff", default=0.72, unit="cut"),
        Param("reso", "Reso", default=0.15),
        Param("attack", "Attack", 0.001, 2.0, 0.005, "s", skew=3.0),
        Param("decay", "Decay", 0.01, 3.0, 0.5, "s", skew=2.0),
        Param("sustain", "Sustain", default=0.6),
        Param("release", "Release", 0.01, 4.0, 0.35, "s", skew=2.0),
        Param("env", "Env", default=0.3),
        Param("lfo_rate", "LFO Rate", 0.05, 12.0, 4.0, "Hz", skew=2.0),
        Param("lfo_depth", "LFO", default=0.0),
        Param("chorus", "Chorus", default=0.35),
        Param("level", "Level", default=0.7),
        Param("engine", "Engine", default=3, choices=ENGINES),
        Param("arp", "Arp", default=0, choices=ARP_MODES),
        Param("arp_rate", "Rate", default=2, choices=ARP_RATES),
        Param("lfo_dest", "LFO to", default=0, choices=LFO_DESTS),
        Param("octave", "Octave", default=2, choices=OCTAVES),
        Param("hold", "Hold", default=0, choices=("Off", "On")),
    )
    library = LIBRARY

    def _build(self) -> None:
        sr = self.sr
        self.voices = [Voice(sr) for _ in range(VOICES)]
        self.tables = wavetables(sr)
        self.filter = pb.LadderFilter(mode=pb.LadderFilter.Mode.LPF24)
        self.chorus = DelayLine(int(sr * 0.05), channels=1)
        self.lfo_phase = 0.0
        self.chorus_phase = 0.0
        self.gain = Ramp()
        self.down: list = []        # keys physically held, in the order pressed
        self.latched: list = []     # notes the arp / hold is keeping alive
        self.arp_clock = 0.0        # steps, free-running when the transport is stopped
        self.arp_index = 0
        self.arp_note = None
        self.arp_off_at = 0.0
        self.rng = np.random.default_rng(9)
        self.scope = np.zeros(256)
        self._age = 0
        self._was_hold = False
        self._freset = True
        if not hasattr(self, "sample_name"):
            self.sample_name = "Keys"
        self.sample = self.library.get(self.sample_name)

    def set_sample(self, name: str) -> None:
        sample = self.library.get(name)
        if sample is not None:
            self.sample, self.sample_name = sample, name

    def sounding(self) -> list[int]:
        """Notes whose keys are down or latched, for the keyboard display."""
        return [int(v.note) for v in self.voices if v.gate]

    # -- voices -------------------------------------------------------
    def _note_on(self, note: float, vel: float, delay: int = 0) -> None:
        if not any(v.env.active for v in self.voices):
            self._freset = True
        voice = next((v for v in self.voices if not v.env.active), None)
        if voice is None:
            voice = min(self.voices, key=lambda v: (v.gate, v.age))
        self._age += 1
        voice.note, voice.vel, voice.gate, voice.age = float(note), float(vel), True, self._age
        voice.t, voice.delay = 0, delay
        voice.phase = self.rng.random(4)
        voice.pos = 0.0
        voice.env.level = 0.0
        voice.env.gate(True)

    def _note_off(self, note: float) -> None:
        for v in self.voices:
            if v.gate and v.note == note:
                v.gate = False
                v.env.gate(False)

    def _all_off(self) -> None:
        for v in self.voices:
            v.gate = False
            v.env.gate(False)

    def _handle(self, cmd) -> None:
        arp = int(self.values["arp"]) > 0
        hold = int(self.values["hold"]) == 1
        if cmd[0] == "on":
            note, vel = float(cmd[1]), float(cmd[2])
            if hold and not self.down:           # a fresh chord replaces the latched one
                if not arp:
                    self._all_off()
                self.latched = []
            if note not in self.down:
                self.down.append(note)
            if note not in self.latched:
                self.latched.append(note)
            self.vel = vel
            if not arp:
                self._note_on(note + self._transpose(), vel)
        elif cmd[0] == "off":
            note = float(cmd[1])
            if note in self.down:
                self.down.remove(note)
            if not hold:
                if note in self.latched:
                    self.latched.remove(note)
                if not arp:
                    self._note_off(note + self._transpose())
        elif cmd[0] == "panic":
            self.down, self.latched, self.arp_note = [], [], None
            self._all_off()

    def _transpose(self) -> float:
        return 12.0 * (int(self.values["octave"]) - 2)

    # -- arp ----------------------------------------------------------
    def _arp_fire(self, offset: int, span: float) -> None:
        if self.arp_note is not None:
            self._note_off(self.arp_note)
            self.arp_note = None
        notes = list(self.latched)
        if not notes:
            return
        mode = ARP_MODES[int(self.values["arp"])]
        if mode != "Played":
            notes.sort()
        if mode == "Down":
            notes.reverse()
        elif mode == "Up-Dn" and len(notes) > 2:
            notes = notes + notes[-2:0:-1]
        if mode == "Random":
            note = notes[int(self.rng.integers(len(notes)))]
        else:
            note = notes[self.arp_index % len(notes)]
        self.arp_index += 1
        self.arp_note = note + self._transpose()
        self.arp_off_at = self.arp_clock + 0.6 * span
        self._note_on(self.arp_note, getattr(self, "vel", 0.8), offset)

    def _run_arp(self, clock) -> None:
        n = clock.n
        span = _ARP_STEPS[int(self.values["arp_rate"])]
        if clock.started:
            self.arp_clock, self.arp_index = 0.0, 0
        start = self.arp_clock
        end = start + n / clock.sps
        if self.arp_note is not None and start >= self.arp_off_at:
            self._note_off(self.arp_note)
            self.arp_note = None
        if clock.playing:
            for off, k in clock.events:
                if k % span == 0:
                    self.arp_clock = float(k)
                    self._arp_fire(off, span)
            self.arp_clock = clock.step_pos + n / clock.sps
        else:
            k = math.ceil(start / span - 1e-9) * span
            if start <= k < end:
                self.arp_clock = float(k)
                self._arp_fire(int((k - start) * clock.sps), span)
            self.arp_clock = end

    # -- synthesis ----------------------------------------------------
    def _render_voice(self, v: Voice, n: int, engine: int, color: float, shape: float, bend) -> np.ndarray:
        sr = self.sr
        f = midi_hz(v.note) * bend
        t = (v.t + np.arange(n)) / sr
        v.t += n
        if engine == 0:        # Stack: three detuned saws and a sub
            spread = 2.0 ** (0.35 * color / 12.0)
            y = sum(saw(v.advance(k, f * m, n), np.mean(f * m) / sr)
                    for k, m in enumerate((1.0, spread, 1 / spread)))
            y = y / 3.0 + shape * 0.6 * pulse(v.advance(3, f * 0.5, n), np.mean(f) * 0.5 / sr)
        elif engine == 1:      # Pulse with width modulation
            width = 0.5 - 0.42 * shape + 0.07 * color * np.sin(TWO_PI * (0.8 * t + v.phase[3]))
            y = pulse(v.advance(0, f, n), np.mean(f) / sr, np.clip(width, 0.04, 0.96)) * 0.7
        elif engine == 2:      # two-operator FM
            ratio = FM_RATIOS[min(len(FM_RATIOS) - 1, int(color * len(FM_RATIOS)))]
            index = 8.0 * shape * (0.3 + 0.7 * np.exp(-t / 0.5))
            y = np.sin(TWO_PI * v.advance(0, f, n) + index * np.sin(TWO_PI * v.advance(1, f * ratio, n)))
        elif engine in (3, 4):
            octave = min(10, max(0, int(v.note // 12)))
            ph = v.advance(0, f, n)
            if engine == 3:    # Pluck: a bright cycle decaying into a dull one
                bright = _lookup(self.tables["bright"][octave], ph)
                dull = _lookup(self.tables["dull"][octave], ph)
                y = dull + (bright - dull) * (0.25 + 0.75 * shape) * np.exp(-t / (0.04 + 1.6 * color * color))
            else:              # Organ: drawbars, with a percussive click
                y = _lookup(self.tables["mellow"][octave], ph) * (1.0 - color) \
                    + _lookup(self.tables["full"][octave], ph) * color
                y = y + shape * np.sin(TWO_PI * 3.0 * ph) * np.exp(-t * 14.0)
            y = y * 0.8
        else:                  # Sample, played chromatically from C4
            sample = self.sample
            if sample is None or len(sample.data) < 4:
                return np.zeros(n)
            data = sample.data
            last = len(data) - 2
            rate = sample.sr / sr * f / midi_hz(60.0)
            if v.pos == 0.0:
                v.pos = 1e-9 + color * last * 0.9
            idx = v.pos + (np.cumsum(rate) if np.ndim(rate) else rate * np.arange(n))
            v.pos = float(idx[-1]) + 1e-9
            i0 = np.minimum(idx, last).astype(np.intp)
            frac = np.minimum(idx - i0, 1.0)
            y = (data[i0] * (1.0 - frac) + data[i0 + 1] * frac) * (idx < last)
        return y

    def process(self, ins, clock):
        n = clock.n
        p = self.values
        for cmd in self._drain():
            self._handle(cmd)
        hold = int(p["hold"]) == 1
        arp = int(p["arp"]) > 0
        if self._was_hold and not hold:      # hold released: let go of everything not under a finger
            for note in [x for x in self.latched if x not in self.down]:
                self.latched.remove(note)
                self._note_off(note + self._transpose())
        self._was_hold = hold
        if arp:
            self._run_arp(clock)
        elif self.arp_note is not None:
            self._note_off(self.arp_note)
            self.arp_note = None
        if not any(v.env.active for v in self.voices):
            self.scope = np.zeros(8)
            return {}

        lfo = math.sin(TWO_PI * self.lfo_phase)
        self.lfo_phase = (self.lfo_phase + p["lfo_rate"] * n / self.sr) % 1.0
        dest, depth = int(p["lfo_dest"]), p["lfo_depth"]
        color = min(1.0, max(0.0, p["color"] + (0.5 * depth * lfo if dest == 2 else 0.0)))
        bend = 1.0
        if dest == 0 and depth > 0.001:
            ph = self.lfo_phase - p["lfo_rate"] * (n - np.arange(n)) / self.sr
            bend = 2.0 ** (depth * 0.5 * np.sin(TWO_PI * ph) / 12.0)
        engine = int(p["engine"])
        mix = np.zeros(n)
        peak = 0.0
        for v in self.voices:
            if not v.env.active:
                continue
            m = n - v.delay
            if m <= 0:
                v.delay -= n
                continue
            vb = bend[v.delay:] if np.ndim(bend) else bend
            y = self._render_voice(v, m, engine, color, p["shape"], vb)
            env = v.env.render(m, p["attack"], p["decay"], p["sustain"], p["release"])
            mix[v.delay:] += y * env * v.vel
            v.delay = 0
            peak = max(peak, v.env.level)

        c = p["cutoff"] + p["env"] * 0.6 * (peak - 0.5) + (0.25 * depth * lfo if dest == 1 else 0.0)
        self.filter.cutoff_hz = cutoff_hz(c)
        self.filter.resonance = min(0.9, p["reso"])
        y = run(self.filter, mix[None, :] * 0.4, self.sr, reset=self._freset)
        self._freset = False
        self.scope = y[0].copy()

        self.chorus.write(y)
        amount = p["chorus"]
        ph = self.chorus_phase + 0.6 * np.arange(n) / self.sr
        self.chorus_phase = (self.chorus_phase + 0.6 * n / self.sr) % 1.0
        base, swing = 0.012 * self.sr, 0.004 * self.sr
        left = self.chorus.read(base + swing * np.sin(TWO_PI * ph), n)[0]
        right = self.chorus.read(base + swing * np.sin(TWO_PI * (ph + 0.25)), n)[0]
        out = np.stack([y[0] + amount * left, y[0] + amount * right])
        return {"out": (out * self.gain.block(2.2 * p["level"] ** 2 / (1.0 + 0.5 * amount), n)).astype(F32)}

    def state(self) -> dict:
        return {"sample": self.sample_name}

    def load_state(self, data: dict) -> None:
        if data.get("sample"):
            self.set_sample(data["sample"])
