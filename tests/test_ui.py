"""UI behaviour, driven through the same entry points the mouse and keyboard use."""

import numpy as np
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtWidgets import QApplication

from synthrack.racks import RackStore
from synthrack.ui.main_window import MainWindow
from synthrack.ui.theme import MODULE_FINISHES
from synthrack.ui.widgets import Knob


class FakeStream:
    cpu_load = 0.0
    latency = 0.01

    def stop(self):
        pass

    def close(self):
        pass


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    win = MainWindow(RackStore(tmp_path))
    win.engine.start = lambda *a, **k: setattr(win.engine, "_stream", FakeStream())   # no real audio
    win.resize(1440, 900)
    win.show()
    app.processEvents()
    yield win
    win.close()


def types(win):
    return [m.TYPE for m in win.rack.modules()]


def widget(win, type_name):
    return next(w for w in win.rack.widgets if w.module.TYPE == type_name)


def run(win, seconds=0.1):
    return win.engine.render(seconds)


def test_starts_on_the_first_factory_rack_fully_patched(window):
    assert window.rack_name == "First Light"
    assert types(window) == ["knockbox", "forge", "wander", "reel", "afterglow", "summit", "mainout"]
    assert len(window.engine.cables) == 8 and len(window.engine.plan) == 7
    assert not window.engine.running and not window.edited_label.text()
    rows = {w.y() for w in window.rack.widgets}
    assert len(rows) == 2, "the factory rack should sit in two rows at the default width"


def test_space_starts_the_engine_and_the_transport(window):
    window.handle_key(Qt.Key.Key_Space, True)
    assert window.engine.running
    out = run(window, 1.0)
    assert window.engine.transport.playing and float(np.abs(out).max()) > 0.05
    window.handle_key(Qt.Key.Key_Space, True)
    run(window, 0.05)
    assert not window.engine.transport.playing


def test_step_keys_toggle_trigs_and_right_click_locks_knobs(window):
    forge = widget(window, "forge")
    box = forge.module
    forge.select_track(3)
    forge._step_toggled(5)
    assert box.pat.steps[3][5] is not None and window.edited_label.text()
    forge._step_toggled(5)
    assert box.pat.steps[3][5] is None
    forge._step_held(9)                       # holding an empty step creates the trig
    assert forge.held == 9 and box.pat.steps[3][9] is not None
    before = box.tracks[3].values["cutoff"]
    forge.knobs["cutoff"].set_norm(0.3, emit=True)
    assert box.pat.steps[3][9].locks == {"cutoff": pytest.approx(0.3)}
    assert box.tracks[3].values["cutoff"] == before and forge.knobs["cutoff"].locked
    forge.trig_knobs["vel"].set_norm(0.25, emit=True)
    assert box.pat.steps[3][9].vel == pytest.approx(0.25)
    assert forge._knob_reset("cutoff") and box.pat.steps[3][9].locks == {}
    forge.key(Qt.Key.Key_Escape, True, None)
    assert forge.held is None
    forge.knobs["cutoff"].set_norm(0.6, emit=True)
    assert box.tracks[3].values["cutoff"] == pytest.approx(0.6)


def test_number_and_piano_keys_play_the_selected_groovebox(window):
    forge = widget(window, "forge")
    window.rack.select(forge)
    seen = [t.flash for t in forge.module.tracks]
    window.handle_key(Qt.Key.Key_7, True)
    assert forge.module.selected == 6 and window.engine.running
    window.handle_key(Qt.Key.Key_D, True)     # four semitones above the track's root
    run(window)
    assert forge.module.tracks[6].flash == seen[6] + 2
    assert forge.module.tracks[6].voice.note == forge.module.tracks[6].trig["note"] + 4


def test_piano_keys_hold_and_release_wander_notes(window):
    synth = widget(window, "wander")
    window.rack.select(synth)
    window.handle_key(Qt.Key.Key_A, True)
    window.handle_key(Qt.Key.Key_A, True, repeat=True)
    window.handle_key(Qt.Key.Key_G, True)
    run(window)
    assert sorted(synth.module.sounding()) == [60, 67]
    window.handle_key(Qt.Key.Key_A, False)
    window.rack.select(widget(window, "forge"))      # moving focus must not leave G hanging
    run(window)
    assert synth.module.sounding() == []


def test_changing_machine_relabels_knobs_and_keeps_the_pattern(window):
    forge = widget(window, "forge")
    forge.select_track(6)
    steps = list(forge.module.pat.steps[6])
    sounds = forge.module.sounds()
    forge._sound_chosen(sounds.index("Chord"))
    assert forge.module.tracks[6].sound == "Chord" and forge.knobs["color"].label == "Chord"
    assert forge.module.pat.steps[6] == steps


