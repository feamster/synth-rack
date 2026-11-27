"""Main window: transport bar, the rack and the module shelf."""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, racks
from ..dsp.library import LIBRARY, write_wav
from ..dsp.transport import BPM_MAX, BPM_MIN, SWING_MAX
from ..engine import BLOCK_SIZES, SAMPLE_RATES, AudioConfig, AudioEngine, list_devices
from ..racks import RackStore, build_rack, rack_tempo, rack_to_dict, recordings_dir, tidy_path
from .module_widget import ModuleWidget
from .rack_view import ModuleBrowser, RackView
from .theme import RACK_SKINS, ROW_H, UI_ACCENT, UI_BG, UI_DIM, UI_PANEL, UI_TEXT
from .widgets import Knob, LevelMeter, PowerButton, TransportButton

STYLE = f"""
QMainWindow, QDialog {{ background: {UI_BG}; }}
QWidget#bar, QWidget#shelf {{ background: {UI_PANEL}; }}
QLabel {{ color: {UI_TEXT}; font-size: 12px; }}
QLabel#logo {{ color: #ffffff; font-family: Futura, 'Avenir Next'; font-size: 14px;
               font-weight: bold; letter-spacing: 4px; }}
QLabel#dim, QLabel#status {{ color: {UI_DIM}; font-size: 11px; }}
QLabel#caption {{ color: {UI_DIM}; font-size: 9px; font-weight: 500; letter-spacing: 1.2px; }}
QLabel#edited {{ color: {UI_ACCENT}; font-size: 11px; font-weight: bold; }}
QLabel#clock {{ color: #e9e9e5; background: #0c0d0e; border: none; border-radius: 4px;
                font-family: Menlo, Monaco; font-size: 14px; font-weight: bold; padding: 5px 8px; }}
QComboBox, QPushButton, QSpinBox {{
    color: {UI_TEXT}; background: #2a2b2e; border: none;
    border-radius: 4px; padding: 5px 10px; font-size: 12px; min-height: 18px; }}
QComboBox:hover, QPushButton:hover {{ background: #37393d; }}
QPushButton:pressed {{ background: #1d1e20; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{ color: {UI_TEXT}; background: #24272b;
    selection-background-color: #3d444c; border: 1px solid #3a3f46; }}
QMenu {{ color: {UI_TEXT}; background: #24272b; border: 1px solid #3a3f46; padding: 4px; }}
QMenu::item {{ padding: 5px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: #3d444c; }}
QMenu::item:disabled {{ color: {UI_DIM}; }}
QListWidget {{ color: {UI_TEXT}; background: #0c0d0e; border: none; border-radius: 4px;
               font-size: 12px; padding: 2px; }}
QListWidget::item:selected {{ background: #37393d; color: #ffffff; }}
QLineEdit, QDoubleSpinBox {{ color: {UI_TEXT}; background: #0c0d0e; border: none; border-radius: 4px;
    padding: 6px 8px; font-size: 12px; selection-background-color: #3d444c; }}
QScrollArea {{ border: none; background: #0c0d0e; }}
QScrollBar:vertical {{ background: #101113; width: 11px; }}
QScrollBar::handle:vertical {{ background: #3a3f46; border-radius: 5px; min-height: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ color: {UI_TEXT}; background: #24272b; border: 1px solid #3a3f46; }}
"""


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("caption")
    return label


