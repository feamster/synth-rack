"""The sound browser: packs on the left, their sounds on the right, a search box.

Clicking a sound plays it on the track it is for (through that track's own
filter and pitch, with the pattern still running), so what you hear is what
you get. Use keeps it; Cancel puts the old sound back.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ..dsp.library import AUDIO_SUFFIXES, leaf, pack_of
from ..racks import tidy_path

ALL = "All sounds"
MAX_SHOWN = 1500         # a list longer than this is not for reading; search instead
NAME = Qt.ItemDataRole.UserRole


class SoundBrowser(QDialog):
    previewed = pyqtSignal(str)          # a sound was clicked: play it

    def __init__(self, library, current: str = "", title: str = "Sounds", parent=None):
        super().__init__(parent)
        self.library = library
        self.chosen = current
        self.setWindowTitle(title)
        self.resize(620, 470)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search every pack")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill_sounds)
        self.packs = QListWidget()
        self.packs.setFixedWidth(210)
        self.packs.currentRowChanged.connect(lambda _: self._fill_sounds())
        self.sounds = QListWidget()
        self.sounds.currentItemChanged.connect(self._clicked)
        self.sounds.itemDoubleClicked.connect(lambda _: self.accept())
        self.where = QLabel("")
        self.where.setObjectName("dim")
        # a long path must not widen the window
        self.where.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for box in (self.packs, self.sounds):
            box.setStyleSheet("QListWidget::item { padding: 3px 5px; border-radius: 3px; }")

        lists = QHBoxLayout()
        lists.setSpacing(8)
        lists.addWidget(self.packs)
        lists.addWidget(self.sounds, 1)

        add_file = QPushButton("Add File…")
        add_file.setToolTip("Copy an audio file into your samples folder")
        add_file.clicked.connect(self._add_file)
        add_pack = QPushButton("Add Pack…")
        add_pack.setToolTip("Copy a whole folder of audio into your samples folder as a pack")
        add_pack.clicked.connect(self._add_pack)
        reveal = QPushButton("Show in Finder")
        reveal.clicked.connect(self._reveal)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        use = QPushButton("Use")
        use.setDefault(True)
        use.clicked.connect(self.accept)
        for button in (add_file, add_pack, reveal, cancel):
            button.setAutoDefault(False)
        buttons = QHBoxLayout()
        for button in (add_file, add_pack, reveal):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(use)

        column = QVBoxLayout(self)
        column.setContentsMargins(14, 14, 14, 12)
        column.setSpacing(8)
        column.addWidget(self.search)
        column.addLayout(lists, 1)
        column.addWidget(self.where)
        column.addLayout(buttons)
        self.reload(current)

    # -- filling the lists --------------------------------------------
    def reload(self, select: str = "") -> None:
        """Read the library again and show the pack that holds ``select``."""
        self.groups = self.library.groups()
        want = pack_of(select) if select else self.current_pack()
        self.packs.blockSignals(True)
        self.packs.clear()
        total = sum(len(names) for names in self.groups.values())
        for pack, count in ((ALL, total), *((k, len(v)) for k, v in self.groups.items())):
            item = QListWidgetItem(f"{pack}   {count}")
            item.setData(NAME, pack)
            self.packs.addItem(item)
        rows = self.pack_names()
        self.packs.setCurrentRow(rows.index(want) if want in rows else 1)
        self.packs.blockSignals(False)
        self._fill_sounds(select=select)

    def pack_names(self) -> list[str]:
        return [self.packs.item(i).data(NAME) for i in range(self.packs.count())]

    def current_pack(self) -> str:
        item = self.packs.currentItem()
        return item.data(NAME) if item is not None else ALL

    def shown(self) -> list[str]:
        """The sound names in the right-hand list, in order."""
        return [self.sounds.item(i).data(NAME) for i in range(self.sounds.count())
                if self.sounds.item(i).data(NAME)]

    def _fill_sounds(self, *_, select: str = "") -> None:
        words = self.search.text().lower().split()
        pack = self.current_pack()
        everywhere = bool(words) or pack == ALL          # a search looks in every pack
        names = [n for group in self.groups.values() for n in group] if everywhere \
            else list(self.groups.get(pack, ()))
        if words:
            names = [n for n in names if all(w in n.lower() for w in words)]
        self.sounds.blockSignals(True)
        self.sounds.clear()
        for name in names[:MAX_SHOWN]:
            item = QListWidgetItem(name.replace("/", "  /  ") if everywhere else leaf(name))
            item.setData(NAME, name)
            self.sounds.addItem(item)
            if name == (select or self.chosen):
                self.sounds.setCurrentItem(item)
        if len(names) > MAX_SHOWN:
            more = QListWidgetItem(f"… and {len(names) - MAX_SHOWN} more. Search to narrow it down.")
            more.setFlags(Qt.ItemFlag.NoItemFlags)
            self.sounds.addItem(more)
        self.sounds.blockSignals(False)
        self._describe()

    def _describe(self) -> None:
        path = self.library.path_of(self.chosen)
        self.where.setText(tidy_path(path) if path is not None else
                           "Built in (made by the app, no file)" if self.chosen else "")

    # -- choosing ---------------------------------------------------
    def _clicked(self, item, _=None) -> None:
        name = item.data(NAME) if item is not None else None
        if name:
            self.choose(name)

    def choose(self, name: str) -> None:
        self.chosen = name
        self._describe()
        self.previewed.emit(name)

    # -- adding -----------------------------------------------------
    def _add_file(self) -> None:
        patterns = " ".join(f"*{s}" for s in AUDIO_SUFFIXES)
        paths, _ = QFileDialog.getOpenFileNames(self, "Add audio files", str(Path.home()),
                                                f"Audio ({patterns});;All files (*)")
        self.add_files(paths)

    def add_files(self, paths) -> None:
        name = ""
        for path in paths:
            try:
                name = self.library.import_file(path)
            except Exception as exc:
                QMessageBox.warning(self, "Add File", f"Couldn't read {Path(path).name}:\n\n{exc}")
        if name:
            self.reload(name)
            self.choose(name)

    def _add_pack(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of sounds", str(Path.home()))
        if folder:
            self.add_pack(folder)

    def add_pack(self, folder) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pack, _count = self.library.import_pack(folder)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Add Pack", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.search.clear()
        self.reload()
        rows = self.pack_names()
        hit = next((i for i, row in enumerate(rows) if row == pack or row.startswith(pack + "/")), 0)
        self.packs.setCurrentRow(hit)

    def _reveal(self) -> None:
        path = self.library.path_of(self.chosen)
        folder = path.parent if path is not None else self.library.write_root
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