def test_linked_boxes_change_pattern_together(window):
    knock, forge = widget(window, "knockbox"), widget(window, "forge")
    knock._pattern_chosen(1)
    assert knock.module.pattern == 1 and forge.module.pattern == 1
    forge.module.link = False
    knock._pattern_chosen(2)
    assert knock.module.pattern == 2 and forge.module.pattern == 1


def test_cables_patch_unpatch_and_refuse_loops(window):
    rack = window.rack
    wander, glow, reel = (widget(window, t) for t in ("wander", "afterglow", "reel"))
    count = len(rack.cables)
    out, inp = wander.jacks[("out", "out")], glow.jacks[("in", "in")]
    assert rack.connect_jacks(inp, out)                     # either end first
    assert ("wander-1", "out", "afterglow-1", "in") in window.engine.cables
    assert not rack.connect_jacks(out, inp), "the same cable twice"
    assert not rack.connect_jacks(out, reel.jacks[("out", "out")]), "output to output"
    summit, main = widget(window, "summit"), widget(window, "mainout")
    assert not rack.can_connect(summit.jacks[("out", "out")], glow.jacks[("in", "in")]), "feedback loop"
    # picking a cable up off an input and dropping it on nothing removes it
    rack.jack_press(inp, QPointF(inp.mapToGlobal(QPoint(20, 15))))
    rack.jack_release(QPointF(rack.mapToGlobal(QPoint(5, 5))))
    assert len(rack.cables) == count + 1 - 2 + 1 or len(rack.cables) == count
    assert ("summit-1", "out", "mainout-1", "in") in rack.cables and main.module.REMOVABLE is False


def test_modules_can_be_added_reordered_and_removed_but_not_main_out(window):
    rack = window.rack
    added = rack.add_module("linein")
    assert added.module.uid == "linein-1" and not window.engine.wants_input
    rack.connect_jacks(added.jacks[("out", "out")], widget(window, "summit").jacks[("in", "in1")])
    assert window.engine.wants_input
    first = rack.widgets[0]
    start = QPointF(first.mapToGlobal(QPoint(300, 12)))
    rack.begin_drag(first, start)
    for i in range(1, 11):
        rack.drag_to(first, start + QPointF(90 * i, 0))
    rack.end_drag(first)
    assert types(window)[:2] == ["forge", "knockbox"]
    rack.remove(added)
    assert "linein" not in types(window) and not window.engine.wants_input
    assert all("linein-1" not in (c[0], c[2]) for c in rack.cables)
    rack.remove(widget(window, "mainout"))
    assert "mainout" in types(window)


def test_knockbox_loads_a_file_onto_the_selected_track(window, tmp_path):
    from synthrack.dsp.library import write_wav

    path = tmp_path / "Field Recording.wav"
    write_wav(path, 0.4 * np.sin(np.arange(9600) * 0.1), 48000)
    knock = widget(window, "knockbox")
    knock.select_track(5)
    assert knock.import_file(str(path))
    assert knock.module.tracks[5].sound == "Field Recording"
    assert "Field Recording" in knock.f_sound.choices
    assert not knock.import_file(str(tmp_path / "nope.wav"))


def test_reel_record_starts_the_transport_and_fills_the_tape(window):
    reel = widget(window, "reel")
    forge = widget(window, "forge")
    window.rack.connect_jacks(forge.jacks[("out", "out")], reel.jacks[("in", "in")])
    window.rack.select(reel)
    window.handle_key(Qt.Key.Key_2, True)
    window.handle_key(Qt.Key.Key_R, True)
    run(window, 1.0)
    assert window.engine.transport.playing and reel.module.recording and reel.module.selected == 1
    window.handle_key(Qt.Key.Key_R, True)
    run(window, 0.1)
    assert not reel.module.recording
    assert float(np.abs(reel.module.tape[1]).max()) > 0.01 and reel.module.tape[0] is None


def test_session_brings_back_edits_cables_and_tape(app, tmp_path):
    store = RackStore(tmp_path)
    win = MainWindow(store)
    forge = widget(win, "forge")
    forge.select_track(1)
    forge._step_toggled(3)
    win.rack.connect_jacks(widget(win, "wander").jacks[("out", "out")],
                           widget(win, "afterglow").jacks[("in", "in")])
    reel = widget(win, "reel").module
    reel.arm(104.0)
    reel.tape[reel.selected][:, :500] = 0.2
    win._tempo_changed((97 - 40) / 180)
    win.close()

    again = MainWindow(RackStore(tmp_path))
    box = widget(again, "forge").module
    assert again.edited_label.text() and box.pat.steps[1][3] is not None
    assert ("wander-1", "out", "afterglow-1", "in") in again.rack.cables
    assert again.engine.transport.bpm == 97
    tape = widget(again, "reel").module
    assert tape.length == reel.length and float(tape.tape[0].max()) == pytest.approx(0.2, abs=1e-3)
    again.close()