class FolderList(QWidget):
    """A built-in folder plus any number of extra ones, and which of them new files are saved in."""

    def __init__(self, builtin: Path, extra, save_to, noun: str, parent=None):
        super().__init__(parent)
        self.builtin = Path(builtin)
        self.noun = noun
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self.list = QListWidget()
        self.list.setFixedHeight(74)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        column.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton("Add Folder…")
        add.clicked.connect(self._add)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        row.addWidget(QLabel("Save new ones in"))
        self.save = QComboBox()
        self.save.setMinimumWidth(170)
        row.addWidget(self.save)
        column.addLayout(row)
        self._extra = [Path(p) for p in extra]
        self._fill(Path(save_to) if save_to else None)

    def _fill(self, save_to) -> None:
        self.list.clear()
        self.save.clear()
        self.list.addItem(f"{tidy_path(self.builtin)}   (main)")
        self.save.addItem(self.builtin.name or "main", None)
        for path in self._extra:
            self.list.addItem(tidy_path(path))
            self.save.addItem(path.name or str(path), str(path))
        self.save.setCurrentIndex(max(0, self.save.findData(str(save_to) if save_to else None)))

    def _add(self) -> None:
        path = QFileDialog.getExistingDirectory(self, f"Also look for {self.noun} in", str(Path.home()))
        if path and Path(path) != self.builtin and Path(path) not in self._extra:
            self._extra.append(Path(path))
            self._fill(self.save.currentData())

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 1:                    # row 0 is the main folder
            del self._extra[row - 1]
            self._fill(self.save.currentData())

    def extra(self) -> list:
        return list(self._extra)

    def save_to(self) -> Path | None:
        data = self.save.currentData()
        return Path(data) if data else None


class SettingsDialog(QDialog):
    def __init__(self, config: AudioConfig, store: RackStore, library, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.recordings = recordings_dir()
        self.samples = FolderList(library.root, library.extra, library.save_to, "samples")
        self.racks = FolderList(store.racks_dir, store.extra_dirs, store.save_dir, "racks")
        self.setMinimumWidth(560)
        ins, outs = list_devices()
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 16)
        form.setVerticalSpacing(12)

        def device_combo(devices, current):
            combo = QComboBox()
            default = next((d["name"] for d in devices if d["default"]), "none")
            combo.addItem(f"System Default ({default})", None)
            for dev in devices:
                combo.addItem(f"{dev['name']}  ({dev['channels']} ch)", dev["name"])
            combo.setCurrentIndex(max(0, combo.findData(current)))
            return combo

        self.output = device_combo(outs, config.output_device)
        self.input = device_combo(ins, config.input_device)
        self.channel = QSpinBox()
        self.channel.setRange(1, 64)
        self.channel.setValue(config.input_channel)
        self.rate = QComboBox()
        self.rate.addItem("Match device", 0)
        for sr in SAMPLE_RATES:
            self.rate.addItem(f"{sr / 1000:g} kHz", sr)
        self.rate.setCurrentIndex(self.rate.findData(config.sample_rate))
        self.block = QComboBox()
        for size in BLOCK_SIZES:
            self.block.addItem(f"{size} samples", size)
        self.block.setCurrentIndex(self.block.findData(config.block_size))
        form.addRow("Output device", self.output)
        form.addRow("Input device (Line In)", self.input)
        form.addRow("Line In listens to input", self.channel)
        form.addRow("Sample rate", self.rate)
        form.addRow("Buffer size", self.block)
        folder = QHBoxLayout()
        self.folder_label = QLabel(tidy_path(self.recordings))
        self.folder_label.setToolTip("Where ● takes and Reel bounces are saved")
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose_folder)
        folder.addWidget(self.folder_label, 1)
        folder.addWidget(choose)
        form.addRow("Recordings folder", folder)
        form.addRow("Sample folders", self.samples)
        form.addRow("Rack folders", self.racks)
        hint = QLabel("Samples and racks are found by name, in the order listed; the main folder "
                      "comes first. In a sample folder, each subfolder is a pack.")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        form.addRow(hint)
        note = QLabel("The input device is only opened while a Line In module is patched. "
                      "To feed the pedalboard app, send the output to BlackHole and pick "
                      "BlackHole as its Live Input.")
        note.setObjectName("dim")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _choose_folder(self) -> None:
        path = choose_recordings_folder(self, self.recordings)
        if path:
            self.recordings = path
            self.folder_label.setText(tidy_path(path))

    def result_config(self) -> AudioConfig:
        return AudioConfig(self.input.currentData(), self.output.currentData(),
                           self.channel.value(), self.rate.currentData(),
                           self.block.currentData())


def choose_recordings_folder(parent, current: Path) -> Path | None:
    start = current if current.is_dir() else current.parent if current.parent.is_dir() else Path.home()
    path = QFileDialog.getExistingDirectory(parent, "Save recordings in", str(start))
    return Path(path) if path else None


