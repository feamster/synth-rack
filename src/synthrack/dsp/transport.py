"""The rack's shared clock.

The transport runs on the audio thread. Each block it hands every module a
``Clock`` listing the 16th-note steps that start inside the block and the
sample offset of each, so sequencers can be sample-accurate.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

BPM_MIN, BPM_MAX = 40.0, 220.0
SWING_MAX = 0.7


@dataclass(frozen=True)
class Clock:
    n: int                   # samples in this block
    sr: float
    bpm: float
    sps: float               # samples per 16th-note step
    playing: bool
    events: tuple = ()       # ((sample offset, step number), ...) for steps starting in this block
    started: bool = False    # the transport started at the top of this block
    stopped: bool = False    # ... or stopped
    step_pos: float = 0.0    # position in steps at the top of the block


class Transport:
    def __init__(self):
        self.bpm = 120.0
        self.swing = 0.0         # 0 .. SWING_MAX; delays every other 16th
        self.playing = False
        self.step_pos = 0.0
        self.step = -1           # last step that fired, for displays
        self._commands: deque = deque()
        self._sps = 0.0
        self._anchor = 0.0       # step position at which the current tempo took over
        self._samples = 0        # samples played since then

    def play(self) -> None:
        self._commands.append("play")

    def stop(self) -> None:
        self._commands.append("stop")

    def toggle(self) -> None:
        self._commands.append("toggle")

    def advance(self, n: int, sr: float) -> Clock:
        started = stopped = False
        while self._commands:
            cmd = self._commands.popleft()
            want = (not self.playing) if cmd == "toggle" else cmd == "play"
            if want and not self.playing:
                self.playing, started, self.step_pos = True, True, 0.0
            elif not want and self.playing:
                self.playing, stopped, self.step = False, True, -1
        bpm = min(BPM_MAX, max(BPM_MIN, float(self.bpm)))
        sps = sr * 60.0 / bpm / 4.0
        if started or sps != self._sps:      # count whole samples from here, so steps cannot drift
            self._sps, self._anchor, self._samples = sps, self.step_pos, 0
        start = self.step_pos
        if not self.playing:
            return Clock(n, sr, bpm, sps, False, (), started, stopped, start)
        late = 0.5 * min(SWING_MAX, max(0.0, self.swing))
        done = self._samples
        events = []
        for k in range(max(0, int(math.floor(start)) - 1), int(math.floor(start + n / sps)) + 2):
            at = k + (late if k & 1 else 0.0)
            off = int(math.ceil((at - self._anchor) * sps - 1e-6)) - done
            if 0 <= off < n:
                events.append((off, k))
                self.step = k
        self._samples = done + n
        self.step_pos = self._anchor + self._samples / sps
        return Clock(n, sr, bpm, sps, True, tuple(events), started, stopped, start)
