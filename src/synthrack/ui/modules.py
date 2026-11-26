"""The faceplates: grooveboxes, Wander, Reel and the utility modules."""

from __future__ import annotations

import math
import time

import numpy as np
from PyQt6.QtCore import QFile, QPointF, QRectF, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from ..dsp.groovebox import LENGTHS, PATTERN_NAMES, TRIG_PARAMS, note_name
from ..dsp.library import LIBRARY, write_wav
from ..dsp.reel import BARS, TRACKS
from ..dsp.wander import ENGINE_LABELS, ENGINES
from ..racks import recordings_dir, tidy_path
from .module_widget import HEADER_H, PIANO_KEYS, ModuleWidget
from .theme import (
    FINISHES,
    MODULE_COLORS,
    RED,
    SCREEN_DIM,
    SCREEN_FG,
    UI_ACCENT,
    draw_led,
    draw_screen,
    fit_font,
    font,
)
from .widgets import CycleField, Keyboard, Knob, PageSelect, StepRow, TrackPads, VMeter

DIGITS = (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_4,
          Qt.Key.Key_5, Qt.Key.Key_6, Qt.Key.Key_7, Qt.Key.Key_8)


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _to_trash(path) -> bool:
    return QFile.moveToTrash(str(path))


def sample_actions(widget, menu, name: str, library) -> dict:
    """Context-menu entries for the sample a module is using: rename, delete, show the folder."""
    mine = library.is_user(name)
    rename = menu.addAction(f"Rename Sample “{name}”…" if mine else "Rename Sample…")
    delete = menu.addAction(f"Delete Sample “{name}”…" if mine else "Delete Sample…")
    for action in (rename, delete):
        action.setEnabled(mine)        # built-in sounds are synthesised; there is no file
    reveal = menu.addAction("Show Samples Folder")
    rack = widget.rack

    def do_rename():
        new, ok = QInputDialog.getText(widget, "Rename Sample", "Sample name:", text=name)
        if ok and new.strip() and new.strip() != name:
            try:
                rack.rename_sample(name, library.rename(name, new))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(widget, "Rename Sample", str(exc))

    def do_delete():
        answer = QMessageBox.question(
            widget, "Delete Sample", f"Move “{name}” to the Trash?\n\n"
            "Tracks in this rack that use it go back to their default sound.")
        if answer == QMessageBox.StandardButton.Yes:
            try:
                library.delete(name, _to_trash)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(widget, "Delete Sample", str(exc))
                return
            rack.forget_sample(name)

    def do_reveal():
        folder = library.path_of(name).parent if mine else library.write_root
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    return {rename: do_rename, delete: do_delete, reveal: do_reveal}