def default_config() -> AudioConfig:
    """First-run guess: a Scarlett interface with the instrument on input 2,
    as on the pedalboard. Output stays on the system default."""
    ins, _ = list_devices()
    cfg = AudioConfig()
    scarlett = next((d for d in ins if d["name"].startswith("Scarlett")), None)
    if scarlett:
        cfg.input_device = scarlett["name"]
        cfg.input_channel = 2 if scarlett["channels"] >= 2 else 1
    return cfg


class MainWindow(QMainWindow):
    def __init__(self, store: RackStore | None = None):
        super().__init__()
        self.store = store or RackStore()
        self.engine = AudioEngine()
        self.rack_name = self.store.factory_names()[0]
        self._loading = False
        self._note = ("", 0.0)
        self.setWindowTitle("Synth Rack")
        self.setStyleSheet(STYLE)

        self.rack = RackView(lambda: self.engine.sr, self.engine.transport)
        self.rack.patch_changed.connect(self._patch_changed)
        self.rack.edited.connect(self._mark_edited)
        self.rack.need_engine.connect(self._ensure_engine)
        self.rack.need_play.connect(lambda: self._play(True))
        self.rack.sample_renamed.connect(lambda old, new: self.store.rename_sample(old, new))

        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_bar())
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.rack)
        column.addWidget(self.scroll, 1)
        column.addWidget(self._build_shelf())
        self.setCentralWidget(central)

        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        width, height = 1440, 72 + 2 * ROW_H + 116
        if avail is not None:
            width, height = min(width, avail.width()), min(height, avail.height() - 28)
        self.resize(width, height)

        QShortcut(QKeySequence.StandardKey.Save, self, activated=self._save)
        QApplication.instance().installEventFilter(self)

        self._restore_session()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # -- construction -------------------------------------------------
    def _build_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("bar")
        bar.setFixedHeight(72)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 2, 18, 2)
        row.setSpacing(10)

        logo = QLabel("SYNTH RACK")
        logo.setObjectName("logo")
        row.addWidget(logo)
        row.addSpacing(6)

        self.power = PowerButton()
        self.power.toggled.connect(self._power)
        row.addWidget(self.power)
        row.addSpacing(8)

        self.play = TransportButton("play")
        self.play.setToolTip("Play / stop (Space)")
        self.play.toggled.connect(self._play)
        row.addWidget(self.play)
        self.rec = TransportButton("rec")
        self.rec.toggled.connect(self._record)
        self.rec.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.rec.customContextMenuRequested.connect(self._recordings_menu)
        row.addWidget(self.rec)
        self.clock = QLabel("104.0  1.1")
        self.clock.setObjectName("clock")
        self.clock.setFixedWidth(118)
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.clock)

        self.tempo = Knob("Tempo", 0.5, (120 - BPM_MIN) / (BPM_MAX - BPM_MIN), UI_TEXT, 30,
                          formatter=lambda t: f"{self.engine.transport.bpm:g} bpm")
        self.tempo.on_type = self._type_tempo
        self.tempo.setToolTip("Click to type a tempo · drag up or down to turn\nOption-click for 120")
        self.tempo.changed.connect(self._tempo_changed)
        row.addWidget(self.tempo)
        self.swing = Knob("Swing", 0.0, 0.0, UI_TEXT, 30,
                          formatter=lambda t: f"{100 * t:.0f}%")
        self.swing.changed.connect(self._swing_changed)
        row.addWidget(self.swing)
        row.addStretch(1)

        preset_box = QVBoxLayout()
        preset_box.setSpacing(3)
        head = QHBoxLayout()
        head.addWidget(_caption("RACK"))
        self.edited_label = QLabel("")
        self.edited_label.setObjectName("edited")
        head.addWidget(self.edited_label)
        head.addStretch(1)
        preset_box.addLayout(head)
        line = QHBoxLayout()
        line.setSpacing(6)
        self.presets = QComboBox()
        self.presets.setFixedWidth(210)
        self.presets.activated.connect(lambda _: self._load_rack(self.presets.currentData()))
        line.addWidget(self.presets)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        line.addWidget(save)
        more = QPushButton("⋯")
        more.setFixedWidth(38)
        menu = QMenu(more)
        menu.addAction("Save As…", self._save_as)
        menu.addAction("Revert to Saved", lambda: self._load_rack(self.rack_name))
        menu.addSeparator()
        menu.addAction("Delete Rack", self._delete_rack)
        more.setMenu(menu)
        line.addWidget(more)
        preset_box.addLayout(line)
        row.addLayout(preset_box)

        skin_box = QVBoxLayout()
        skin_box.setSpacing(3)
        skin_box.addWidget(_caption("CASE"))
        self.skins = QComboBox()
        for skin in RACK_SKINS:
            self.skins.addItem(skin.title(), skin)
        self.skins.activated.connect(lambda _: self.rack.set_skin(self.skins.currentData()))
        skin_box.addWidget(self.skins)
        row.addLayout(skin_box)
        row.addStretch(1)

        self.in_meter, self.out_meter = LevelMeter(), LevelMeter()
        meters = QVBoxLayout()
        meters.setSpacing(4)
        for text, meter in (("IN", self.in_meter), ("OUT", self.out_meter)):
            line = QHBoxLayout()
            label = _caption(text)
            label.setFixedWidth(26)
            line.addWidget(label)
            line.addWidget(meter)
            meters.addLayout(line)
        self.status = QLabel("Engine off")
        self.status.setObjectName("status")
        self.status.setFixedWidth(210)
        meters.addWidget(self.status)
        row.addLayout(meters)
        lo, hi = -36.0, 12.0
        self.out_knob = Knob("Master", (0 - lo) / (hi - lo), (0 - lo) / (hi - lo), UI_TEXT, 30,
                             formatter=lambda t: f"{lo + (hi - lo) * t:+.1f} dB")
        self.out_knob.changed.connect(lambda t: setattr(self.engine, "master_db", lo + (hi - lo) * t))
        row.addWidget(self.out_knob)

        self.cables = QPushButton("Cables")
        self.cables.setToolTip("Show, dim or hide the patch cables (C)")
        self.cables.clicked.connect(self._cycle_cables)
        row.addWidget(self.cables)
        settings = QPushButton("Settings…")
        settings.setToolTip("Audio devices, and the folders for recordings, samples and racks")
        settings.clicked.connect(self._open_settings)
        row.addWidget(settings)
        return bar

    def _build_shelf(self) -> QWidget:
        shelf = QWidget()
        shelf.setObjectName("shelf")
        column = QVBoxLayout(shelf)
        column.setContentsMargins(0, 5, 0, 0)
        column.setSpacing(0)
        hint = _caption("SPACE  PLAY      CLICK A MODULE, THEN  A W S E D F T G Y H U J K  PLAY IT      "
                        "Z X  OCTAVE      C  CABLES      DRAG JACK TO JACK TO PATCH")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(hint)
        column.addWidget(ModuleBrowser(self.rack))
        return shelf

    # -- keyboard -----------------------------------------------------
    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget):
            self._select_module_under(obj)    # clicking anything on a module makes it the played one
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and self._keys_are_ours(event):
            if self.handle_key(event.key(), kind == QEvent.Type.KeyPress, event.isAutoRepeat(),
                               event.modifiers()):
                return True
        return super().eventFilter(obj, event)

    def _select_module_under(self, widget) -> None:
        while widget is not None and widget is not self.rack:
            if isinstance(widget, ModuleWidget) and widget in self.rack.widgets:
                self.rack.select(widget)
                return
            widget = widget.parentWidget()

    def _keys_are_ours(self, event) -> bool:
        if not self.isActiveWindow() or QApplication.activePopupWidget() is not None:
            return False
        if isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox)):
            return False
        blocked = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
                   | Qt.KeyboardModifier.AltModifier)
        return not (event.modifiers() & blocked)

    def handle_key(self, key, down: bool, repeat: bool = False,
                   mods=Qt.KeyboardModifier.NoModifier) -> bool:
        """Space is the transport; [ and ] pick a module; everything else goes
        to the selected module (its pads, its keyboard)."""
        if repeat:
            return True
        if key == Qt.Key.Key_Space:
            if down:
                self._play(not self.engine.transport.playing or not self.engine.running)
            return True
        if key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
            if down:
                self.rack.select_step(1 if key == Qt.Key.Key_BracketRight else -1)
                self._show_selected()
            return True
        if key == Qt.Key.Key_C:
            if down:
                self._cycle_cables()
            return True
        selected = self.rack.selected
        if selected is not None and selected.key(key, down, mods):
            if down:
                self._ensure_engine()
            return True
        return False

    def _cycle_cables(self) -> None:
        view = self.rack.cycle_cable_view()
        self.cables.setText(("Cables", "Cables ◐", "Cables ○")[view])

    def _show_selected(self) -> None:
        if self.rack.selected is not None:
            self.scroll.ensureWidgetVisible(self.rack.selected, 0, 4)

    # -- transport ----------------------------------------------------
    def _bpm_of(self, t: float) -> float:
        return round(BPM_MIN + (BPM_MAX - BPM_MIN) * t)

    def _tempo_changed(self, t: float) -> None:
        self.engine.transport.bpm = self._bpm_of(t)
        self._mark_edited()

    def _type_tempo(self) -> None:
        bpm, ok = QInputDialog.getDouble(self, "Tempo", "Beats per minute:", self.engine.transport.bpm,
                                         BPM_MIN, BPM_MAX, 1)
        if ok:
            self.set_bpm(bpm)

    def set_bpm(self, bpm: float) -> None:
        """Set an exact tempo (the knob itself moves in whole beats per minute)."""
        bpm = round(min(BPM_MAX, max(BPM_MIN, float(bpm))), 1)
        self._set_tempo(bpm, self.engine.transport.swing)
        self.tempo.update()
        self._mark_edited()

    def _swing_changed(self, t: float) -> None:
        self.engine.transport.swing = t * SWING_MAX
        self._mark_edited()

    def _set_tempo(self, bpm: float, swing: float) -> None:
        transport = self.engine.transport
        transport.bpm, transport.swing = bpm, swing
        self.tempo.set_norm((bpm - BPM_MIN) / (BPM_MAX - BPM_MIN))
        self.swing.set_norm(swing / SWING_MAX)

    def _play(self, on: bool) -> None:
        if on:
            self._ensure_engine()
            if self.engine.running:
                self.engine.transport.play()
        else:
            self.engine.transport.stop()

    def _record(self, on: bool) -> None:
        if on:
            self._ensure_engine()
            if self.engine.running:
                self.engine.start_recording()
        else:
            audio = self.engine.stop_recording()
            if audio is not None and audio.shape[1] > self.engine.sr // 4:
                path = recordings_dir() / f"take-{time.strftime('%Y%m%d-%H%M%S')}.wav"
                try:
                    write_wav(path, audio, self.engine.sr)
                    self.say(f"Saved {path.name} in {tidy_path(path.parent)}")
                except Exception as exc:
                    QMessageBox.warning(self, "Recording", f"Couldn't save the take:\n\n{exc}")
        self.rec.set_on(self.engine.recording)

    # -- where recordings go ----------------------------------------------
    def set_recordings_folder(self, path) -> None:
        racks.set_recordings_dir(path)
        self.rec.setToolTip(f"Record the main output to {tidy_path(recordings_dir())}\n"
                            "Right-click to choose or open the folder")
        self._save_settings()

    def set_folders(self, sample_folders=(), samples_save=None, rack_folders=(), racks_save=None) -> None:
        """Extra places to look for samples and racks, and where new ones are saved."""
        LIBRARY.configure(sample_folders, samples_save)
        self.store.configure(rack_folders, racks_save)
        self._save_settings()
        self._refresh_presets()
        for widget in self.rack.widgets:
            widget.refresh()

    def _save_settings(self) -> None:
        try:
            self.store.save_settings({
                "recordings_dir": str(racks._recordings) if racks._recordings else None,
                "sample_folders": [str(p) for p in LIBRARY.extra],
                "samples_save_to": str(LIBRARY.save_to) if LIBRARY.save_to else None,
                "rack_folders": [str(p) for p in self.store.extra_dirs],
                "racks_save_to": str(self.store.save_dir) if self.store.save_dir else None,
            })
        except OSError:
            pass

    def _load_settings(self, session: dict) -> None:
        settings = self.store.load_settings()
        # the recordings folder used to be kept in the session file
        racks.set_recordings_dir(settings.get("recordings_dir") or session.get("recordings_dir"))
        self.rec.setToolTip(f"Record the main output to {tidy_path(recordings_dir())}\n"
                            "Right-click to choose or open the folder")
        LIBRARY.configure(settings.get("sample_folders") or (), settings.get("samples_save_to"))
        self.store.configure(settings.get("rack_folders") or (), settings.get("racks_save_to"))

    def _recordings_menu(self, pos) -> None:
        menu = QMenu(self)
        where = menu.addAction(f"Recordings go to {tidy_path(recordings_dir())}")
        where.setEnabled(False)
        choose = menu.addAction("Choose Recordings Folder…")
        show = menu.addAction("Show Recordings Folder")
        chosen = menu.exec(self.rec.mapToGlobal(pos))
        if chosen is choose:
            path = choose_recordings_folder(self, recordings_dir())
            if path:
                self.set_recordings_folder(path)
        elif chosen is show:
            recordings_dir().mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(recordings_dir())))

    def say(self, text: str) -> None:
        """Show a message in the status line for a few seconds."""
        self._note = (text, time.monotonic())

    # -- racks --------------------------------------------------------
    def _refresh_presets(self) -> None:
        self.presets.clear()
        for name in self.store.user_names():
            self.presets.addItem(name, name)
        if self.presets.count():
            self.presets.insertSeparator(self.presets.count())
        user = set(self.store.user_names())
        for name in self.store.factory_names():
            if name not in user:
                self.presets.addItem(f"{name}  (factory)", name)
        self.presets.setCurrentIndex(self.presets.findData(self.rack_name))

    def _apply_rack(self, data: dict, assets=None) -> None:
        self._loading = True
        self.engine.transport.stop()
        skin = data.get("skin", "graphite")
        self.rack.skin = skin if skin in RACK_SKINS else "graphite"
        self.skins.setCurrentIndex(self.skins.findData(self.rack.skin))
        self._set_tempo(*rack_tempo(data))
        modules, cables = build_rack(data, self.engine.sr, assets)
        self.rack.set_rack(modules, cables)
        self._loading = False

    def _load_rack(self, name: str | None) -> None:
        if not name:
            return
        try:
            data = self.store.load(name)
        except KeyError:
            return
        self.rack_name = name
        self._apply_rack(data, self.store.load_assets_dir(name))
        self._refresh_presets()
        self.edited_label.setText("")

    def _mark_edited(self) -> None:
        if not self._loading:
            self.edited_label.setText("● edited")

    def _current_rack(self, name: str) -> dict:
        transport = self.engine.transport
        return rack_to_dict(name, self.rack.modules(), self.rack.cables, self.rack.skin,
                            transport.bpm, transport.swing)

    def _save(self) -> None:
        if not self.store.is_user(self.rack_name):
            return self._save_as()  # factory racks are never overwritten
        self.store.save(self._current_rack(self.rack_name), self.rack.modules())
        self.edited_label.setText("")

    def _save_as(self) -> None:
        suggestion = self.rack_name if self.store.is_user(self.rack_name) else f"My {self.rack_name}"
        name, ok = QInputDialog.getText(self, "Save Rack", "Rack name:", text=suggestion)
        name = name.strip()
        if not ok or not name:
            return
        self.store.save(self._current_rack(name), self.rack.modules())
        self.rack_name = name
        self._refresh_presets()
        self.edited_label.setText("")

    def _delete_rack(self) -> None:
        name = self.rack_name
        if not self.store.is_user(name):
            QMessageBox.information(self, "Delete Rack", "Factory racks can't be deleted.")
            return
        if QMessageBox.question(self, "Delete Rack", f"Delete “{name}”?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(name)
        self._load_rack(self.store.factory_names()[0])

    # -- audio --------------------------------------------------------
    def _patch_changed(self) -> None:
        self.engine.set_patch(self.rack.modules(), self.rack.cables)
        if self.engine.running and not self.engine.stream_matches_patch:
            self._power(True)      # Line In was patched or unpatched: reopen with / without input

    def _power(self, on: bool) -> None:
        if on:
            try:
                self.engine.start()
            except Exception as exc:
                self.engine.stop()
                QMessageBox.warning(self, "Audio", f"Couldn't start audio:\n\n{exc}\n\n"
                                    "Check the devices under Audio… and try again.")
        else:
            self.engine.transport.stop()
            if self.engine.recording:
                self._record(False)
            self.engine.stop()
        self.power.set_on(self.engine.running)

    def _ensure_engine(self) -> None:
        if not self.engine.running:
            self._power(True)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.engine.config, self.store, LIBRARY, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.engine.config = dialog.result_config()
            if dialog.recordings != recordings_dir():
                self.set_recordings_folder(dialog.recordings)
            self.set_folders(dialog.samples.extra(), dialog.samples.save_to(),
                             dialog.racks.extra(), dialog.racks.save_to())
            if self.engine.running:
                self._power(True)

    def _tick(self) -> None:
        engine = self.engine
        transport = engine.transport
        in_peak, out_peak = engine.in_peak, engine.out_peak
        engine.in_peak = engine.out_peak = 0.0
        self.in_meter.feed(in_peak)
        self.out_meter.feed(out_peak)
        self.play.set_on(transport.playing and engine.running)
        self.rec.set_on(engine.recording)
        step = transport.step
        position = f"{step // 16 + 1}.{step % 16 // 4 + 1}" if transport.playing and step >= 0 else "–.–"
        self.clock.setText(f"{transport.bpm:5.1f}  {position}")
        note, when = self._note
        if engine.last_error:
            self.status.setText(f"DSP error: {engine.last_error}"[:64])
        elif time.monotonic() - when < 4.0:
            self.status.setText(note)
        elif engine.recording:
            self.status.setText(f"● Recording  {engine.recorded_seconds():.0f} s")
        elif engine.running:
            cfg = engine.config
            xruns = f" · {engine.xruns} late" if engine.xruns else ""
            self.status.setText(f"{engine.sr / 1000:g} kHz · {cfg.block_size} · "
                                f"{engine.latency_ms:.0f} ms · CPU {engine.cpu_load * 100:.0f}%{xruns}")
        else:
            self.status.setText("Engine off · press Space to play")
        for widget in self.rack.widgets:
            widget.tick()

    # -- session ------------------------------------------------------
    def _restore_session(self) -> None:
        session = self.store.load_session()
        self._load_settings(session)
        self.engine.config = AudioConfig.from_dict(session["audio"]) if "audio" in session \
            else default_config()
        if self.engine.config.sample_rate:
            self.engine.set_sample_rate(self.engine.config.sample_rate)
        lo, hi = -36.0, 12.0
        master = min(hi, max(lo, float(session.get("master_db", 0.0))))
        self.engine.master_db = master
        self.out_knob.set_norm((master - lo) / (hi - lo))
        rack = session.get("rack")
        self.rack_name = session.get("name", self.rack_name)
        if rack:
            self._apply_rack(rack, self.store.session_assets)
            self._refresh_presets()
            self.edited_label.setText("● edited" if session.get("edited") else "")
        else:
            self._load_rack(self.store.factory_names()[0])

    def save_session(self) -> None:
        self.store.save_session({
            "version": __version__,
            "audio": self.engine.config.to_dict(),
            "master_db": self.engine.master_db,
            "name": self.rack_name,
            "edited": bool(self.edited_label.text()),
            "rack": self._current_rack(self.rack_name),
        }, self.rack.modules())

    def closeEvent(self, event):
        self._timer.stop()
        QApplication.instance().removeEventFilter(self)
        if self.engine.recording:
            self._record(False)
        self.rack.shutdown()
        self.engine.stop()
        try:
            self.save_session()
        except OSError:
            pass
        super().closeEvent(event)
