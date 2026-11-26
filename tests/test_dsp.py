"""The modules, offline: sequencing, voices, tape, patching."""

import numpy as np
import pytest

from conftest import SR, make_engine
from synthrack.dsp import MODULE_CLASSES, Afterglow, Forge, Knockbox, Reel, Summit, Transport, Wander
from synthrack.dsp.groovebox import Step
from synthrack.dsp.library import FACTORY_NAMES, LIBRARY, Library, write_wav
from synthrack.dsp.machines import MACHINES
from synthrack.dsp.utility import PedalLoop, available_boards
from synthrack.engine import build_plan, would_loop
from synthrack.racks import FACTORY_RACKS, build_rack, rack_tempo

STEP = SR * 60 // 120 // 4      # samples per 16th at 120 bpm


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))))


def box_engine(box, **kw):
    box.uid = box.TYPE + "-1"
    return make_engine([box], [(box.uid, "out", "mainout-1", "in")], **kw)


def empty(box):
    for pattern in box.patterns:
        pattern.steps = [[None] * 64 for _ in range(8)]
    return box


# -- transport ----------------------------------------------------------------
def collect(block, swing=0.0, total=SR):
    t = Transport()
    t.swing = swing
    t.play()
    hits, pos = [], 0
    while pos < total:
        clock = t.advance(block, SR)
        hits += [(pos + off, step) for off, step in clock.events]
        pos += block
    return hits


