"""The sample library: a synthesised factory set plus audio files on disk.

Factory sounds are built from sine sweeps, FM and filtered noise the first
time they are asked for - there are no audio assets in the repository. Sample
files live with the music (``~/Dropbox/Synth Rack/Samples`` by default), in
packs, and are decoded on first use. Samples are mono and keep their own
sample rate; voices compensate when they play them.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

import numpy as np

F32 = np.float32
FACTORY_SR = 48000
MAX_SECONDS = 30.0
AUDIO_SUFFIXES = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a")
REPO_SAMPLES = Path(__file__).resolve().parents[3] / "samples"     # where samples used to live


def music_dir() -> Path:
    """Where audio lives (samples, takes, tape): Dropbox if this machine has
    one, so it is backed up and on every Mac, else ~/Music. None of it belongs
    in a git repository. ``SYNTHRACK_HOME`` moves it, for tests and scripts."""
    if "SYNTHRACK_HOME" in os.environ:
        return Path(os.environ["SYNTHRACK_HOME"])
    dropbox = Path.home() / "Dropbox"
    return (dropbox if dropbox.is_dir() else Path.home() / "Music") / "Synth Rack"


def samples_dir() -> Path:
    return music_dir() / ("samples" if "SYNTHRACK_HOME" in os.environ else "Samples")


class Sample:
    def __init__(self, name: str, data: np.ndarray, sr: int, factory: bool = False):
        self.name = name
        self.data = np.ascontiguousarray(data, dtype=F32)
        self.sr = int(sr)
        self.factory = factory
        self._peaks: dict = {}

    @property
    def seconds(self) -> float:
        return len(self.data) / self.sr

    def peaks(self, width: int) -> np.ndarray:
        """``width`` peak magnitudes across the sample, for waveform displays."""
        if width not in self._peaks:
            n = len(self.data)
            edges = np.linspace(0, n, width + 1).astype(int)
            mag = np.abs(self.data)
            self._peaks[width] = np.array([mag[a:max(b, a + 1)].max() if a < n else 0.0
                                           for a, b in zip(edges[:-1], edges[1:])])
        return self._peaks[width]


# -- synthesis helpers ------------------------------------------------------
def band(x, sr, lo, hi):
    spectrum = np.fft.rfft(x)
    f = np.maximum(np.fft.rfftfreq(len(x), 1.0 / sr), 1e-6)
    shape = 1.0 / np.sqrt(1.0 + (lo / f) ** 6) / np.sqrt(1.0 + (f / hi) ** 6)
    return np.fft.irfft(spectrum * shape, len(x))


def _env(n, sr, decay, attack=0.0008):
    t = np.arange(n) / sr
    return np.minimum(1.0, t / attack) * np.exp(-t * decay)


def _sweep(n, sr, f_start, f_end, rate):
    t = np.arange(n) / sr
    freq = f_end + (f_start - f_end) * np.exp(-t * rate)
    return np.sin(2 * np.pi * np.cumsum(freq) / sr)


def _tone(n, sr, freq):
    return np.sin(2 * np.pi * freq * np.arange(n) / sr)


def _sawtone(n, sr, freq, harmonics=40):
    t = np.arange(n) / sr
    out = np.zeros(n)
    for h in range(1, harmonics + 1):
        if h * freq < sr * 0.45:
            out += np.sin(2 * np.pi * h * freq * t) / h
    return out


def _finish(x, level, tail=256):
    x = np.asarray(x, dtype=np.float64)
    x = x / max(1e-9, np.abs(x).max()) * level
    tail = min(len(x), tail)
    x[-tail:] *= np.linspace(1.0, 0.0, tail)
    return x.astype(F32)


def _build_factory() -> dict:
    sr = FACTORY_SR
    rng = np.random.default_rng(1234)

    def n(seconds):
        return int(seconds * sr)

    def noise(count):
        return rng.standard_normal(count)

    def lofi(x):
        dull = np.tanh(2.0 * band(np.asarray(x, dtype=np.float64), sr, 30, 4200))
        return np.round(dull * 40) / 40

    s = {}
    k = n(0.45)
    s["Kick Round"] = _finish(_sweep(k, sr, 165, 48, 45) * _env(k, sr, 8)
                              + 0.25 * band(noise(k), sr, 1500, 6000) * _env(k, sr, 300), 0.95)
    k = n(0.3)
    s["Kick Punch"] = _finish(np.tanh(2.2 * _sweep(k, sr, 260, 58, 60) * _env(k, sr, 13))
                              + 0.35 * band(noise(k), sr, 2000, 8000) * _env(k, sr, 400), 0.95)
    k = n(0.9)
    s["Kick Sub"] = _finish(_sweep(k, sr, 120, 40, 20) * _env(k, sr, 4.2), 0.95)
    s["Kick Dusty"] = _finish(lofi(s["Kick Round"]), 0.9)
    k = n(0.28)
    snare = (0.75 * band(noise(k), sr, 400, 9000) * _env(k, sr, 20)
             + 0.45 * _sweep(k, sr, 260, 180, 60) * _env(k, sr, 26))
    s["Snare Tight"] = _finish(snare, 0.8)
    k = n(0.42)
    s["Snare Fat"] = _finish(np.tanh(1.8 * (0.8 * band(noise(k), sr, 250, 7000) * _env(k, sr, 11)
                                            + 0.7 * _sweep(k, sr, 230, 150, 40) * _env(k, sr, 16))), 0.8)
    s["Snare Dusty"] = _finish(lofi(snare), 0.75)
    k = n(0.09)
    s["Rim"] = _finish(0.6 * _tone(k, sr, 1720) * _env(k, sr, 110) + 0.45 * _tone(k, sr, 560)
                       * _env(k, sr, 70) + 0.5 * band(noise(k), sr, 1500, 7000) * _env(k, sr, 450), 0.6)
    k = n(0.32)
    clap = np.zeros(k)
    burst = band(noise(k), sr, 900, 4500)
    for delay in (0.0, 0.011, 0.023):
        d = int(delay * sr)
        clap[d:] += burst[: k - d] * _env(k - d, sr, 180)
    s["Clap"] = _finish(clap + 0.6 * burst * _env(k, sr, 22), 0.75)
    k = n(0.06)
    s["Snap"] = _finish(band(noise(k), sr, 1800, 6000) * _env(k, sr, 120)
                        + 0.4 * _tone(k, sr, 2400) * _env(k, sr, 200), 0.6)
    s["Hat Closed"] = _finish(band(noise(n(0.07)), sr, 7000, 16000) * _env(n(0.07), sr, 75), 0.4)
    s["Hat Tick"] = _finish(band(noise(n(0.03)), sr, 9000, 18000) * _env(n(0.03), sr, 220), 0.35)
    s["Hat Open"] = _finish(band(noise(n(0.5)), sr, 6000, 16000) * _env(n(0.5), sr, 8), 0.4)
    k = n(0.12)
    s["Shaker"] = _finish(band(noise(k), sr, 5000, 12000) * _env(k, sr, 30, attack=0.02), 0.35)
    k = n(0.9)
    s["Ride"] = _finish(band(noise(k), sr, 4500, 14000) * _env(k, sr, 4.5)
                        + 0.45 * (_tone(k, sr, 3150) + _tone(k, sr, 4720)) * _env(k, sr, 7), 0.35)
    s["Crash"] = _finish(band(noise(n(1.8)), sr, 2500, 15000) * _env(n(1.8), sr, 2.8, 0.004), 0.5)
    s["Tom Low"] = _finish(_sweep(n(0.5), sr, 130, 85, 25) * _env(n(0.5), sr, 7.5), 0.8)
    s["Tom High"] = _finish(_sweep(n(0.35), sr, 210, 140, 30) * _env(n(0.35), sr, 9), 0.75)
    k = n(0.3)
    s["Conga"] = _finish(_sweep(k, sr, 330, 262, 80) * _env(k, sr, 14)
                         + 0.2 * band(noise(k), sr, 1000, 5000) * _env(k, sr, 200), 0.7)
    k = n(0.35)
    s["Cowbell"] = _finish(np.sign(_tone(k, sr, 540)) * 0.5 + np.sign(_tone(k, sr, 800)) * 0.5, 1.0)
    s["Cowbell"] = _finish(band(s["Cowbell"], sr, 500, 5000) * _env(k, sr, 12), 0.5)
    s["Clave"] = _finish(_tone(n(0.08), sr, 2500) * _env(n(0.08), sr, 60), 0.55)
    s["Blip"] = _finish(_sweep(n(0.12), sr, 1800, 600, 50) * _env(n(0.12), sr, 30), 0.5)

    # tonal one-shots, all rooted on C so they play in key from the keyboard
    k = n(0.9)
    bass = band(_sawtone(k, sr, 65.41), sr, 20, 900) + 0.6 * _tone(k, sr, 65.41)
    s["Bass Pluck"] = _finish(bass * _env(k, sr, 4.5, 0.002), 0.85)
    k = n(1.2)
    s["Sub Drop"] = _finish(_sweep(k, sr, 110, 32.7, 3.0) * _env(k, sr, 2.2, 0.005), 0.9)
    k = n(1.1)
    stab = sum(_sawtone(k, sr, f * d, 24) for f in (261.63, 311.13, 392.0, 466.16) for d in (0.996, 1.004))
    s["Stab Minor"] = _finish(band(stab, sr, 120, 3200) * _env(k, sr, 3.6, 0.003), 0.7)
    k = n(1.8)
    t = np.arange(k) / sr
    w = 2 * np.pi * 523.25
    s["Bell"] = _finish(np.sin(w * t + 3.2 * np.exp(-t * 3) * np.sin(w * 3.5 * t))
                        * _env(k, sr, 2.4, 0.001), 0.6)
    k = n(1.4)
    t = np.arange(k) / sr
    w = 2 * np.pi * 261.63
    s["Keys"] = _finish(np.sin(w * t + 1.6 * np.exp(-t * 6) * np.sin(w * t)) * _env(k, sr, 2.6, 0.002)
                        + 0.15 * np.sin(w * 14 * t) * _env(k, sr, 40), 0.7)
    k = n(1.3)
    src = _sawtone(k, sr, 130.81, 60) * (1 + 0.012 * np.sin(2 * np.pi * 5.2 * np.arange(k) / sr))
    vox = sum(g * band(src, sr, f * 0.9, f * 1.1) for f, g in ((700, 1.0), (1150, 0.6), (2600, 0.3)))
    s["Vox Ah"] = _finish(vox * _env(k, sr, 1.6, 0.06), 0.7, tail=4000)
    k = n(2.0)
    ramp = np.arange(k) / k
    s["Noise Rise"] = _finish(band(noise(k), sr, 300, 9000) * ramp ** 2
                              * (0.6 + 0.4 * np.sin(2 * np.pi * (2 + 10 * ramp) * ramp)), 0.5, tail=600)
    k = n(2.0)
    crackle = np.where(rng.random(k) < 0.0009, rng.standard_normal(k) * 6, 0.0)
    s["Vinyl"] = _finish(band(crackle, sr, 800, 9000) + 0.05 * band(noise(k), sr, 200, 5000), 0.3, tail=32)
    return s


FACTORY_NAMES = (
    "Kick Round", "Kick Punch", "Kick Sub", "Kick Dusty", "Snare Tight", "Snare Fat", "Snare Dusty",
    "Rim", "Clap", "Snap", "Hat Closed", "Hat Tick", "Hat Open", "Shaker", "Ride", "Crash",
    "Tom Low", "Tom High", "Conga", "Cowbell", "Clave", "Blip", "Bass Pluck", "Sub Drop",
    "Stab Minor", "Bell", "Keys", "Vox Ah", "Noise Rise", "Vinyl",
)


def decode_file(path: Path) -> tuple[np.ndarray, int]:
    """Read (up to ``MAX_SECONDS`` of) an audio file as mono."""
    from pedalboard.io import AudioFile

    with AudioFile(str(path)) as f:
        frames = int(min(f.frames, MAX_SECONDS * f.samplerate))
        audio = f.read(frames)
        sr = int(f.samplerate)
    mono = audio.mean(axis=0) if audio.ndim == 2 else audio
    if len(mono) < 2:
        raise ValueError("audio file is empty")
    return mono.astype(F32), sr


def write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    """Write mono ``(n,)`` or stereo ``(2, n)`` float audio as 24-bit WAV."""
    from pedalboard.io import AudioFile

    audio = np.atleast_2d(np.asarray(audio, dtype=F32))
    path.parent.mkdir(parents=True, exist_ok=True)
    with AudioFile(str(path), "w", samplerate=int(sr), num_channels=audio.shape[0], bit_depth=24) as f:
        f.write(audio)


BUILT_IN = "Built in"        # the synthesised sounds
LOOSE = "My Sounds"          # files at the top of a sample folder; a subfolder is a pack
MAX_FILES = 50000            # stop scanning a runaway folder


def pack_of(name: str) -> str:
    """The pack a sample name belongs to: ``"808 Kit/Kick 1"`` -> ``"808 Kit"``."""
    if "/" in name:
        return name.rsplit("/", 1)[0]
    return BUILT_IN if name in FACTORY_NAMES else LOOSE


def leaf(name: str) -> str:
    """A sample name without its pack, for small displays."""
    return name.rsplit("/", 1)[-1]


class Library:
    """Every sound a module can play: the built-in ones, then audio files in
    the sample folders. A file is named by its path inside its folder without
    the extension, so ``Samples/808 Kit/Kick 1.wav`` is ``"808 Kit/Kick 1"``:
    subfolders are packs, and a rack that names a sample finds it on any Mac."""

    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder) if folder else None
        self.extra: list = []            # more folders to look in, after the main one
        self.save_to: Path | None = None  # where imports and recordings go; None = the main one
        self._factory: dict | None = None
        self._user: dict = {}
        self._scan: dict | None = None   # name -> path, from the last look at the disk
        self._stamps: dict = {}          # folder -> mtime when it was scanned
        self._roots: list = []

    @property
    def root(self) -> Path:
        """The main sample folder (``Samples`` with the music, see ``samples_dir``)."""
        return self.folder or samples_dir()

    def folders(self) -> list:
        """Every folder searched, in order. The first one holding a name wins."""
        seen, out = set(), []
        for folder in (self.root, *self.extra):
            key = str(Path(folder).expanduser())
            if key not in seen:
                seen.add(key)
                out.append(Path(key))
        return out

    @property
    def write_root(self) -> Path:
        """Where new samples are written."""
        if self.save_to is not None and Path(self.save_to).expanduser() in self.folders():
            return Path(self.save_to).expanduser()
        return self.root

    def configure(self, extra=(), save_to=None) -> None:
        self.extra = [Path(p).expanduser() for p in extra]
        self.save_to = Path(save_to).expanduser() if save_to else None
        self.refresh()

    def refresh(self) -> None:
        """Forget what is on disk; names may now resolve to different files."""
        self._scan = None
        self._user = {}

    def _stale(self) -> bool:
        """Has any scanned folder gained, lost or renamed an entry since the scan?"""
        if self._roots != [str(f) for f in self.folders()]:
            return True
        for folder, stamp in self._stamps.items():
            try:
                now = os.stat(folder).st_mtime_ns
            except OSError:
                now = None
            if now != stamp:
                return True
        return False

    def _files(self) -> dict:
        """Sample name -> file, across every folder and its subfolders."""
        if self._scan is not None and not self._stale():
            return self._scan
        files: dict = {}
        stamps: dict = {}
        for root in self.folders():
            try:
                stamps[str(root)] = os.stat(root).st_mtime_ns
            except OSError:
                stamps[str(root)] = None          # not there (yet); notice when it appears
                continue
            for folder, dirs, names in os.walk(root):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                try:
                    stamps[folder] = os.stat(folder).st_mtime_ns
                except OSError:
                    continue
                pack = Path(folder).relative_to(root).as_posix()
                for filename in sorted(names):
                    stem, suffix = os.path.splitext(filename)
                    if suffix.lower() not in AUDIO_SUFFIXES or filename.startswith("."):
                        continue
                    name = stem if pack == "." else f"{pack}/{stem}"
                    if name not in FACTORY_NAMES:
                        files.setdefault(name, Path(folder) / filename)
                if len(files) >= MAX_FILES:
                    break
        self._user = {k: v for k, v in self._user.items() if k in files}
        self._scan, self._stamps, self._roots = files, stamps, [str(f) for f in self.folders()]
        return files

    def groups(self) -> dict:
        """Pack name -> sample names, built-in sounds first, then loose files, then packs."""
        out: dict = {BUILT_IN: list(FACTORY_NAMES)}
        loose, packs = [], {}
        for name in self._files():
            if "/" in name:
                packs.setdefault(pack_of(name), []).append(name)
            else:
                loose.append(name)
        if loose:
            out[LOOSE] = loose
        for pack in sorted(packs, key=str.lower):
            out[pack] = packs[pack]
        return out

    def siblings(self, name: str) -> list[str]:
        """The sounds in the same pack as ``name``: what stepping through sounds moves across."""
        if name in FACTORY_NAMES:
            return list(FACTORY_NAMES)
        pack = pack_of(name)
        return [n for n in self._files() if pack_of(n) == pack] or list(FACTORY_NAMES)

    def import_pack(self, folder: str | Path) -> tuple[str, int]:
        """Copy a folder of audio (and its subfolders) into the library as a
        pack. Returns the pack's name and how many files were copied."""
        folder = Path(folder)
        base = re.sub(r"[^\w\- ]+", "", folder.name).strip() or "Pack"
        name, i = base, 2
        while (self.write_root / name).exists():
            name, i = f"{base} {i}", i + 1
        copied = 0
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() in AUDIO_SUFFIXES and path.is_file() \
                    and not any(part.startswith(".") for part in path.relative_to(folder).parts):
                target = self.write_root / name / path.relative_to(folder)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                copied += 1
        if not copied:
            raise ValueError(f"no audio files in {folder.name}")
        self.refresh()
        return name, copied

    def user_names(self) -> list[str]:
        return list(self._files())

    def names(self) -> list[str]:
        return [*FACTORY_NAMES, *self.user_names()]

    def get(self, name: str) -> Sample | None:
        if name in FACTORY_NAMES:
            if self._factory is None:
                self._factory = {k: Sample(k, v, FACTORY_SR, True) for k, v in _build_factory().items()}
            return self._factory[name]
        if name not in self._user:
            path = self._files().get(name)
            if path is None:
                return None
            try:
                data, sr = decode_file(path)
            except Exception:
                return None
            self._user[name] = Sample(name, data, sr)
        return self._user[name]

    def _free_name(self, stem: str) -> str:
        stem = re.sub(r"[^\w\- ]+", "", stem).strip() or "sample"
        taken = set(self.names())
        name, i = stem, 2
        while name in taken:
            name, i = f"{stem} {i}", i + 1
        return name

    def import_file(self, path: str | Path) -> str:
        """Copy an audio file into the library and return its sample name."""
        path = Path(path)
        decode_file(path)                      # raises if it is not audio we can read
        for name, known in self._files().items():
            if known.resolve() == path.resolve():
                return name                    # already in a folder we search
        existing = self._files().get(path.stem)
        if existing is not None and existing.stat().st_size == path.stat().st_size:
            return path.stem                   # already imported
        name = self._free_name(path.stem)
        self.write_root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, self.write_root / f"{name}{path.suffix.lower()}")
        self._scan = None
        return name

    def is_user(self, name: str) -> bool:
        return name in self._files()

    def path_of(self, name: str) -> Path | None:
        return self._files().get(name)

    def rename(self, old: str, new: str) -> str:
        """Rename a sample's file, keeping it in its pack. Returns the name it ended up with."""
        path = self._files().get(old)
        if path is None:
            raise ValueError(f"'{leaf(old)}' is not a sample file")
        new = re.sub(r"[^\w\- ]+", "", leaf(new)).strip()
        if not new:
            raise ValueError("a sample needs a name")
        full = f"{old.rsplit('/', 1)[0]}/{new}" if "/" in old else new
        if full == old:
            return old
        if full in self.names():
            raise ValueError(f"there is already a sample called '{new}'")
        path.rename(path.with_name(f"{new}{path.suffix}"))
        sample = self._user.pop(old, None)
        self._scan = None
        if sample is not None:
            sample.name = full
            self._user[full] = sample
        return full

    def delete(self, name: str, remover=None) -> None:
        """Remove an imported sample. ``remover(path)`` can move it to the Trash
        instead of unlinking it; it returns False if it could not."""
        path = self._files().get(name)
        if path is None:
            raise ValueError(f"'{name}' is not a sample file")
        if remover is None or not remover(path):
            path.unlink()
        self._scan = None
        self._user.pop(name, None)

    def add_recording(self, data: np.ndarray, sr: int, prefix: str = "rec") -> str:
        name = self._free_name(f"{prefix}-{time.strftime('%m%d-%H%M%S')}")
        peak = float(np.abs(data).max()) if len(data) else 0.0
        if peak > 1e-4:
            data = data * min(4.0, 0.9 / peak)
        write_wav(self.write_root / f"{name}.wav", data, sr)
        self._scan = None
        return name


LIBRARY = Library()
