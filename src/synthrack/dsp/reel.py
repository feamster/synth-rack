"""Reel: a four-track tape loop that follows the transport.

The loop is a whole number of bars at the tempo it was first recorded at. It
plays like tape: if the transport tempo (or the speed switch) changes, pitch
moves with it. Recording needs the tape running at normal speed.

Tape buffers are allocated on the UI thread (``arm``) and handed over as whole
objects; the audio thread only reads and overdubs them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .core import F32, Module, Param, Ramp
from .library import write_wav

TRACKS = 4
BARS = (1, 2, 4, 8)
SPEEDS = (1.0, 0.5, 2.0, -1.0)
SPEED_NAMES = ("1×", "½×", "2×", "Rev")
MAX_SECONDS = 60.0
FADE = 96


class Reel(Module):
    TYPE = "reel"
    NAME = "Reel"
    TAGLINE = "4-track tape loop"
    FINISH = "paper"
    WIDTH = 340
    PARAMS = (
        Param("level1", "Trk 1", default=0.8), Param("level2", "Trk 2", default=0.8),
        Param("level3", "Trk 3", default=0.8), Param("level4", "Trk 4", default=0.8),
        Param("bars", "Bars", default=1, choices=tuple(str(b) for b in BARS)),
        Param("speed", "Speed", default=0, choices=SPEED_NAMES),
        Param("monitor", "Monitor", default=1, choices=("Off", "On")),
    )

    def _build(self) -> None:
        if not hasattr(self, "tape"):
            self.tape: list = [None] * TRACKS
            self.length = 0            # loop length in tape samples; 0 = blank tape
            self.tape_bpm = 120.0
            self.tape_sr = self.sr
            self.selected = 0
            self.mute = [False] * TRACKS
            self.dirty = [0] * TRACKS  # bumped whenever a track's audio changes
        self.pos = 0.0
        self.recording = False
        self.rec_track = 0
        self.rolling = False
        self.rate = 1.0
        self._fade_in = False
        self._stop_after = False
        self.gains = [Ramp() for _ in range(TRACKS)]

    # -- UI thread ----------------------------------------------------
    def has_audio(self) -> bool:
        return any(t is not None for t in self.tape)

    def arm(self, bpm: float) -> bool:
        """Get the selected track ready to record. False if the loop would be too long."""
        if not self.length:
            bars = BARS[int(self.values["bars"])]
            length = int(round(bars * 16 * self.sr * 60.0 / bpm / 4.0))
            if length > MAX_SECONDS * self.sr:
                return False
            self.tape_bpm, self.tape_sr, self.length = float(bpm), self.sr, length
        if self.tape[self.selected] is None:
            self.tape[self.selected] = np.zeros((2, self.length), dtype=F32)
        return True

    def erase(self, track: int | None = None) -> None:
        for t in range(TRACKS) if track is None else (track,):
            self.tape[t] = None
            self.dirty[t] += 1
        if not self.has_audio():
            self.length = 0

    def seconds(self) -> float:
        return self.length / self.tape_sr if self.length else 0.0

    def bounce(self):
        """The loop mixed to stereo at the tape's own rate, or None when blank."""
        if not self.has_audio():
            return None
        mix = np.zeros((2, self.length), dtype=F32)
        for t, buf in enumerate(self.tape):
            if buf is not None and not self.mute[t]:
                mix += buf * F32(self._level(t))
        return mix, int(self.tape_sr)

    def _level(self, t: int) -> float:
        return 1.5 * self.values[f"level{t + 1}"] ** 2

    # -- audio thread ---------------------------------------------------
    def process(self, ins, clock):
        n = clock.n
        x = ins.get("in")
        for cmd in self._drain():
            if cmd[0] == "rec":
                on, track = cmd[1], cmd[2]
                if on and not self.recording:
                    if clock.playing and self.length and self.tape[track] is not None:
                        self.recording, self.rec_track, self._fade_in = True, track, True
                elif not on and self.recording:
                    self._stop_after = True
        if clock.started:
            self.pos = 0.0
        self.rolling = clock.playing and bool(self.length)
        out = None
        if x is not None and int(self.values["monitor"]):
            out = x.copy()
        if not self.rolling:
            self.recording = self._stop_after = False
            return {} if out is None else {"out": out}
        if out is None:
            out = np.zeros((2, n), dtype=F32)
        length = self.length
        rate = SPEEDS[int(self.values["speed"])] * clock.bpm / self.tape_bpm * self.tape_sr / self.sr
        self.rate = rate
        straight = abs(rate - 1.0) < 1e-6
        if straight:
            idx = (int(self.pos) + np.arange(n)) % length
        else:
            fpos = (self.pos + rate * np.arange(n)) % length
            idx = fpos.astype(np.intp)
            frac = (fpos - idx).astype(F32)
            nxt = (idx + 1) % length
        for t, buf in enumerate(self.tape):
            gain = self.gains[t].block(0.0 if self.mute[t] else self._level(t), n)
            if buf is None or buf.shape[1] != length:
                continue
            if straight:
                out += buf[:, idx] * gain
            else:
                out += (buf[:, idx] * (1.0 - frac) + buf[:, nxt] * frac) * gain
        if self.recording:
            buf = self.tape[self.rec_track]
            if not straight or buf is None or buf.shape[1] != length:
                self.recording = self._stop_after = False
            elif x is not None:
                take = x
                k = min(n, FADE)
                if self._fade_in:
                    take = take.copy()
                    take[:, :k] *= np.linspace(0.0, 1.0, k, dtype=F32)
                if self._stop_after:
                    take = take.copy()
                    take[:, -k:] *= np.linspace(1.0, 0.0, k, dtype=F32)
                buf[:, idx] += take
                self.dirty[self.rec_track] += 1
            self._fade_in = False
            if self._stop_after:
                self.recording = self._stop_after = False
        self.pos = (self.pos + rate * n) % length
        return {"out": out}

    # -- persistence --------------------------------------------------
    def state(self) -> dict:
        return {"length": self.length, "tape_bpm": self.tape_bpm, "tape_sr": self.tape_sr,
                "selected": self.selected, "mute": list(self.mute),
                "tracks": [t is not None for t in self.tape]}

    def load_state(self, data: dict) -> None:
        self.selected = int(data.get("selected", 0)) % TRACKS
        self.mute = [bool(m) for m in (list(data.get("mute", [])) + [False] * TRACKS)[:TRACKS]]
        self._saved = data      # audio arrives separately through load_assets

    def save_assets(self, folder: Path) -> None:
        for t, buf in enumerate(self.tape):
            path = folder / f"{self.uid}-t{t + 1}.wav"
            if buf is not None and float(np.abs(buf).max()) > 0.0:
                write_wav(path, buf, int(self.tape_sr))
            elif path.exists():
                path.unlink()

    def load_assets(self, folder: Path) -> None:
        from pedalboard.io import AudioFile

        data = getattr(self, "_saved", None) or {}
        length = int(data.get("length", 0))
        if length <= 0:
            return
        tape = [None] * TRACKS
        for t in range(TRACKS):
            path = folder / f"{self.uid}-t{t + 1}.wav"
            if not path.exists():
                continue
            try:
                with AudioFile(str(path)) as f:
                    audio = f.read(f.frames)
            except Exception:
                continue
            buf = np.zeros((2, length), dtype=F32)
            k = min(length, audio.shape[1])
            buf[:, :k] = audio[:2, :k] if audio.shape[0] >= 2 else audio[:1, :k]
            tape[t] = buf
        if any(t is not None for t in tape):
            self.tape = tape
            self.length = length
            self.tape_bpm = float(data.get("tape_bpm", 120.0))
            self.tape_sr = float(data.get("tape_sr", self.sr))
            self.dirty = [d + 1 for d in self.dirty]