def test_save_as_makes_a_user_rack_and_factory_racks_stay_put(window, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Road Sketch", True))
    widget(window, "knockbox")._step_toggled(15)
    window._save()                                   # a factory rack: goes through Save As
    assert window.rack_name == "Road Sketch" and window.store.is_user("Road Sketch")
    assert not window.edited_label.text()
    window._load_rack("First Light")
    assert widget(window, "knockbox").module.pat.steps[0][15] is None
    window._load_rack("Road Sketch")
    assert widget(window, "knockbox").module.pat.steps[0][15] is not None


def test_every_factory_rack_and_finish_builds_and_ticks(window):
    for name in window.store.factory_names():
        window._load_rack(name)
        run(window, 0.05)
        window._tick()
    window._load_rack("First Light")
    for w in list(window.rack.widgets):
        for finish in MODULE_FINISHES:
            w.module.finish = finish
            w.rebuild()
        assert any(isinstance(c, Knob) for c in w.controls.values()) or w.module.TYPE == "mainout"
    window.grab()


def test_clicking_any_control_selects_its_module_for_the_keyboard(window, app):
    from PyQt6.QtTest import QTest

    synth = widget(window, "wander")
    assert window.rack.selected is not synth
    QTest.mouseClick(synth.controls["cutoff"], Qt.MouseButton.LeftButton)
    assert window.rack.selected is synth
    window.handle_key(Qt.Key.Key_F, True)
    run(window)
    assert synth.module.sounding() == [65]


def test_renaming_and_deleting_a_sample_follows_through_the_rack_and_saved_racks(window, tmp_path):
    import json

    from synthrack.dsp.library import Library, write_wav

    library = Library(tmp_path / "samples")
    knock, synth = widget(window, "knockbox"), widget(window, "wander")
    knock.module.library = synth.module.library = library
    write_wav(tmp_path / "Clonk.wav", 0.4 * np.sin(np.arange(9600) * 0.1), 48000)
    knock.select_track(2)
    assert knock.import_file(str(tmp_path / "Clonk.wav"))
    synth._sample_chosen(library.names().index("Clonk"))
    window.store.save(window._current_rack("Keeper"), window.rack.modules())

    window.rack.rename_sample("Clonk", library.rename("Clonk", "Door Slam"))
    assert knock.module.tracks[2].sound == "Door Slam" and synth.module.sample_name == "Door Slam"
    assert knock.f_sound.choices[knock.f_sound.index] == "Door Slam"
    saved = json.loads((window.store.racks_dir / "keeper.json").read_text())
    sounds = [t.get("sound") for m in saved["modules"] if m["type"] == "knockbox" for t in m["tracks"]]
    assert "Door Slam" in sounds and "Clonk" not in sounds
    assert "Door Slam" in [m.get("sample") for m in saved["modules"]]

    library.delete("Door Slam")
    window.rack.forget_sample("Door Slam")
    assert knock.module.tracks[2].sound == "Hat Closed" and synth.module.sample_name == "Keys"
    assert "Door Slam" not in knock.f_sound.choices


def test_recordings_go_to_the_chosen_folder_and_the_choice_is_remembered(app, tmp_path, monkeypatch):
    from synthrack import racks

    monkeypatch.delenv("SYNTHRACK_HOME", raising=False)
    monkeypatch.setattr(racks.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert racks.default_recordings_dir() == tmp_path / "home" / "Music" / "Synth Rack"
    (tmp_path / "home" / "Dropbox").mkdir(parents=True)
    assert racks.default_recordings_dir() == tmp_path / "home" / "Dropbox" / "Synth Rack"

    win = MainWindow(RackStore(tmp_path / "state"))
    win.engine.start = lambda *a, **k: setattr(win.engine, "_stream", FakeStream())
    assert racks.recordings_dir() == racks.default_recordings_dir()
    target = tmp_path / "Songs"
    win.set_recordings_folder(target)
    win._play(True)
    win._record(True)
    run(win, 0.6)
    win._record(False)
    takes = list(target.glob("take-*.wav"))
    assert len(takes) == 1 and takes[0].stat().st_size > 50000
    assert not (tmp_path / "home" / "Dropbox" / "Synth Rack").exists(), "nothing lands in the default"
    win.close()

    again = MainWindow(RackStore(tmp_path / "state"))
    assert racks.recordings_dir() == target and "Songs" in again.rec.toolTip()
    again.set_recordings_folder(None)
    again.close()