def test_transport_steps_land_on_the_grid_at_any_buffer_size():
    expected = [(k * STEP, k) for k in range(SR // STEP)]
    for block in (64, 256, 500, 1024):
        assert collect(block)[:len(expected)] == expected


def test_swing_delays_every_other_sixteenth():
    hits = dict((step, at) for at, step in collect(128, swing=0.5))
    assert hits[0] == 0 and hits[2] == 2 * STEP
    assert hits[1] == STEP + STEP // 4 and hits[3] == 3 * STEP + STEP // 4


def test_stopping_and_starting_restarts_from_step_zero():
    t = Transport()
    t.play()
    t.advance(STEP * 3, SR)
    t.stop()
    assert t.advance(256, SR).stopped
    t.play()
    clock = t.advance(256, SR)
    assert clock.started and clock.events == ((0, 0),)


# -- grooveboxes --------------------------------------------------------------
def test_a_trig_sounds_on_its_step_and_not_before():
    box = empty(Knockbox(SR))
    box.set_step(0, 4, Step())
    out = box_engine(box).render(1.0)
    start = 4 * STEP
    assert rms(out[:, :start]) == 0.0
    assert rms(out[:, start:start + 2000]) > 0.05


@pytest.mark.parametrize("cls", [Knockbox, Forge])
def test_groovebox_output_does_not_depend_on_buffer_size(cls):
    def run(block):
        box = empty(cls(SR))
        for t, steps in enumerate(((0, 6, 10), (4, 12), (0, 2, 4, 6, 8, 10, 12, 14))):
            for i in steps:
                box.set_step(t, i, box.new_step(t))
        return box_engine(box).render(1.5, block)

    a, b = run(64), run(512)
    assert rms(a) > 0.02
    assert np.allclose(a, b, atol=2e-3)


def test_a_parameter_lock_changes_only_its_step():
    def run(locks):
        box = empty(Knockbox(SR))
        box.set_step(0, 0, Step())
        box.set_step(0, 4, Step(locks=locks))
        out = box_engine(box).render(1.0)
        return out, box

    plain, _ = run({})
    locked, box = run({"tune": 12.0})
    assert np.allclose(plain[:, :4 * STEP], locked[:, :4 * STEP])
    assert not np.allclose(plain[:, 4 * STEP:6 * STEP], locked[:, 4 * STEP:6 * STEP])
    assert box.tracks[0].values["tune"] == 0.0


def test_probability_zero_never_fires_and_muted_tracks_are_silent():
    box = empty(Knockbox(SR))
    box.set_step(0, 0, Step(prob=0.0))
    box.set_step(1, 0, Step())
    box.tracks[1].mute = True
    assert rms(box_engine(box).render(1.0)) == 0.0


def test_pattern_change_waits_for_the_end_of_the_pattern():
    box = empty(Forge(SR))
    engine = box_engine(box)
    engine.render(0.25)
    box.select_pattern(3)
    assert (box.pattern, box.next_pattern) == (0, 3)
    engine.render(16 * STEP / SR)
    assert (box.pattern, box.next_pattern) == (3, None)
    engine.transport.stop()
    engine.render(0.05)
    box.select_pattern(1)                  # stopped: switches at once
    assert box.pattern == 1


def test_live_record_quantises_what_is_played_into_the_pattern():
    box = empty(Knockbox(SR))
    box.record = True
    engine = box_engine(box)
    engine.render((5 * STEP + STEP // 5) / SR)     # just after step 5
    box.play(2)
    engine.render(0.05)
    assert box.pat.steps[2][5] is not None
    engine.render(STEP / SR)                       # 6.6 steps in: nearer step 7
    box.play(3, note=64)
    engine.render(0.02)
    assert box.pat.steps[3][7].note == 64


def test_dice_fills_only_the_pattern_length_and_melodic_tracks_get_notes():
    box = empty(Forge(SR))
    box.dice(6, seed=3)
    row = box.pat.steps[6]
    assert any(row[:16]) and not any(row[16:])
    assert len({st.note for st in row if st}) > 1
    box.dice(0, seed=3)
    assert {st.note for st in box.pat.steps[0] if st} == {box.tracks[0].trig["note"]}


def test_send_jack_carries_only_tracks_with_send_turned_up():
    box = empty(Knockbox(SR))
    box.set_step(0, 0, Step())
    box.uid = "knockbox-1"
    engine = make_engine([box], [("knockbox-1", "send", "mainout-1", "in")])
    assert rms(engine.render(0.3)) == 0.0
    box.tracks[0].values["send"] = 0.8
    engine.transport.stop()
    engine.render(0.1)
    engine.transport.play()
    assert rms(engine.render(0.3)) > 0.01


def test_knockbox_samples_its_input_jack():
    source, box = empty(Forge(SR)), empty(Knockbox(SR))
    source.set_step(0, 0, source.new_step(0))
    source.uid, box.uid = "forge-1", "knockbox-1"
    engine = make_engine([source, box], [("forge-1", "out", "knockbox-1", "in")])
    box.command("sample", True, 5)
    engine.render(0.4)
    assert box.sampling
    box.command("sample", False, 5)
    engine.render(0.05)
    audio, track = box.take_sampled()
    assert track == 5 and len(audio) > SR * 0.3 and rms(audio) > 0.01
    assert box.take_sampled() is None


@pytest.mark.parametrize("name", list(MACHINES))
def test_every_machine_makes_a_sound_that_ends(name):
    voice = MACHINES[name](SR)
    params = {"tune": 0.0, "decay": 0.5, "color": 0.5, "shape": 0.5, "sweep": 0.5, **voice.DEFAULTS}
    voice.trigger(voice.NOTE, 0.9, params, 0.1)
    chunks = []
    while voice.active and len(chunks) < 1500:
        chunks.append(voice.render(256))
    y = np.concatenate(chunks)
    assert np.all(np.isfinite(y)) and 0.01 < np.abs(y).max() < 4.0
    assert not voice.active, "voice never finished"


# -- wander -------------------------------------------------------------------
@pytest.mark.parametrize("engine_index", range(6))
def test_wander_plays_and_releases(engine_index):
    synth = Wander(SR)
    synth.uid = "wander-1"
    synth.set("engine", engine_index)
    engine = make_engine([synth], [("wander-1", "out", "mainout-1", "in")], play=False)
    for note in (60, 64, 67):
        synth.command("on", note, 0.8)
    held = engine.render(0.5)
    assert np.all(np.isfinite(held)) and 0.005 < rms(held) and np.abs(held).max() < 1.0
    assert sorted(synth.sounding()) == [60, 64, 67]
    for note in (60, 64, 67):
        synth.command("off", note)
    synth.set("release", 0.05)
    engine.render(1.0)
    assert rms(engine.render(0.2)) == 0.0 and synth.sounding() == []


def test_wander_arp_steps_through_held_notes_in_time():
    synth = Wander(SR)
    synth.uid = "wander-1"
    synth.set("arp", 1)          # up
    synth.set("arp_rate", 2)     # 1/16
    engine = make_engine([synth], [("wander-1", "out", "mainout-1", "in")])
    for note in (72, 60, 67):
        synth.command("on", note, 0.8)
    seen = []
    for _ in range(4):
        engine.render(STEP / 2 / SR)
        seen.append(synth.arp_note)          # read mid-step, while the note is still gated
        engine.render(STEP / 2 / SR)
    assert seen == [60, 67, 72, 60]


# -- reel ---------------------------------------------------------------------
def test_reel_records_a_loop_and_plays_it_back():
    source, reel = empty(Forge(SR)), Reel(SR)
    source.set_step(0, 0, source.new_step(0))
    source.uid, reel.uid = "forge-1", "reel-1"
    reel.set("bars", 0)
    reel.set("monitor", 0)
    engine = make_engine([source, reel], [("forge-1", "out", "reel-1", "in"),
                                          ("reel-1", "out", "mainout-1", "in")])
    assert reel.arm(120.0)
    reel.command("rec", True, 0)
    bar = 16 * STEP / SR
    first = engine.render(bar)
    assert reel.length == 16 * STEP and rms(first) == 0.0      # monitor off, tape was blank
    reel.command("rec", False, 0)
    empty(source)
    engine.render(256 / SR)
    engine.transport.stop()
    engine.render(0.01)
    engine.transport.play()
    again = engine.render(bar)
    assert rms(again[:, :4000]) > 0.02                           # the kick comes back off tape
    reel.erase(0)
    assert reel.length == 0 and not reel.has_audio()


def test_reel_tape_survives_save_and_load(tmp_path):
    reel = Reel(SR)
    reel.uid = "reel-1"
    reel.arm(100.0)
    reel.tape[0][:, :1000] = 0.25
    reel.save_assets(tmp_path)
    data = reel.to_dict()
    copy = Reel(SR)
    copy.uid = "reel-1"
    copy.load_dict(data)
    copy.load_assets(tmp_path)
    assert copy.length == reel.length and copy.tape_bpm == 100.0
    assert np.allclose(copy.tape[0], reel.tape[0], atol=1e-4) and copy.tape[1] is None


# -- utility ------------------------------------------------------------------
def test_afterglow_rings_on_after_the_input_stops():
    box, fx = empty(Knockbox(SR)), Afterglow(SR)
    box.set_step(1, 0, Step())
    box.uid, fx.uid = "knockbox-1", "afterglow-1"
    engine = make_engine([box, fx], [("knockbox-1", "out", "afterglow-1", "in"),
                                     ("afterglow-1", "out", "mainout-1", "in")])
    engine.render(0.5)
    engine.transport.stop()
    tail = engine.render(1.0)
    assert rms(tail[:, SR // 2:]) > 1e-4


def test_summit_sums_pans_and_mutes():
    a, b, mixer = empty(Forge(SR)), empty(Forge(SR)), Summit(SR)
    a.set_step(0, 0, a.new_step(0))
    b.set_step(0, 0, b.new_step(0))
    a.uid, b.uid, mixer.uid = "forge-1", "forge-2", "summit-1"
    cables = [("forge-1", "out", "summit-1", "in1"), ("forge-2", "out", "summit-1", "in2"),
              ("summit-1", "out", "mainout-1", "in")]
    mixer.set("pan1", -1.0)
    mixer.mute[1] = True
    out = make_engine([a, b, mixer], cables).render(0.3)
    assert rms(out[0]) > 0.01 and rms(out[1]) == 0.0


def test_two_cables_into_one_input_are_summed():
    a, b = empty(Forge(SR)), empty(Forge(SR))
    a.set_step(0, 0, a.new_step(0))
    b.set_step(0, 0, b.new_step(0))
    a.uid, b.uid = "forge-1", "forge-2"
    one = make_engine([a], [("forge-1", "out", "mainout-1", "in")]).render(0.2)
    for box in (a, b):
        box.set_sample_rate(44100)
        box.set_sample_rate(SR)       # fresh voices
    both = make_engine([a, b], [("forge-1", "out", "mainout-1", "in"),
                                ("forge-2", "out", "mainout-1", "in")]).render(0.2)
    assert rms(both) > 1.5 * rms(one)


def test_feedback_loops_are_detected_and_plans_run_in_dependency_order():
    cables = [("a", "out", "b", "in"), ("b", "out", "c", "in")]
    assert would_loop(cables, "c", "a") and would_loop(cables, "a", "a")
    assert not would_loop(cables, "a", "c")
    fx, box = Afterglow(SR), Knockbox(SR)
    fx.uid, box.uid = "fx", "box"
    plan = build_plan([fx, box], [("box", "send", "fx", "in"), ("nope", "out", "fx", "in")])
    assert [m.uid for m, _ in plan] == ["box", "fx"]
    assert plan[1][1] == (("in", (("box", "send"),)),)


def test_pedal_loop_runs_a_saved_pedalboard():
    if not available_boards():
        pytest.skip("pedalboard-effects is not checked out next to this repo")
    box, loop = empty(Forge(SR)), PedalLoop(SR)
    box.set_step(6, 0, box.new_step(6))
    box.uid, loop.uid = "forge-1", "pedalloop-1"
    assert loop.load_board("Shoegaze Wash") and len(loop.chain) >= 3
    assert all(p.TYPE not in PedalLoop.SKIP for p in loop.chain)
    cables = [("forge-1", "out", "pedalloop-1", "in"), ("pedalloop-1", "out", "mainout-1", "in")]
    wet = make_engine([box, loop], cables).render(0.5)
    loop.set("mix", 0.0)
    box.set_sample_rate(44100)
    box.set_sample_rate(SR)
    dry = make_engine([box, loop], cables).render(0.5)
    assert np.all(np.isfinite(wet)) and not np.allclose(wet, dry, atol=1e-3)


# -- library and racks --------------------------------------------------------
def test_factory_library_is_complete_and_sane():
    for name in FACTORY_NAMES:
        sample = LIBRARY.get(name)
        assert sample is not None and len(sample.data) > 500
        assert np.all(np.isfinite(sample.data)) and 0.1 < np.abs(sample.data).max() <= 1.0
        assert len(sample.peaks(40)) == 40


def test_importing_a_file_copies_it_into_the_library(tmp_path):
    source = tmp_path / "elsewhere" / "My Loop.wav"
    write_wav(source, 0.5 * np.sin(np.arange(22050) * 0.05), 22050)
    library = Library(tmp_path / "samples")
    name = library.import_file(source)
    assert name == "My Loop" and name in library.names()
    assert library.import_file(source) == "My Loop"            # importing twice does not duplicate
    assert len(library.user_names()) == 1
    sample = library.get(name)
    assert sample.sr == 22050 and abs(sample.seconds - 1.0) < 0.01
    with pytest.raises((OSError, ValueError)):
        library.import_file(tmp_path / "missing.wav")


@pytest.mark.parametrize("rack", FACTORY_RACKS, ids=lambda r: r["name"])
def test_factory_racks_load_and_play_cleanly(rack):
    if rack["name"] == "Through the Pedalboard" and not available_boards():
        pytest.skip("pedalboard-effects is not checked out next to this repo")
    modules, cables = build_rack(rack, SR)
    assert len(cables) == len(rack["cables"])
    engine = make_engine(modules, cables, bpm=rack_tempo(rack)[0])
    out = engine.render(4.0)
    assert engine.last_error is None
    assert np.all(np.isfinite(out)) and np.abs(out).max() <= 1.0
    if len(modules) > 1 and rack["name"] != "Synth Sketchpad":
        assert 0.03 < rms(out) < 0.3, "factory rack level is off"


def test_every_module_round_trips_through_its_dict():
    for cls in MODULE_CLASSES:
        module = cls(SR)
        module.uid = f"{cls.TYPE}-1"
        for param in cls.PARAMS:
            module.set(param.key, param.hi if not param.is_choice else len(param.choices) - 1)
        copy = cls(SR)
        copy.load_dict(module.to_dict())
        copy.uid = module.uid
        assert copy.to_dict() == module.to_dict()


def test_groovebox_patterns_locks_and_kit_round_trip():
    box = Forge(SR)
    box.set_sound(2, "Chord")
    box.tracks[2].values["cutoff"] = 0.4
    box.patterns[1].length = 32
    box.patterns[1].steps[2][17] = Step(67, 0.5, 3, 0.7, {"cutoff": 0.9, "bogus": 1})
    copy = Forge(SR)
    copy.load_dict(box.to_dict())
    step = copy.patterns[1].steps[2][17]
    assert copy.tracks[2].sound == "Chord" and copy.tracks[2].values["cutoff"] == 0.4
    assert (step.note, step.length, step.locks) == (67, 3, {"cutoff": 0.9})