# ---------------------------------------------------------------------------
class GrooveScreen(QWidget):
    """Track, pattern, waveform and the value of whatever was touched last."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.touched = ("", "", 0.0)
        self._pv_key = None
        self._pv = np.zeros(1)
        self.setFixedSize(204, 132)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def touch(self, label: str, text: str) -> None:
        self.touched = (label, text, time.monotonic())
        self.update()

    def _wave(self, track, columns: int):
        box = self.owner.module
        if track.sample is not None:
            return track.sample.peaks(columns), track.values["start"], track.values["length"]
        key = (track.sound, track.trig["note"], tuple(round(track.values[k], 3) for k in box.SOURCE_KEYS))
        if key != self._pv_key:      # audition the machine offline at a low rate, just for the picture
            voice = type(track.voice)(12000.0)
            voice.trigger(track.trig["note"], 0.9, dict(track.values), 0.08)
            y = np.abs(voice.render(columns * 30))
            self._pv, self._pv_key = y.reshape(columns, 30).max(axis=1), key
        return self._pv, 0.0, 1.0

    def paintEvent(self, _):
        owner = self.owner
        box = owner.module
        track = box.tracks[box.selected]
        accent = QColor(box.ACCENT)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        draw_screen(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.setPen(accent)
        title = f"T{box.selected + 1} {track.sound.upper()}"
        p.setFont(fit_font(title, w - 70, 13, bold=True, family="mono"))
        p.drawText(QRectF(10, 5, w - 70, 18), Qt.AlignmentFlag.AlignVCenter, title)
        pattern = PATTERN_NAMES[box.pattern]
        if box.next_pattern is not None:
            pattern += f"▸{PATTERN_NAMES[box.next_pattern]}"
        p.setPen(QColor("#ffffff"))
        p.setFont(font(13, bold=True, family="mono"))
        p.drawText(QRectF(w - 80, 5, 70, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   pattern)

        # waveform
        area = QRectF(10, 28, w - 20, 56)
        peaks, start, length = self._wave(track, 92)
        top = max(1e-6, float(peaks.max()))
        mid = area.center().y()
        bar = area.width() / len(peaks)
        p.setPen(Qt.PenStyle.NoPen)
        end = start + length * (1.0 - start)
        for i, value in enumerate(peaks):
            frac = i / len(peaks)
            color = QColor(SCREEN_FG if start <= frac <= end else SCREEN_DIM)
            color.setAlpha(255 if start <= frac <= end else 90)
            p.setBrush(color)
            h = max(1.0, (value / top) * area.height() * 0.5)
            p.drawRect(QRectF(area.left() + i * bar, mid - h, max(1.0, bar - 0.6), 2 * h))
        if track.mute:
            p.setPen(QColor(RED))
            p.setFont(font(11, bold=True, family="mono"))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "MUTED")

        # info line
        label, text, when = self.touched
        p.setFont(font(11, bold=True, family="mono"))
        line = QRectF(10, 88, w - 20, 16)
        if time.monotonic() - when < 1.6:
            p.setPen(QColor("#ffffff"))
            p.drawText(line, Qt.AlignmentFlag.AlignVCenter, label.upper())
            p.setPen(accent)
            p.drawText(line, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
        elif owner.held is not None:
            step = box.pat.steps[box.selected][owner.held]
            locks = len(step.locks) if step else 0
            p.setPen(QColor(RED))
            p.drawText(line, Qt.AlignmentFlag.AlignVCenter,
                       f"STEP {owner.held + 1:02d} · {note_name(step.note) if step else ''}")
            p.drawText(line, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"{locks} LOCK{'' if locks == 1 else 'S'}")
        else:
            p.setPen(QColor(SCREEN_DIM))
            p.setFont(font(9, medium=True, spacing=0.8))
            p.drawText(line, Qt.AlignmentFlag.AlignVCenter, f"{track.sample.seconds:.2f} S"
                       if track.sample is not None else ("MELODIC" if box.melodic(box.selected) else "DRUM"))

        # track activity and state
        for i in range(8):
            level = owner.flash[i]
            color = QColor(accent)
            color.setAlpha(int(255 * level))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 18 if box.tracks[i].mute else 46))
            p.drawRect(QRectF(10 + i * 11, 114, 8, 4))
            p.setBrush(color)
            p.drawRect(QRectF(10 + i * 11, 114, 8, 4))
        p.setFont(font(10, bold=True, family="mono"))
        if getattr(box, "sampling", False):
            p.setPen(QColor(RED))
            status = "SAMPLING"
        elif box.record:
            p.setPen(QColor(RED))
            status = "● REC"
        elif box.play_step >= 0:
            p.setPen(QColor(SCREEN_FG))
            status = f"{box.play_step + 1:02d}/{box.pat.length}"
        else:
            p.setPen(QColor(SCREEN_DIM))
            status = f"--/{box.pat.length}"
        p.drawText(QRectF(w - 90, 108, 80, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   status)


class GrooveBoxWidget(ModuleWidget):
    """Knockbox / Forge: screen, 14 sound knobs, trig knobs, track pads, step keys."""

    ROW2 = ("cutoff", "reso", "fenv", "fdec", "level", "pan", "send")

    def _build(self) -> None:
        box = self.module
        fin = self.fin
        if not hasattr(self, "page"):
            self.page = 0
            self.held = None           # step index being edited (parameter-lock mode)
            self.octave = 0
            self.flash = [0.0] * 8
            self._seen = [t.flash for t in box.tracks]
            self._shown = None
        self.screen = GrooveScreen(self)
        self.screen.move(16, 40)
        self.controls["_screen"] = self.screen

        self.knobs: dict = {}
        rows = ((*box.SOURCE_KEYS, "drive", "crush"), self.ROW2)
        for r, keys in enumerate(rows):
            for c, key in enumerate(keys):
                param = box.track_param(key)
                accent = box.ACCENT if key in box.SOURCE_KEYS else None
                knob = Knob(param.label, 0.5, param.to_norm(param.default), fin["text"],
                            32, accent, lambda t, p=param: p.format(p.from_norm(t)), self)
                knob.changed.connect(lambda t, k=key: self._knob_moved(k, t))
                knob.on_reset = lambda k=key: self._knob_reset(k)
                self.knobs[key] = self.controls[f"_k_{key}"] = self._center(knob, 257 + 60 * c, 36 + 70 * r)

        def field(name, label, choices, x, width, handler, menu=False):
            f = CycleField(label, choices, 0, fin["text"], width, self, menu=menu)
            f.changed.connect(handler)
            f.move(x, 178)
            self.controls[f"_f_{name}"] = f
            return f

        self.f_pattern = field("pattern", "Pattern", PATTERN_NAMES, 16, 84, self._pattern_chosen)
        self.f_length = field("length", "Steps", [str(n) for n in LENGTHS], 106, 72, self._length_chosen)
        self.f_sound = field("sound", "Sound", box.sounds(), 184, 164, self._sound_chosen, menu=True)
        self.f_filter = field("filter", "Filter", box.track_param("ftype").choices, 354, 70,
                              lambda i: self._knob_set("ftype", i))

        self.trig_knobs: dict = {}
        for i, param in enumerate(TRIG_PARAMS):
            fmt = (lambda t, p=param: note_name(p.from_norm(t))) if param.key == "note" \
                else (lambda t, p=param: p.format(p.from_norm(t)))
            knob = Knob(param.label, 0.5, param.to_norm(param.default), fin["text"], 26,
                        None, fmt, self)
            knob.changed.connect(lambda t, k=param.key: self._trig_moved(k, t))
            self._center(knob, 455 + 53 * i, 172)
            self.trig_knobs[param.key] = self.controls[f"_t_{param.key}"] = knob

        self.pads = TrackPads(self._pad_info, box.ACCENT, self)
        self.pads.pressed.connect(self._pad_pressed)
        self.pads.move(16, 240)
        self.controls["_pads"] = self.pads
        self._pad("rec", "Rec", 446, 240, self._toggle_record, "Live record (R)", lambda: box.record, RED,
                  width=48)
        self._pad("mute", "Mute", 497, 240, self._toggle_mute, "Mute the selected track",
                  lambda: box.tracks[box.selected].mute, UI_ACCENT, width=48)
        self._pad("dice", "Dice", 548, 240, self._dice, "Roll a new pattern for this track", width=48)
        self._pad("clear", "Clear", 599, 240, self._clear, "Clear this track (Shift: the whole pattern)",
                  width=48)

        self.steps = StepRow(self._step_state, box.ACCENT, self)
        self.steps.toggled.connect(self._step_toggled)
        self.steps.held.connect(self._step_held)
        self.steps.move(16, 298)
        self.controls["_steps"] = self.steps
        self.pages = PageSelect(box.ACCENT, self)
        self.pages.changed.connect(self._set_page)
        self.pages.move(445, 283)
        self.controls["_pages"] = self.pages
        self._extra_pads()
        self._jack_strip(top=60, pitch=84)
        self.refresh()

    def _extra_pads(self) -> None:
        pass

    # -- state helpers ---------------------------------------------------
    @property
    def track(self):
        return self.module.tracks[self.module.selected]

    def _held_step(self):
        if self.held is None:
            return None
        return self.module.pat.steps[self.module.selected][self.held]

    def refresh(self) -> None:
        box = self.module
        track = self.track
        step = self._held_step()
        if self.held is not None and step is None:
            self.held = None
        labels = box.labels(box.selected)
        for key, knob in self.knobs.items():
            param = box.track_param(key)
            locked = step is not None and key in step.locks
            knob.set_norm(param.to_norm(step.locks[key] if locked else track.values[key]))
            knob.set_locked(locked)
            knob.set_label(labels.get(key, param.label))
        source = step if step is not None else None
        for param in TRIG_PARAMS:
            value = getattr(source, param.key) if source is not None else track.trig[param.key]
            self.trig_knobs[param.key].set_norm(param.to_norm(value))
            self.trig_knobs[param.key].set_locked(step is not None)
        sounds = box.sounds()
        self.f_sound.set_choices(sounds, sounds.index(track.sound) if track.sound in sounds else 0)
        shown = box.next_pattern if box.next_pattern is not None else box.pattern
        self.f_pattern.set_index(shown)
        self.f_length.set_index(LENGTHS.index(box.pat.length))
        ftype = step.locks["ftype"] if step is not None and "ftype" in step.locks else track.values["ftype"]
        self.f_filter.set_index(int(ftype))
        self.page = min(self.page, box.pat.length // 16 - 1)
        self._shown = (box.pattern, box.next_pattern)
        for widget in (self.steps, self.pads, self.screen, *self._pads()):
            widget.update()
        self._sync_pages()

    def _pads(self):
        return [w for k, w in self.controls.items() if k.startswith("_pad_")]

    def _sync_pages(self) -> None:
        box = self.module
        playing = box.play_step // 16 if box.play_step >= 0 else -1
        self.pages.set_state(self.page, box.pat.length // 16, playing)

    def select_track(self, t: int) -> None:
        self.module.selected = t
        self.held = None
        self.refresh()

    # -- knobs --------------------------------------------------------
    def _knob_set(self, key: str, value) -> None:
        box = self.module
        param = box.track_param(key)
        value = param.clamp(value)
        step = self._held_step()
        if step is not None:
            box.set_step(box.selected, self.held, step.replace(locks={**step.locks, key: value}))
            if key in self.knobs:
                self.knobs[key].set_locked(True)
            self.steps.update()
        else:
            self.track.values[key] = value
        label = box.labels(box.selected).get(key, param.label)
        self.screen.touch(label, param.format(value))
        self.edited.emit()

    def _knob_moved(self, key: str, t: float) -> None:
        self._knob_set(key, self.module.track_param(key).from_norm(t))

    def _knob_reset(self, key: str) -> bool:
        """Double-click: in step mode, drop this knob's lock."""
        step = self._held_step()
        if step is None or key not in step.locks:
            return False
        locks = {k: v for k, v in step.locks.items() if k != key}
        self.module.set_step(self.module.selected, self.held, step.replace(locks=locks))
        self.refresh()
        self.edited.emit()
        return True

    def _trig_moved(self, key: str, t: float) -> None:
        param = next(p for p in TRIG_PARAMS if p.key == key)
        value = param.from_norm(t)
        step = self._held_step()
        if step is not None:
            self.module.set_step(self.module.selected, self.held, step.replace(**{key: value}))
            self.steps.update()
        else:
            self.track.trig[key] = value
        self.screen.touch(param.label, note_name(value) if key == "note" else param.format(value))
        self.edited.emit()

    # -- fields -------------------------------------------------------
    def _pattern_chosen(self, index: int) -> None:
        self.rack.pattern_chosen(self.module, index)
        self.held = None
        self.refresh()
        self.edited.emit()

    def _length_chosen(self, index: int) -> None:
        self.module.pat.length = LENGTHS[index]
        self.refresh()
        self.edited.emit()

    def _sound_chosen(self, index: int) -> None:
        box = self.module
        sounds = box.sounds()
        box.set_sound(box.selected, sounds[index % len(sounds)])
        self.refresh()
        box.play(box.selected)
        self.edited.emit()

    # -- pads and steps ---------------------------------------------
    def _pad_info(self, i: int) -> dict:
        box = self.module
        track = box.tracks[i]
        words = track.sound.split()
        label = track.sound if len(track.sound) <= 7 or len(words) < 2 else f"{words[0][:5]} {words[1][0]}"
        return {"label": label, "selected": i == box.selected, "muted": track.mute,
                "flash": self.flash[i]}

    def _pad_pressed(self, i: int) -> None:
        self.rack.select(self)
        self.select_track(i)
        self.module.play(i)

    def _toggle_record(self) -> None:
        self.module.record = not self.module.record
        self.refresh()

    def _toggle_mute(self) -> None:
        self.track.mute = not self.track.mute
        self.refresh()
        self.edited.emit()

    def _dice(self) -> None:
        self.held = None
        self.module.dice(self.module.selected)
        self.refresh()
        self.edited.emit()

    def _clear(self) -> None:
        from PyQt6.QtWidgets import QApplication

        self.held = None
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.module.clear_pattern()
        else:
            self.module.clear_track(self.module.selected)
        self.refresh()
        self.edited.emit()

    def _step_state(self, i: int):
        box = self.module
        index = self.page * 16 + i
        if index >= box.pat.length:
            return None
        step = box.pat.steps[box.selected][index]
        return {"on": step is not None, "locks": bool(step and step.locks),
                "vel": step.vel if step else 0.0, "playing": index == box.play_step,
                "held": index == self.held, "number": index + 1}

    def _step_toggled(self, i: int) -> None:
        box = self.module
        index = self.page * 16 + i
        if index >= box.pat.length:
            return
        self.rack.select(self)
        if box.toggle_step(box.selected, index) is None and self.held == index:
            self.held = None
        self.refresh()
        self.edited.emit()

    def _step_held(self, i: int) -> None:
        box = self.module
        index = self.page * 16 + i
        if index >= box.pat.length:
            return
        self.rack.select(self)
        if self.held == index:
            self.held = None
        else:
            if box.pat.steps[box.selected][index] is None:
                box.set_step(box.selected, index, box.new_step(box.selected))
                self.edited.emit()
            self.held = index
        self.refresh()

    def _set_page(self, page: int) -> None:
        self.page = max(0, min(self.module.pat.length // 16 - 1, page))
        self.held = None
        self.refresh()

    # -- hooks --------------------------------------------------------
    def tick(self) -> None:
        box = self.module
        lively = False
        for i, track in enumerate(box.tracks):
            if track.flash != self._seen[i]:
                self._seen[i] = track.flash
                self.flash[i] = 1.0
                lively = True
            elif self.flash[i] > 0.0:
                self.flash[i] = self.flash[i] * 0.72 if self.flash[i] > 0.03 else 0.0
                lively = True
        step = box.play_step
        if (box.pattern, box.next_pattern) != self._shown:
            self.refresh()
        if step != getattr(self, "_last_step", -2):
            self._last_step = step
            self.steps.update()
            self._sync_pages()
            lively = True
        if lively or time.monotonic() - self.screen.touched[2] < 1.8 or getattr(box, "sampling", False):
            self.pads.update()
            self.screen.update()
        self._poll()

    def _poll(self) -> None:
        pass

    def key(self, key, down: bool, mods) -> bool:
        box = self.module
        if key in DIGITS:
            if down:
                self.select_track(DIGITS.index(key))
                box.play(box.selected)
            return True
        if key in PIANO_KEYS:
            if down:
                box.play(box.selected, self.track.trig["note"] + PIANO_KEYS[key] + 12 * self.octave)
            return True
        if not down:
            return False
        if key in (Qt.Key.Key_Z, Qt.Key.Key_X):
            self.octave = max(-3, min(3, self.octave + (1 if key == Qt.Key.Key_X else -1)))
            self.screen.touch("Octave", f"{self.octave:+d}")
            return True
        if key == Qt.Key.Key_R:
            self._toggle_record()
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._set_page(self.page + (1 if key == Qt.Key.Key_Right else -1))
            return True
        if key == Qt.Key.Key_Escape and self.held is not None:
            self.held = None
            self.refresh()
            return True
        return False

    def menu_actions(self, menu) -> dict:
        box = self.module
        actions = {menu.addAction("Copy Pattern"): box.copy_pattern}
        paste = menu.addAction("Paste Pattern")
        paste.setEnabled(bool(box.clip_board))
        actions[paste] = lambda: (box.paste_pattern(), self.refresh(), self.edited.emit())
        link = menu.addAction("Link Pattern Changes")
        link.setCheckable(True)
        link.setChecked(box.link)
        actions[link] = lambda: (setattr(box, "link", not box.link), self.edited.emit())
        return actions



class KnockboxWidget(GrooveBoxWidget):
    def _build(self) -> None:
        super()._build()
        self.setAcceptDrops(True)

    def _extra_pads(self) -> None:
        box = self.module
        self._pad("load", "Load", 548, 300, self._load,
                  "Load an audio file onto this track (or drop one here)", width=48)
        self._pad("smpl", "Smpl", 599, 300, self._sample, "Record the IN jack onto this track",
                  lambda: box.sampling, RED, width=48)

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"Sample for track {self.module.selected + 1}", "",
            "Audio (*.wav *.aif *.aiff *.flac *.mp3 *.ogg *.m4a);;All files (*)")
        if path:
            self.import_file(path)

    def import_file(self, path: str) -> bool:
        box = self.module
        try:
            name = box.library.import_file(path)
        except Exception as exc:
            self.screen.touch("Can't load", type(exc).__name__)
            return False
        box.set_sound(box.selected, name)
        self.refresh()
        box.play(box.selected)
        self.edited.emit()
        return True

    def menu_actions(self, menu) -> dict:
        actions = sample_actions(self, menu, self.track.sound, self.module.library)
        menu.addSeparator()
        return {**actions, **super().menu_actions(menu)}

    def _sample(self) -> None:
        box = self.module
        box.command("sample", not box.sampling, box.selected)
        self.rack.need_engine.emit()

    def _poll(self) -> None:
        box = self.module
        done = box.take_sampled()
        if done is None:
            return
        audio, t = done
        loud = np.flatnonzero(np.abs(audio) > 0.01)
        if len(loud) == 0:
            self.screen.touch("Sampling", "silence")
        else:
            audio = audio[max(0, loud[0] - 64):loud[-1] + 2000]     # trim the silence around the take
            box.set_sound(t, box.library.add_recording(audio, int(box.sr)))
            self.edited.emit()
        self.refresh()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile() and self.import_file(url.toLocalFile()):
                break
        e.acceptProposedAction()


class ForgeWidget(GrooveBoxWidget):
    def _extra_pads(self) -> None:
        self._pad("rand", "Rand", 548, 300, self._rand, "Roll a new sound for this track", width=48)
        self._pad("init", "Init", 599, 300, self._init, "Reset this track's sound", width=48)

    def _rand(self) -> None:
        box = self.module
        box.randomize(box.selected)
        self.refresh()
        box.play(box.selected)
        self.edited.emit()

    def _init(self) -> None:
        self.module.init_sound(self.module.selected)
        self.refresh()
        self.edited.emit()


# ---------------------------------------------------------------------------
class WanderScreen(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setFixedSize(180, 70)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _):
        synth = self.owner.module
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        draw_screen(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        engine = ENGINES[int(synth.get("engine"))]
        color = QColor(MODULE_COLORS[int(synth.get("engine")) % 4])
        p.setPen(color)
        p.setFont(font(12, bold=True, family="mono"))
        p.drawText(QRectF(10, 4, w - 20, 16), Qt.AlignmentFlag.AlignVCenter, engine.upper())
        p.setPen(QColor(SCREEN_DIM))
        p.setFont(font(10, bold=True, family="mono"))
        notes = sorted(set(synth.sounding()))
        octave = synth.param("octave").choices[int(synth.get("octave"))]
        right = " ".join(note_name(n) for n in notes[:4]) if notes else f"OCT {octave}"
        p.drawText(QRectF(10, 4, w - 20, 16), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   right)
        scope = synth.scope
        mid = 22 + (h - 28) / 2.0
        path = QPainterPath()
        if len(scope) > 16:
            # start on a rising zero crossing so the picture stands still
            rising = np.flatnonzero((scope[:-1] < 0) & (scope[1:] >= 0))
            start = int(rising[0]) if len(rising) and rising[0] < len(scope) // 2 else 0
            view = scope[start:start + len(scope) // 2]
            gain = (h - 34) / 2.0 / max(0.05, float(np.abs(view).max()))
            xs = np.linspace(10, w - 10, len(view))
            path.moveTo(xs[0], mid - view[0] * gain)
            for x, v in zip(xs[1::2], view[1::2]):
                path.lineTo(float(x), mid - float(v) * gain)
        else:
            path.moveTo(10, mid)
            path.lineTo(w - 10, mid)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(SCREEN_FG), 1.3))
        p.drawPath(path)


class WanderWidget(ModuleWidget):
    ROWS = (("color", "shape", "cutoff", "reso"), ("attack", "decay", "sustain", "release"),
            ("env", "lfo_rate", "lfo_depth", "chorus"))
    CAPS = {"color": MODULE_COLORS[2], "shape": MODULE_COLORS[3], "cutoff": "#f6f6f2",
            "reso": MODULE_COLORS[0]}     # four coloured encoders; everything else is neutral

    def _build(self) -> None:
        synth = self.module
        self._keys_down: dict = {}
        self.screen = WanderScreen(self)
        self.screen.move(16, 40)
        self.controls["_screen"] = self.screen
        self._field("engine", 16, 114, 180, menu=True)
        self._field("arp", 16, 154, 88)
        self._field("arp_rate", 108, 154, 88)
        self._field("lfo_dest", 16, 194, 88)
        self._field("octave", 108, 194, 88)
        names = synth.library.names()
        index = names.index(synth.sample_name) if synth.sample_name in names else 0
        self.f_sample = CycleField("Sample", names, index, self.fin["text"], 180, self, menu=True)
        self.f_sample.changed.connect(self._sample_chosen)
        self.f_sample.move(16, 234)
        self.controls["_f_sample"] = self.f_sample
        for r, keys in enumerate(self.ROWS):
            for c, key in enumerate(keys):
                self._knob(key, 235 + 62 * c, 36 + 68 * r, 32, cap=self.CAPS.get(key))
        self._knob("level", 430, 244, 30)
        self._pad("hold", "Hold", 405, 314, self._toggle_hold, "Hold notes / latch the arp",
                  lambda: int(synth.get("hold")) == 1, UI_ACCENT)
        self.keys = Keyboard(48, 14, 374, 66, MODULE_COLORS[2], self)
        self.keys.note_on.connect(lambda n: (self.rack.select(self), self._note(n, True)))
        self.keys.note_off.connect(lambda n: self._note(n, False))
        self.keys.move(16, 282)
        self.controls["_keys"] = self.keys
        self._jack("out", "out", self.strip_x, 150)
        self.refresh()

    def refresh(self) -> None:
        super().refresh()
        synth = self.module
        engine = ENGINES[int(synth.get("engine"))]
        for key, label in zip(("color", "shape"), ENGINE_LABELS[engine]):
            self.controls[key].set_label(label)
        names = synth.library.names()
        self.f_sample.set_choices(names, names.index(synth.sample_name) if synth.sample_name in names else 0)
        self.controls["_pad_hold"].update()

    def _set(self, key: str, value) -> None:
        super()._set(key, value)
        if key == "engine":
            self.refresh()
        self.screen.update()

    def _sample_chosen(self, index: int) -> None:
        synth = self.module
        names = synth.library.names()
        synth.set_sample(names[index % len(names)])
        if ENGINES[int(synth.get("engine"))] != "Sample":
            self._set("engine", ENGINES.index("Sample"))
        self.edited.emit()

    def menu_actions(self, menu) -> dict:
        return sample_actions(self, menu, self.module.sample_name, self.module.library)

    def _toggle_hold(self) -> None:
        self._set("hold", 0 if int(self.module.get("hold")) else 1)
        self.controls["_pad_hold"].update()

    def _note(self, note: int, on: bool) -> None:
        if on:
            self.module.command("on", note, 0.8)
            self.rack.need_engine.emit()
        else:
            self.module.command("off", note)

    def tick(self) -> None:
        synth = self.module
        transpose = 12 * (int(synth.get("octave")) - 2)
        self.keys.set_lit(n - transpose for n in synth.sounding())
        if len(synth.scope) > 16 or getattr(self, "_was_live", False):
            self.screen.update()
        self._was_live = len(synth.scope) > 16

    def key(self, key, down: bool, mods) -> bool:
        if key in PIANO_KEYS:
            note = 60 + PIANO_KEYS[key]
            if down and key not in self._keys_down:
                self._keys_down[key] = note
                self._note(note, True)
            elif not down and key in self._keys_down:
                self._note(self._keys_down.pop(key), False)
            return True
        if not down:
            return False
        if key in (Qt.Key.Key_Z, Qt.Key.Key_X):
            self._set("octave", int(self.module.get("octave")) + (1 if key == Qt.Key.Key_X else -1))
            self.refresh()
            return True
        if key == Qt.Key.Key_Escape:
            self._keys_down.clear()
            self.module.command("panic")
            return True
        return False

    def set_selected(self, selected: bool) -> None:
        if not selected:                 # don't leave notes hanging when focus moves on
            for note in self._keys_down.values():
                self.module.command("off", note)
            self._keys_down.clear()
        super().set_selected(selected)


# ---------------------------------------------------------------------------
class ReelDisplay(QWidget):
    LANE_TOP, LANE_H = 70, 18

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.message = ("", 0.0)
        self._peaks: dict = {}
        self._angle = 0.0
        self.setFixedSize(264, 146)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def say(self, text: str) -> None:
        self.message = (text, time.monotonic())
        self.update()

    def mousePressEvent(self, e):
        lane = int((e.position().y() - self.LANE_TOP) // self.LANE_H)
        if 0 <= lane < TRACKS:
            self.owner.select_track(lane)
        e.accept()

    def _lane_peaks(self, t: int, columns: int):
        reel = self.owner.module
        buf = reel.tape[t]
        if buf is None:
            return None
        key = reel.dirty[t]
        cached = self._peaks.get(t)
        fresh = cached is not None and cached[0] == key
        if not fresh and (cached is None or time.monotonic() - cached[2] > 0.25):
            usable = buf.shape[1] - buf.shape[1] % columns
            peaks = np.abs(buf[0, :usable]).reshape(columns, -1).max(axis=1)
            cached = self._peaks[t] = (key, peaks, time.monotonic())
        return cached[1] if cached else None

    def paintEvent(self, _):
        reel = self.owner.module
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        draw_screen(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        rolling = reel.rolling
        if rolling:
            self._angle = (self._angle + 5.0 * reel.rate) % 360.0
        for cx in (44.0, w - 44.0):      # the reels
            c = QPointF(cx, 36.0)
            p.setPen(QPen(QColor(SCREEN_DIM), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 25, 25)
            p.setBrush(QColor("#2a2b2e"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(c, 17 if cx < w / 2 else 13, 17 if cx < w / 2 else 13)
            p.setBrush(QColor("#0c0d0e"))
            p.drawEllipse(c, 7, 7)
            p.setPen(QPen(QColor(SCREEN_FG), 1.4))
            for k in range(3):
                ang = math.radians(self._angle + 120 * k)
                d = QPointF(math.cos(ang), math.sin(ang))
                p.drawLine(c + d * 3, c + d * 7)
        if reel.recording:
            state, color = "REC", QColor(RED)
        elif rolling:
            state, color = "PLAY", QColor(SCREEN_FG)
        elif reel.length:
            state, color = "STOP", QColor(SCREEN_DIM)
        else:
            state, color = "BLANK", QColor(SCREEN_DIM)
        p.setPen(color)
        p.setFont(font(15, bold=True, family="mono", spacing=2.0))
        p.drawText(QRectF(70, 8, w - 140, 26), Qt.AlignmentFlag.AlignCenter, state)
        p.setFont(font(10, bold=True, family="mono"))
        text, when = self.message
        if time.monotonic() - when < 3.0:
            p.setPen(QColor(UI_ACCENT))
            info = text
        elif reel.length:
            bars = round(reel.length / reel.tape_sr * reel.tape_bpm / 240.0)
            off = abs(reel.rate - 1.0) > 1e-3 and rolling
            p.setPen(QColor(UI_ACCENT) if off else QColor(SCREEN_DIM))
            info = f"{bars} BAR · ♩{reel.tape_bpm:.0f}" + (f" ×{reel.rate:.2f}" if off else "")
        else:
            p.setPen(QColor(SCREEN_DIM))
            info = "PRESS REC"
        p.drawText(QRectF(70, 36, w - 140, 16), Qt.AlignmentFlag.AlignCenter, info)

        left, lane_w = 30.0, w - 42.0
        for t in range(TRACKS):
            y = self.LANE_TOP + t * self.LANE_H
            lane = QRectF(left, y + 1, lane_w, self.LANE_H - 3)
            selected = t == reel.selected
            color = QColor(SCREEN_FG)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 22 if selected else 9))
            p.drawRoundedRect(lane, 2, 2)
            p.setPen(color if selected else QColor(SCREEN_DIM))
            p.setFont(font(10, bold=True, family="mono"))
            p.drawText(QRectF(8, y, 20, self.LANE_H - 1), Qt.AlignmentFlag.AlignVCenter,
                       "M" if reel.mute[t] else str(t + 1))
            peaks = self._lane_peaks(t, 111)
            if peaks is not None:
                color.setAlpha(60 if reel.mute[t] else 230 if selected else 130)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                mid = lane.center().y()
                step = lane_w / len(peaks)
                for i, value in enumerate(peaks):
                    h = min(lane.height() / 2, max(0.5, value * lane.height()))
                    p.drawRect(QRectF(left + i * step, mid - h, step - 0.5, 2 * h))
            if selected and reel.recording:
                p.setPen(QPen(QColor(RED), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(lane, 2, 2)
        if reel.length and rolling:
            x = left + lane_w * reel.pos / reel.length
            p.setPen(QPen(QColor(RED), 1.4))
            p.drawLine(QPointF(x, self.LANE_TOP - 2), QPointF(x, self.LANE_TOP + TRACKS * self.LANE_H))


class ReelWidget(ModuleWidget):
    def _build(self) -> None:
        reel = self.module
        self.display = ReelDisplay(self)
        self.display.move(16, 40)
        self.controls["_display"] = self.display
        self._field("bars", 16, 192, 84)
        self._field("speed", 104, 192, 84)
        self._field("monitor", 192, 192, 88)
        for i in range(TRACKS):
            self._knob(f"level{i + 1}", 49 + 66 * i, 234, 30)
        self._pad("rec", "Rec", 16, 312, self._record, "Record the IN jack onto the selected track (R)",
                  lambda: reel.recording, RED, width=62)
        self._pad("mute", "Mute", 83, 312, self._mute, "Mute the selected track",
                  lambda: reel.mute[reel.selected], UI_ACCENT, width=62)
        self._pad("erase", "Erase", 150, 312, self._erase, "Erase the selected track (Shift: the whole tape)",
                  width=62)
        self._pad("bounce", "Bounce", 217, 312, self._bounce,
                  "Write the loop to the recordings folder as a WAV", width=62)
        self._jack("in", "in", self.strip_x, 90)
        self._jack("out", "out", self.strip_x, 200)

    def select_track(self, t: int) -> None:
        self.rack.select(self)
        self.module.selected = t
        self.display.update()
        self.controls["_pad_mute"].update()

    def _set(self, key: str, value) -> None:
        if key == "bars" and self.module.has_audio():
            self.display.say("ERASE ALL TO RESIZE")
        super()._set(key, value)

    def _record(self) -> None:
        reel = self.module
        if reel.recording:
            reel.command("rec", False, reel.selected)
            return
        self.rack.need_play.emit()
        transport = self.rack.transport
        if not reel.arm(transport.bpm):
            self.display.say("LOOP TOO LONG")
        elif reel.length and abs(reel.tape_bpm - transport.bpm) > 0.01 or int(reel.get("speed")):
            self.display.say("NEEDS 1× AT TAPE TEMPO")
        else:
            reel.command("rec", True, reel.selected)
        self.edited.emit()

    def _mute(self) -> None:
        reel = self.module
        reel.mute[reel.selected] = not reel.mute[reel.selected]
        self.display.update()
        self.edited.emit()

    def _erase(self) -> None:
        from PyQt6.QtWidgets import QApplication

        reel = self.module
        if reel.recording:
            reel.command("rec", False, reel.selected)
        everything = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        reel.erase(None if everything else reel.selected)
        self.display.update()
        self.edited.emit()

    def _bounce(self) -> None:
        result = self.module.bounce()
        if result is None:
            self.display.say("NOTHING ON TAPE")
            return
        path = recordings_dir() / f"reel-{_stamp()}.wav"
        try:
            write_wav(path, result[0], result[1])
            self.display.say(f"→ {path.name}")
            self.window().say(f"Saved {path.name} in {tidy_path(path.parent)}")
        except Exception as exc:
            self.display.say(type(exc).__name__)

    def tick(self) -> None:
        reel = self.module
        state = (reel.rolling, reel.recording)
        talking = time.monotonic() - self.display.message[1] < 3.2
        if reel.rolling or talking or state != getattr(self, "_state", None):
            self.display.update()
            self.controls["_pad_rec"].update()
        self._state = state

    def key(self, key, down: bool, mods) -> bool:
        if not down:
            return False
        if key in DIGITS[:TRACKS]:
            self.select_track(DIGITS.index(key))
            return True
        if key == Qt.Key.Key_R:
            self._record()
            return True
        return False


# ---------------------------------------------------------------------------
class AfterglowWidget(ModuleWidget):
    def _build(self) -> None:
        self._field("time", 12, 38, 118)
        keys = ("feedback", "tone", "echo", "dry", "size", "damp", "reverb")
        for i, key in enumerate(keys):
            cx = 71 if key == "reverb" else 41 + 60 * (i % 2)
            self._knob(key, cx, 82 + 68 * (i // 2), 32)
        self._jack("in", "in", self.strip_x, 110)
        self._jack("out", "out", self.strip_x, 220)


class SummitWidget(ModuleWidget):
    def _build(self) -> None:
        mixer = self.module
        self.meters = []
        for i in range(mixer.CHANNELS):
            cx = 34 + 50 * i
            self._knob(f"pan{i + 1}", cx, 36, 24)
            self._knob(f"level{i + 1}", cx, 100, 30)
            self._pad(f"mute{i}", "Mute", cx - 22, 182, lambda i=i: self._mute(i), "",
                      lambda i=i: mixer.mute[i], UI_ACCENT, width=44)
            meter = VMeter(96, self.fin["text"], self)
            meter.move(cx - 2, 232)
            self.meters.append(meter)
            self.controls[f"_meter{i}"] = meter
        for i, name in enumerate(mixer.INPUTS):
            self._jack("in", name, self.strip_x, 40 + 54 * i, f"in {i + 1}")
        self._jack("out", "out", self.strip_x, 268)

    def _mute(self, i: int) -> None:
        self.module.mute[i] = not self.module.mute[i]
        self.controls[f"_pad_mute{i}"].update()
        self.edited.emit()

    def tick(self) -> None:
        mixer = self.module
        for i, meter in enumerate(self.meters):
            meter.feed(mixer.peaks[i])
            mixer.peaks[i] = 0.0


class PedalStrip(QWidget):
    """The hosted board's pedals as coloured chips; click one to switch it on or off."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setFixedSize(190, 160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    ROW = 22

    def mousePressEvent(self, e):
        chain = self.owner.module.chain
        i = int((e.position().y() - 6) // self.ROW)
        if 0 <= i < len(chain):
            chain[i].enabled = not chain[i].enabled
            self.update()
            self.owner.edited.emit()
        e.accept()

    def paintEvent(self, _):
        loop = self.owner.module
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_screen(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        if not loop.chain:
            p.setPen(QColor(255, 255, 255, 130))
            p.setFont(font(10, bold=True, family="mono"))
            text = loop.error.upper() if loop.error else "PICK A BOARD"
            p.drawText(QRectF(8, 0, self.width() - 16, self.height()),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
            return
        for i, pedal in enumerate(loop.chain[:7]):
            fin = FINISHES.get(pedal.finish or pedal.FINISH, FINISHES["graphite"])
            rect = QRectF(8, 6 + i * self.ROW, self.width() - 16, self.ROW - 4)
            body = QColor(fin["body"])
            if not pedal.enabled:
                body.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(body)
            p.drawRoundedRect(rect, 4, 4)
            draw_led(p, QPointF(rect.left() + 10, rect.center().y()), 2.6, QColor(fin["text"]), pedal.enabled)
            text = QColor(fin["text"])
            text.setAlpha(255 if pedal.enabled else 120)
            p.setPen(text)
            p.setFont(font(11, bold=True, family="logo", spacing=0.8))
            p.drawText(rect.adjusted(22, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, pedal.NAME.upper())


class PedalLoopWidget(ModuleWidget):
    def _build(self) -> None:
        loop = self.module
        names = loop.boards() or ["-"]
        if not loop.board and loop.boards():
            loop.load_board(names[0])
        self.f_board = CycleField("Board", names, names.index(loop.board) if loop.board in names else 0,
                                  self.fin["text"], 190, self, menu=True)
        self.f_board.changed.connect(self._board_chosen)
        self.f_board.move(12, 38)
        self.controls["_f_board"] = self.f_board
        self.strip = PedalStrip(self)
        self.strip.move(12, 84)
        self.controls["_strip"] = self.strip
        self._knob("mix", 62, 256, 34)
        self._knob("level", 152, 256, 34)
        self._jack("in", "in", self.strip_x, 110)
        self._jack("out", "out", self.strip_x, 220)

    def _board_chosen(self, index: int) -> None:
        names = self.module.boards()
        if names:
            self.module.load_board(names[index % len(names)])
            self.strip.update()
            self.edited.emit()


class LineInWidget(ModuleWidget):
    def _build(self) -> None:
        self._knob("gain", self.width() / 2, 44, 36)
        self.meter = VMeter(96, self.fin["text"], self)
        self._center(self.meter, self.width() / 2, 130)
        self.controls["_meter"] = self.meter
        self._jack("out", "out", self.width() / 2, 262, "live")

    def tick(self) -> None:
        self.meter.feed(self.module.peak)
        self.module.peak = 0.0


class ScopeDisplay(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setFixedSize(80, 76)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_screen(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        scope = self.owner.module.scope
        w, h = self.width(), self.height()
        path = QPainterPath()
        if scope.ndim == 2 and scope.shape[1] > 16:
            view = scope.mean(axis=0)
            xs = np.linspace(6, w - 6, len(view))
            path.moveTo(xs[0], h / 2 - float(view[0]) * h * 0.45)
            for x, v in zip(xs[2::2], view[2::2]):
                path.lineTo(float(x), h / 2 - float(v) * h * 0.45)
        else:
            path.moveTo(6, h / 2)
            path.lineTo(w - 6, h / 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(SCREEN_FG), 1.2))
        p.drawPath(path)


class MainOutWidget(ModuleWidget):
    def _build(self) -> None:
        self.scope = ScopeDisplay(self)
        self._center(self.scope, self.width() / 2, 40)
        self.controls["_scope"] = self.scope
        self.meters = []
        for i in range(2):
            meter = VMeter(110, self.fin["text"], self)
            self._center(meter, self.width() / 2 - 5 + 10 * i, 128)
            self.meters.append(meter)
            self.controls[f"_meter{i}"] = meter
        self._jack("in", "in", self.width() / 2, 262, "main")

    def tick(self) -> None:
        out = self.module
        for i, meter in enumerate(self.meters):
            meter.feed(out.peaks[i])
        live = out.peaks[0] > 1e-5 or out.peaks[1] > 1e-5
        out.peaks = [0.0, 0.0]
        if live or getattr(self, "_was_live", False):
            self.scope.update()
        if not live:
            out.scope = np.zeros(8, dtype=np.float32)
        self._was_live = live


WIDGETS = {"knockbox": KnockboxWidget, "forge": ForgeWidget, "wander": WanderWidget, "reel": ReelWidget,
           "afterglow": AfterglowWidget, "summit": SummitWidget, "pedalloop": PedalLoopWidget,
           "linein": LineInWidget, "mainout": MainOutWidget}


def make_module_widget(module, rack) -> ModuleWidget:
    return WIDGETS.get(module.TYPE, ModuleWidget)(module, rack)


__all__ = ["HEADER_H", "LIBRARY", "BARS", "make_module_widget"]
