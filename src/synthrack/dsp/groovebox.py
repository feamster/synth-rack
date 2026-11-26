"""The groovebox core shared by Knockbox (samples) and Forge (synth machines).

Eight mono tracks, each a voice -> filter -> drive -> crush -> level/pan with a
send, driven by an 8-pattern step sequencer with per-step parameter locks.

Threading: the UI replaces whole objects (a ``Step``, a track's step list, a
voice) and writes plain values; anything that must happen at a precise time
(live trigs, sampling) goes through ``command()``.
"""

from __future__ import annotations

import math
import random

import numpy as np
import pedalboard as pb

from .core import F32, Module, Param, Ramp, cutoff_hz, decay_seconds, pan_gains, run
from .library import LIBRARY
from .machines import MACHINE_NAMES, MACHINES

TRACKS = 8
MAX_STEPS = 64
PATTERNS = 8
PATTERN_NAMES = tuple(f"A{i + 1}" for i in range(PATTERNS))
LENGTHS = (16, 32, 48, 64)
FILTER_TYPES = ("LP24", "LP12", "HP", "BP")
_MODES = (pb.LadderFilter.Mode.LPF24, pb.LadderFilter.Mode.LPF12,
          pb.LadderFilter.Mode.HPF24, pb.LadderFilter.Mode.BPF12)
DECLICK = 64
_FADE = np.linspace(1.0, 0.0, DECLICK)
SCALE = (0, 3, 5, 7, 10, 12, -2, -5)    # minor pentatonic around the root, for DICE
MAX_SAMPLING_SECONDS = 10.0

COMMON_PARAMS = (
    Param("drive", "Drive", default=0.0),
    Param("crush", "Crush", default=0.0),
    Param("cutoff", "Cutoff", default=1.0, unit="cut"),
    Param("reso", "Reso", default=0.0),
    Param("fenv", "Env", -1.0, 1.0, 0.0, "±"),
    Param("fdec", "F.Decay", default=0.4, unit="dec"),
    Param("level", "Level", default=0.7),
    Param("pan", "Pan", -1.0, 1.0, 0.0, "pan"),
    Param("send", "Send", default=0.0),
    Param("ftype", "Filter", default=0, choices=FILTER_TYPES),
)
SAMPLE_PARAMS = (
    Param("tune", "Tune", -24.0, 24.0, 0.0, "st"),
    Param("start", "Start", default=0.0),
    Param("length", "Length", default=1.0),
    Param("attack", "Attack", 0.0, 0.5, 0.0, "s", skew=3.0),
    Param("decay", "Decay", default=1.0, unit="env"),
)
SYNTH_PARAMS = (
    Param("tune", "Tune", -24.0, 24.0, 0.0, "st"),
    Param("color", "Color", default=0.5),
    Param("shape", "Shape", default=0.5),
    Param("sweep", "Sweep", default=0.5),
    Param("decay", "Decay", default=0.5, unit="dec"),
)
TRIG_PARAMS = (
    Param("note", "Note", 24.0, 96.0, 60.0, "int"),
    Param("vel", "Vel", default=0.8),
    Param("length", "Len", 1.0, 16.0, 1.0, "int"),
    Param("prob", "Prob", default=1.0),
)
_TRIG = {p.key: p for p in TRIG_PARAMS}
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(note: float) -> str:
    note = int(round(note))
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


class Step:
    """One trig. Treated as immutable: edits replace the object."""

    __slots__ = ("note", "vel", "length", "prob", "locks")

    def __init__(self, note=60.0, vel=0.8, length=1.0, prob=1.0, locks=None):
        self.note = _TRIG["note"].clamp(note)
        self.vel = _TRIG["vel"].clamp(vel)
        self.length = _TRIG["length"].clamp(length)
        self.prob = _TRIG["prob"].clamp(prob)
        self.locks = dict(locks or {})

    def replace(self, **changes) -> Step:
        fields = {k: getattr(self, k) for k in self.__slots__}
        fields.update(changes)
        return Step(**fields)

    def to_list(self) -> list:
        return [self.note, round(self.vel, 3), self.length, round(self.prob, 3), self.locks]

    @classmethod
    def from_list(cls, data) -> Step:
        return cls(*data[:4], locks=data[4] if len(data) > 4 else None)


