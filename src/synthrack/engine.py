"""Real-time audio engine: transport -> patched modules -> soft clip -> output."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .dsp.core import F32, Ramp, db_to_lin
from .dsp.transport import Transport
from .dsp.utility import LineIn, MainOut

try:  # the engine still works offline (tests, rendering) without PortAudio
    import sounddevice as sd
except Exception:  # pragma: no cover - depends on the machine
    sd = None

SAMPLE_RATES = (44100, 48000, 96000)
BLOCK_SIZES = (64, 128, 256, 512, 1024)
MAX_RECORD_SECONDS = 1800.0


@dataclass
class AudioConfig:
    input_device: str | None = None   # None -> system default
    output_device: str | None = None
    input_channel: int = 1            # 1-based hardware input Line In listens to
    sample_rate: int = 0              # 0 -> whatever rate the device is running at
    block_size: int = 256

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AudioConfig:
        cfg = cls()
        for key, value in (data or {}).items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        if cfg.sample_rate not in (0, *SAMPLE_RATES):
            cfg.sample_rate = 0
        if cfg.block_size not in BLOCK_SIZES:
            cfg.block_size = 256
        cfg.input_channel = max(1, int(cfg.input_channel or 1))
        return cfg


def soft_clip(y: np.ndarray, knee: float = 0.7) -> np.ndarray:
    """Output safety: transparent below the knee, rounds off into +/-1 above."""
    mag = np.abs(y)
    if not mag.size or float(mag.max()) <= knee:
        return y
    over = knee + (1.0 - knee) * np.tanh((mag - knee) / (1.0 - knee))
    return np.where(mag > knee, np.sign(y) * over, y).astype(F32)


def list_devices() -> tuple[list[dict], list[dict]]:
    """(inputs, outputs) as dicts with name / channels / default flag."""
    if sd is None:
        return [], []
    try:
        devices = sd.query_devices()
        default_in, default_out = sd.default.device
    except Exception:
        return [], []
    ins, outs = [], []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            ins.append({"name": dev["name"], "channels": dev["max_input_channels"],
                        "default": i == default_in})
        if dev["max_output_channels"] > 0:
            outs.append({"name": dev["name"], "channels": dev["max_output_channels"],
                         "default": i == default_out})
    return ins, outs


def _device_index(name: str | None, want_input: bool) -> int | None:
    """Resolve a saved device name; None means 'use the system default'."""
    if not name or sd is None:
        return None
    key = "max_input_channels" if want_input else "max_output_channels"
    for i, dev in enumerate(sd.query_devices()):
        if dev["name"] == name and dev[key] > 0:
            return i
    return None


# -- the patch ----------------------------------------------------------------
def valid_cables(modules, cables) -> list:
    """Cables whose ends exist, without duplicates, as (src, out jack, dst, in jack)."""
    by_id = {m.uid: m for m in modules}
    seen, good = set(), []
    for cable in cables:
        cable = tuple(cable)
        if len(cable) != 4 or cable in seen:
            continue
        src, out_jack, dst, in_jack = cable
        if src in by_id and dst in by_id and out_jack in by_id[src].OUTPUTS and in_jack in by_id[dst].INPUTS:
            seen.add(cable)
            good.append(cable)
    return good


def would_loop(cables, src: str, dst: str) -> bool:
    """Would a cable from module ``src`` to module ``dst`` close a feedback loop?"""
    if src == dst:
        return True
    feeds: dict = {}
    for a, _, b, _ in cables:
        feeds.setdefault(a, set()).add(b)
    stack, seen = [dst], set()
    while stack:
        node = stack.pop()
        if node == src:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(feeds.get(node, ()))
    return False


def build_plan(modules, cables) -> tuple:
    """Modules in dependency order, each with its input wiring."""
    cables = valid_cables(modules, cables)
    needs = {m.uid: {c[0] for c in cables if c[2] == m.uid} for m in modules}
    order, placed, waiting = [], set(), list(modules)
    while waiting:
        ready = [m for m in waiting if needs[m.uid] <= placed]
        if not ready:           # a loop slipped in: run the rest in rack order, one block late
            ready = waiting[:1]
        for m in ready:
            order.append(m)
            placed.add(m.uid)
            waiting.remove(m)
    plan = []
    for m in order:
        wiring = {}
        for src, out_jack, dst, in_jack in cables:
            if dst == m.uid:
                wiring.setdefault(in_jack, []).append((src, out_jack))
        plan.append((m, tuple((jack, tuple(sources)) for jack, sources in wiring.items())))
    return tuple(plan)


class AudioEngine:
    def __init__(self, sample_rate: int = 48000):
        self.sr = int(sample_rate)
        self.config = AudioConfig()
        self.transport = Transport()
        self.modules: tuple = ()
        self.cables: tuple = ()
        self.plan: tuple = ()          # replaced atomically; read by the audio thread
        self.main: MainOut | None = None
        self.line_ins: tuple = ()
        self.wants_input = False
        self.master_db = 0.0
        self.in_peak = 0.0             # block peaks; the UI reads and clears them
        self.out_peak = 0.0
        self.last_error: str | None = None
        self.xruns = 0
        self.recording = False
        self._takes: list = []
        self._stream = None
        self._stream_live = False
        self._live_channel = 0
        self._out_gain = Ramp()

    # -- patch --------------------------------------------------------
    def set_patch(self, modules, cables) -> None:
        modules = tuple(modules)
        for module in modules:
            module.set_sample_rate(self.sr)
        cables = tuple(valid_cables(modules, cables))
        plan = build_plan(modules, cables)
        self.main = next((m for m in modules if isinstance(m, MainOut)), None)
        patched = {c[0] for c in cables}
        self.line_ins = tuple(m for m in modules if isinstance(m, LineIn) and m.uid in patched)
        self.wants_input = bool(self.line_ins)
        self.modules, self.cables, self.plan = modules, cables, plan

    def set_sample_rate(self, sr: int) -> None:
        self.sr = int(sr)
        for module in self.modules:
            module.set_sample_rate(self.sr)

    # -- processing (also used offline) -----------------------------
    def process_block(self, n: int, live: np.ndarray | None = None) -> np.ndarray:
        """Run one block. ``live`` is the hardware input, shaped ``(2, n)``."""
        clock = self.transport.advance(n, self.sr)
        if live is not None:
            self.in_peak = max(self.in_peak, float(np.abs(live).max()) if n else 0.0)
        for module in self.line_ins:
            module.feed = live
        main = self.main
        outs: dict = {}
        for module, wiring in self.plan:
            ins = {}
            for jack, sources in wiring:
                buf = None
                for uid, out_jack in sources:
                    block = outs.get(uid, {}).get(out_jack)
                    if block is not None:
                        buf = block if buf is None else buf + block
                ins[jack] = buf
            try:
                outs[module.uid] = module.process(ins, clock) or {}
            except Exception as exc:   # one broken module must not silence the rack
                self.last_error = f"{module.NAME}: {type(exc).__name__}: {exc}"
                outs[module.uid] = {}
        mix = main.mix if main is not None else None
        if mix is None:
            y = np.zeros((2, n), dtype=F32)
            self._out_gain.block(db_to_lin(self.master_db), n)
        else:
            main.mix = None
            y = np.asarray(mix, dtype=F32) * self._out_gain.block(db_to_lin(self.master_db), n)
            y = soft_clip(np.nan_to_num(y, copy=False))
            left, right = float(np.abs(y[0]).max()), float(np.abs(y[1]).max())
            self.out_peak = max(self.out_peak, left, right)
            main.peaks = [max(main.peaks[0], left), max(main.peaks[1], right)]
            main.scope = y
        if self.recording:
            self._takes.append(y.copy())
            if len(self._takes) * n > MAX_RECORD_SECONDS * self.sr:
                self.recording = False
        return y

    def render(self, seconds: float, block: int = 256) -> np.ndarray:
        """Offline: run the rack for ``seconds`` and return the stereo output."""
        total = int(seconds * self.sr)
        out = np.zeros((2, total), dtype=F32)
        for s in range(0, total, block):
            n = min(block, total - s)
            out[:, s:s + n] = self.process_block(n)
        return out

    # -- master recorder ---------------------------------------------
    def start_recording(self) -> None:
        self._takes = []
        self.recording = True

    def stop_recording(self) -> np.ndarray | None:
        self.recording = False
        takes, self._takes = self._takes, []
        return np.concatenate(takes, axis=1) if takes else None

    def recorded_seconds(self) -> float:
        takes = self._takes
        return sum(t.shape[1] for t in takes) / self.sr if takes else 0.0

    # -- stream -------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._stream is not None

    @property
    def stream_matches_patch(self) -> bool:
        """False when Line In was (un)patched since the stream was opened."""
        return self._stream is None or self._stream_live == self.wants_input

    @property
    def cpu_load(self) -> float:
        try:
            return float(self._stream.cpu_load) if self._stream else 0.0
        except Exception:
            return 0.0

    @property
    def latency_ms(self) -> float:
        if not self._stream:
            return 0.0
        lat = self._stream.latency
        total = sum(lat) if isinstance(lat, (tuple, list)) else lat
        return 1000.0 * float(total)

    def start(self, config: AudioConfig | None = None) -> None:
        if sd is None:
            raise RuntimeError("sounddevice / PortAudio is not available")
        self.stop()
        if config is not None:
            self.config = config
        cfg = self.config
        self.last_error = None
        self.xruns = 0
        live = self.wants_input
        out_dev = _device_index(cfg.output_device, want_input=False)
        in_dev = _device_index(cfg.input_device, want_input=True) if live else None
        # Running at the device's own rate avoids a resampler.
        native = sd.query_devices(out_dev, "output")
        self.set_sample_rate(cfg.sample_rate or int(native["default_samplerate"]))
        # "low" latency asks for the device default, which is far from low on
        # many interfaces; ask for one buffer's worth instead.
        common = {"samplerate": self.sr, "blocksize": cfg.block_size, "dtype": "float32",
                  "latency": cfg.block_size / self.sr}
        if live:
            info = sd.query_devices(in_dev, "input")
            channel = min(cfg.input_channel, int(info["max_input_channels"]))
            if channel < 1:
                raise RuntimeError(f"'{info['name']}' has no input channels")
            self._live_channel = channel - 1
            stream = sd.Stream(device=(in_dev, out_dev), channels=(channel, 2),
                               callback=self._duplex_callback, **common)
        else:
            stream = sd.OutputStream(device=out_dev, channels=2,
                                     callback=self._output_callback, **common)
        stream.start()
        self._stream, self._stream_live = stream, live

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self.in_peak = self.out_peak = 0.0

    def _emit(self, frames: int, live, outdata) -> None:
        try:
            y = self.process_block(frames, live)
            outdata[:, 0] = y[0]
            outdata[:, 1] = y[1]
        except Exception as exc:  # never let an exception kill the stream
            self.last_error = f"{type(exc).__name__}: {exc}"
            outdata[:] = 0.0

    def _duplex_callback(self, indata, outdata, frames, time, status) -> None:
        if status:
            self.xruns += 1
        mono = indata[:, self._live_channel]
        self._emit(frames, np.stack([mono, mono]).astype(F32), outdata)

    def _output_callback(self, outdata, frames, time, status) -> None:
        if status:
            self.xruns += 1
        self._emit(frames, None, outdata)
