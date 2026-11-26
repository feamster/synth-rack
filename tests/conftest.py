import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep imported samples, racks and the session out of the repository and the user's home.
os.environ.setdefault("SYNTHRACK_HOME", tempfile.mkdtemp(prefix="synthrack-test-"))

SR = 48000


def make_engine(modules, cables, bpm=120.0, play=True):
    """An offline engine with ``modules`` patched by ``cables``; ids are assigned from the type."""
    from synthrack.dsp import MainOut
    from synthrack.engine import AudioEngine
    from synthrack.racks import new_uid

    modules = list(modules)
    if not any(isinstance(m, MainOut) for m in modules):
        modules.append(MainOut(SR))
    for m in modules:
        if not m.uid:
            m.uid = new_uid(m.TYPE, [x.uid for x in modules])
    engine = AudioEngine(SR)
    engine.set_patch(modules, cables)
    engine.transport.bpm = bpm
    if play:
        engine.transport.play()
    return engine


@pytest.fixture
def engine_for():
    return make_engine