class Pattern:
    def __init__(self):
        self.length = 16
        self.steps = [[None] * MAX_STEPS for _ in range(TRACKS)]

    @property
    def empty(self) -> bool:
        return not any(st for row in self.steps for st in row)

    def to_dict(self) -> dict:
        return {"length": self.length,
                "tracks": [{str(i): st.to_list() for i, st in enumerate(row) if st} for row in self.steps]}

    @classmethod
    def from_dict(cls, data: dict, lock_params: dict | None = None) -> Pattern:
        pat = cls()
        length = int(data.get("length", 16))
        pat.length = length if length in LENGTHS else 16
        for t, row in enumerate(data.get("tracks", [])[:TRACKS]):
            for key, value in row.items():
                i = int(key)
                if 0 <= i < MAX_STEPS:
                    st = Step.from_list(value)
                    if lock_params is not None:
                        st.locks = {k: lock_params[k].clamp(v) for k, v in st.locks.items()
                                    if k in lock_params}
                    pat.steps[t][i] = st
        return pat

    def copy(self) -> Pattern:
        return Pattern.from_dict(self.to_dict())


class SampleVoice:
    """Plays the track's sample: pitch, start/length window, attack/decay."""

    MELODIC = False
    NOTE = 60

    def __init__(self, sr: float, track):
        self.sr = float(sr)
        self.track = track
        self.active = False
        self.data = None

    def trigger(self, note, vel, p, hold=0.0) -> None:
        sample = self.track.sample
        if sample is None or len(sample.data) < 4:
            self.active = False
            return
        self.p = p
        self.data = sample.data
        last = len(self.data) - 2
        self.rate = sample.sr / self.sr * 2.0 ** ((p["tune"] + note - 60.0) / 12.0)
        self.pos = p["start"] * (last - 2)
        self.end = min(float(last), self.pos + max(48.0, p["length"] * (last - self.pos)))
        self.vel = float(vel)
        self.t = 0
        self.active = True

    def render(self, n: int) -> np.ndarray:
        p = self.p
        idx = self.pos + self.rate * np.arange(n)
        self.pos += self.rate * n
        t = (self.t + np.arange(n)) / self.sr
        self.t += n
        i0 = np.minimum(idx, self.end).astype(np.intp)
        frac = idx - i0
        y = self.data[i0] * (1.0 - frac) + self.data[i0 + 1] * frac
        env = np.clip((self.end - idx) / (DECLICK * self.rate), 0.0, 1.0)   # also zero past the end
        attack = p["attack"]
        if attack > 0.0005:
            env = env * np.minimum(1.0, t / attack)
        if p["decay"] < 0.98:
            env = env * np.exp(-np.maximum(t - attack, 0.0) / decay_seconds(p["decay"]))
        if idx[-1] >= self.end or (t[-1] > attack and env[-1] < 1e-4):
            self.active = False
        return y * env * self.vel


class Track:
    def __init__(self, box, index: int):
        self.box = box
        self.index = index
        self.values = {p.key: p.default for p in box.TRACK_PARAMS}
        self.trig = {p.key: p.default for p in TRIG_PARAMS}
        self.sound = ""
        self.sample = None
        self.mute = False
        self.flash = 0          # bumped on every trigger; the UI watches it
        self.voice = None
        self.build()

    def build(self) -> None:
        self.filter = pb.LadderFilter()
        self.fmode = -1
        self.eff = self.values  # the parameters the sounding voice uses (values + step locks)
        self.vt = 0
        self.gain = Ramp()
        self.ring = 0
        self._tail = None
        self._freset = False
        self._held = 0.0
        self._crush_phase = 0

    def trigger(self, step: Step, clock) -> None:
        self.eff = {**self.values, **step.locks} if step.locks else self.values
        self.voice.trigger(step.note, step.vel, self.eff, step.length * clock.sps / clock.sr)
        self.vt = 0
        self.flash += 1
        if self.eff["fenv"]:
            self._freset = True     # snap the filter's smoothed cutoff so the envelope has an attack

    def render(self, n: int, events, clock):
        """Mono block for this track, or None when it is silent."""
        voice = self.voice
        if voice is None or (not events and not voice.active and self._tail is None and self.ring <= 0):
            return None
        out = np.zeros(n)
        if self._tail is not None:
            k = min(n, len(self._tail))
            out[:k] += self._tail[:k]
            self._tail = self._tail[k:] if k < len(self._tail) else None
        pos = 0
        for off, step in events:
            if voice.active:
                if off > pos:
                    out[pos:off] += voice.render(off - pos)
                if voice.active:                       # fade the old note out under the new one
                    tail = voice.render(DECLICK) * _FADE
                    k = min(n - off, DECLICK)
                    out[off:off + k] += tail[:k]
                    if k < DECLICK:
                        self._tail = tail[k:]
            self.trigger(step, clock)
            voice = self.voice
            pos = off
        if voice.active:
            out[pos:] += voice.render(n - pos)

        p = self.eff
        sr = self.box.sr
        c, ftype = p["cutoff"], int(p["ftype"])
        if p["fenv"]:
            c += p["fenv"] * math.exp(-(self.vt / sr) / decay_seconds(p["fdec"]))
        self.vt += n
        y = out
        if ftype or c < 0.995 or p["reso"] > 0.01:
            if ftype != self.fmode:
                self.filter.mode = _MODES[ftype]
                self.fmode = ftype
            self.filter.cutoff_hz = cutoff_hz(c)
            self.filter.resonance = min(0.95, p["reso"])
            y = run(self.filter, y[None, :], sr, reset=self._freset)[0]
            self._freset = False
        self.ring = int(0.08 * sr) if (voice.active or events) else self.ring - n
        d = p["drive"]
        if d > 0.005:
            g = 1.0 + 24.0 * d * d
            y = np.tanh(y * g) * ((1.0 - 0.3 * d) / math.tanh(g))
        k = int(1 + 40 * p["crush"] ** 2)
        if k > 1:
            c0 = self._crush_phase
            idx = np.maximum(((c0 + np.arange(n)) // k) * k - c0, -1) + 1
            ext = np.concatenate(([self._held], y))
            y = ext[idx]
            self._held = float(y[-1])
            self._crush_phase = (c0 + n) % k
        return y * self.gain.block(2.0 * p["level"] ** 2, n)


class GrooveBox(Module):
    WIDTH = 700
    INPUTS = ("in",)
    OUTPUTS = ("out", "send")
    PARAMS = (Param("volume", "Volume", default=0.8),)
    TRACK_PARAMS: tuple = ()
    SOURCE_KEYS: tuple = ()
    DEFAULT_KIT: tuple = ()
    ACCENT = "#d9a441"

    def _build(self) -> None:
        if not hasattr(self, "tracks"):
            self.tracks = [Track(self, i) for i in range(TRACKS)]
            self.patterns = [Pattern() for _ in range(PATTERNS)]
            self.pattern = 0
            self.next_pattern: int | None = None
            self.selected = 0
            self.record = False
            self.link = True
            for t, name in enumerate(self.DEFAULT_KIT):
                self.set_sound(t, name)
        else:
            for t, track in enumerate(self.tracks):
                track.build()
                self.set_sound(t, track.sound, defaults=False)
        self.count = 0           # steps since the transport started
        self.play_step = -1      # step being played, for the display
        self.running = False
        self.rng = np.random.default_rng(5)
        self.vol = Ramp()
        self._skip = None
        self.clip_board = None

    @classmethod
    def track_param(cls, key: str) -> Param:
        for p in cls.TRACK_PARAMS:
            if p.key == key:
                return p
        raise KeyError(key)

    # -- sounds -------------------------------------------------------
    def sounds(self) -> list[str]:
        raise NotImplementedError

    def set_sound(self, t: int, name: str, defaults: bool = True) -> None:
        raise NotImplementedError

    def labels(self, t: int) -> dict:
        """Knob captions that depend on the track's sound."""
        return {}

    def melodic(self, t: int) -> bool:
        return bool(getattr(self.tracks[t].voice, "MELODIC", False))

    # -- playing (UI thread) ---------------------------------------------
    def play(self, t: int, note: float | None = None, vel: float | None = None) -> None:
        track = self.tracks[t]
        self.command("trig", t, track.trig["note"] if note is None else note,
                     track.trig["vel"] if vel is None else vel)

    # -- pattern editing (UI thread) ----------------------------------------
    @property
    def pat(self) -> Pattern:
        return self.patterns[self.pattern]

    def new_step(self, t: int) -> Step:
        return Step(**self.tracks[t].trig)

    def toggle_step(self, t: int, i: int) -> Step | None:
        row = self.pat.steps[t]
        row[i] = None if row[i] else self.new_step(t)
        return row[i]

    def set_step(self, t: int, i: int, step: Step | None) -> None:
        self.pat.steps[t][i] = step

    def clear_track(self, t: int) -> None:
        self.pat.steps[t] = [None] * MAX_STEPS

    def clear_pattern(self) -> None:
        for t in range(TRACKS):
            self.clear_track(t)

    def select_pattern(self, index: int) -> None:
        index = int(index) % PATTERNS
        if self.running and index != self.pattern:
            self.next_pattern = index      # switches when the current pattern wraps
        else:
            self.pattern, self.next_pattern = index, None

    def copy_pattern(self) -> None:
        self.clip_board = self.pat.to_dict()

    def paste_pattern(self) -> None:
        if self.clip_board:
            self.patterns[self.pattern] = Pattern.from_dict(self.clip_board)

    def dice(self, t: int, seed: int | None = None) -> None:
        """Roll a new pattern for one track."""
        rng = random.Random(seed)
        track = self.tracks[t]
        melodic = self.melodic(t)
        density = rng.choice((0.3, 0.4, 0.55))
        row = [None] * MAX_STEPS
        for i in range(self.pat.length):
            weight = 1.0 if i % 4 == 0 else 0.55 if i % 2 == 0 else 0.3
            if rng.random() < density * weight * 1.6:
                note = track.trig["note"] + (rng.choice(SCALE) if melodic else 0)
                vel = 0.85 if i % 4 == 0 else rng.uniform(0.4, 0.75)
                row[i] = Step(note, vel, rng.choice((1, 1, 2)) if melodic else 1, 1.0)
        if not any(row):
            row[0] = self.new_step(t)
        self.pat.steps[t] = row

    # -- audio thread ---------------------------------------------------
    def _handle(self, cmd, clock, live) -> None:
        if cmd[0] == "trig":
            _, t, note, vel = cmd
            track = self.tracks[t]
            step = Step(note, vel, track.trig["length"], 1.0)
            live[t].append((0, step))
            if self.record and clock.playing and self.count:
                pat = self.pat
                frac = clock.step_pos - math.floor(clock.step_pos)
                current = (self.count - 1) % pat.length
                if frac < 0.5:
                    pat.steps[t][current] = step
                else:                       # nearer the next step: write it there, don't double-hit
                    nxt = self.count % pat.length
                    pat.steps[t][nxt] = step
                    self._skip = (t, nxt)

    def process(self, ins, clock):
        n = clock.n
        events = [[] for _ in range(TRACKS)]
        for cmd in self._drain():
            self._handle(cmd, clock, events)
        if clock.started:
            self.count = 0
        if clock.stopped:
            self.play_step = -1
            if self.next_pattern is not None:
                self.pattern, self.next_pattern = self.next_pattern, None
        self.running = clock.playing
        for off, _ in clock.events:
            pat = self.patterns[self.pattern]
            local = self.count % pat.length
            if local == 0 and self.next_pattern is not None:
                self.pattern, self.next_pattern = self.next_pattern, None
                self.count = 0
                pat = self.patterns[self.pattern]
            self.play_step = local
            self.count += 1
            for t, track in enumerate(self.tracks):
                step = pat.steps[t][local]
                if step is None or track.mute:
                    continue
                if self._skip == (t, local):
                    self._skip = None
                    continue
                if step.prob < 1.0 and self.rng.random() >= step.prob:
                    continue
                events[t].append((off, step))
        main = np.zeros((2, n))
        send = None
        for t, track in enumerate(self.tracks):
            y = track.render(n, events[t], clock)
            if y is None:
                continue
            left, right = pan_gains(track.eff["pan"])
            main[0] += y * left
            main[1] += y * right
            amount = track.eff["send"]
            if amount > 0.005:
                if send is None:
                    send = np.zeros((2, n))
                send[0] += y * (left * amount)
                send[1] += y * (right * amount)
        ext = ins.get("in")
        self._external(ext, n)
        vol = self.vol.block(0.9 * self.values["volume"] ** 2, n)
        main = main * vol
        if ext is not None:
            main = main + ext
        out = {"out": main.astype(F32)}
        if send is not None:
            out["send"] = (send * vol).astype(F32)
        return out

    def _external(self, ext, n: int) -> None:
        pass

    # -- persistence --------------------------------------------------
    def state(self) -> dict:
        return {
            "pattern": self.pattern, "selected": self.selected, "link": self.link,
            "patterns": [p.to_dict() for p in self.patterns],
            "tracks": [{"sound": t.sound, "mute": t.mute, "params": dict(t.values), "trig": dict(t.trig)}
                       for t in self.tracks],
        }

    def load_state(self, data: dict) -> None:
        params = {p.key: p for p in self.TRACK_PARAMS}
        for t, entry in enumerate(data.get("tracks", [])[:TRACKS]):
            track = self.tracks[t]
            if entry.get("sound"):
                self.set_sound(t, entry["sound"])
            track.mute = bool(entry.get("mute", False))
            for key, value in (entry.get("params") or {}).items():
                if key in params:
                    track.values[key] = params[key].clamp(value)
            for key, value in (entry.get("trig") or {}).items():
                if key in _TRIG:
                    track.trig[key] = _TRIG[key].clamp(value)
        if "patterns" in data:
            loaded = [Pattern.from_dict(p, params) for p in data["patterns"][:PATTERNS]]
            self.patterns = loaded + [Pattern() for _ in range(PATTERNS - len(loaded))]
        self.pattern = int(data.get("pattern", 0)) % PATTERNS
        self.selected = int(data.get("selected", 0)) % TRACKS
        self.link = bool(data.get("link", True))


class Knockbox(GrooveBox):
    TYPE = "knockbox"
    NAME = "Knockbox"
    TAGLINE = "8-track sample drum machine"
    FINISH = "carbon"
    ACCENT = "#d9a441"
    TRACK_PARAMS = SAMPLE_PARAMS + COMMON_PARAMS
    SOURCE_KEYS = tuple(p.key for p in SAMPLE_PARAMS)
    DEFAULT_KIT = ("Kick Punch", "Snare Tight", "Hat Closed", "Hat Open", "Clap", "Rim",
                   "Bass Pluck", "Stab Minor")
    library = LIBRARY

    def _build(self) -> None:
        super()._build()
        self.sampling = False        # recording the in jack into a track
        self.sampled = None          # (blocks, track index) waiting for the UI to save
        self._blocks: list = []
        self._sampling_track = 0

    def sounds(self) -> list[str]:
        return self.library.names()

    def set_sound(self, t: int, name: str, defaults: bool = True) -> None:
        track = self.tracks[t]
        sample = self.library.get(name)
        if sample is None and track.sample is None:
            name = self.DEFAULT_KIT[t]
            sample = self.library.get(name)
        if sample is None:
            return
        if track.voice is None:
            track.voice = SampleVoice(self.sr, track)
        elif track.voice.sr != self.sr:
            track.voice = SampleVoice(self.sr, track)
        track.sample = sample
        track.sound = name

    def _handle(self, cmd, clock, live) -> None:
        if cmd[0] == "sample":
            _, on, t = cmd
            if on and not self.sampling:
                self._blocks, self._sampling_track, self.sampling = [], t, True
            elif not on and self.sampling:
                self._finish_sampling()
        else:
            super()._handle(cmd, clock, live)

    def _finish_sampling(self) -> None:
        self.sampling = False
        if self._blocks:
            self.sampled = (self._blocks, self._sampling_track)
        self._blocks = []

    def _external(self, ext, n: int) -> None:
        if not self.sampling:
            return
        self._blocks.append(np.zeros(n, dtype=F32) if ext is None else ext.mean(axis=0).astype(F32))
        if len(self._blocks) * n > MAX_SAMPLING_SECONDS * self.sr:
            self._finish_sampling()

    def take_sampled(self):
        """UI thread: (mono audio, track) of a finished recording, once."""
        done, self.sampled = self.sampled, None
        if not done:
            return None
        return np.concatenate(done[0]), done[1]


class Forge(GrooveBox):
    TYPE = "forge"
    NAME = "Forge"
    TAGLINE = "8-track drum + synth machine"
    FINISH = "fog"
    ACCENT = "#e2553a"
    TRACK_PARAMS = SYNTH_PARAMS + COMMON_PARAMS
    SOURCE_KEYS = tuple(p.key for p in SYNTH_PARAMS)
    DEFAULT_KIT = ("Kick", "Snare", "Hat", "Clap", "Tom", "FM", "Bass", "Lead")

    def sounds(self) -> list[str]:
        return list(MACHINE_NAMES)

    def set_sound(self, t: int, name: str, defaults: bool = True) -> None:
        track = self.tracks[t]
        cls = MACHINES.get(name) or MACHINES[self.DEFAULT_KIT[t]]
        changed = track.sound != cls.NAME
        track.voice = cls(self.sr)
        track.sound = cls.NAME
        if defaults and changed:
            track.values.update(cls.DEFAULTS)
            track.trig["note"] = float(cls.NOTE)

    def labels(self, t: int) -> dict:
        cls = type(self.tracks[t].voice)
        return dict(zip(("color", "shape", "sweep"), cls.LABELS))

    def randomize(self, t: int, seed: int | None = None) -> None:
        """Roll new source settings for a track (RAND)."""
        rng = random.Random(seed)
        track = self.tracks[t]
        for key in ("color", "shape", "sweep"):
            track.values[key] = round(rng.random(), 3)
        track.values["decay"] = round(rng.uniform(0.15, 0.75), 3)
        if self.melodic(t):
            track.values["cutoff"] = round(rng.uniform(0.35, 0.9), 3)
            track.values["reso"] = round(rng.uniform(0.0, 0.6), 3)
            track.values["fenv"] = round(rng.uniform(0.0, 0.5), 3)

    def init_sound(self, t: int) -> None:
        track = self.tracks[t]
        for p in self.TRACK_PARAMS:
            track.values[p.key] = p.default
        track.values.update(type(track.voice).DEFAULTS)
