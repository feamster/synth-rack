"""Base class for a module's faceplate in the rack."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from .theme import PANEL_H, draw_panel, finish_of, fit_font, font
from .widgets import CycleField, Jack, Knob, PadButton

HEADER_H = 30
STRIP_W = 48      # width of the jack strip down a module's right edge

PIANO_KEYS = {Qt.Key.Key_A: 0, Qt.Key.Key_W: 1, Qt.Key.Key_S: 2, Qt.Key.Key_E: 3, Qt.Key.Key_D: 4,
              Qt.Key.Key_F: 5, Qt.Key.Key_T: 6, Qt.Key.Key_G: 7, Qt.Key.Key_Y: 8, Qt.Key.Key_H: 9,
              Qt.Key.Key_U: 10, Qt.Key.Key_J: 11, Qt.Key.Key_K: 12, Qt.Key.Key_O: 13, Qt.Key.Key_L: 14,
              Qt.Key.Key_P: 15, Qt.Key.Key_Semicolon: 16}


class ModuleWidget(QWidget):
    """A faceplate built from the module's parameter list: knobs in a grid,
    choices as value windows, jacks down the right edge. Modules that need
    more subclass this and lay themselves out in ``_build``."""

    edited = pyqtSignal()
    KNOB = 32
    ACCENT = "#d9a441"      # the selected-module lamp; modules with their own accent override
    COLUMNS = 2

    def __init__(self, module, rack):
        super().__init__(rack)
        self.module = module
        self.rack = rack
        self.lifted = False
        self.selected = False
        self.controls: dict = {}
        self.jacks: dict = {}          # (kind, name) -> Jack
        self._face: QPixmap | None = None
        self._face_key = None
        self.setFixedSize(module.WIDTH, PANEL_H)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._build()

    # -- look ---------------------------------------------------------
    @property
    def fin(self) -> dict:
        return finish_of(self.module)

    @property
    def strip_x(self) -> float:
        """Centre line of the jack strip."""
        return self.width() - STRIP_W / 2.0 - 2

    # -- building blocks ---------------------------------------------
    def _center(self, widget, cx: float, top: float):
        widget.move(int(cx - widget.width() / 2), int(top))
        return widget

    def _knob(self, key: str, cx: float, top: float, dia: int | None = None, accent=None,
              label: str | None = None, cap: str | None = None) -> Knob:
        param = self.module.param(key)
        knob = Knob(label or param.label, param.to_norm(self.module.get(key)),
                    param.to_norm(param.default), self.fin["text"], dia or self.KNOB,
                    accent, lambda t, p=param: p.format(p.from_norm(t)), self, cap=cap)
        knob.changed.connect(lambda t, p=param: self._set(p.key, p.from_norm(t)))
        self.controls[key] = knob
        return self._center(knob, cx, top)

    def _field(self, key: str, x: float, top: float, width: int, label: str | None = None,
               menu: bool = False) -> CycleField:
        param = self.module.param(key)
        field = CycleField(label or param.label, param.choices, int(self.module.get(key)),
                           self.fin["text"], width, self, menu=menu)
        field.changed.connect(lambda i, k=key: self._set(k, i))
        field.move(int(x), int(top))
        self.controls[key] = field
        return field

    def _pad(self, name: str, label: str, x: float, top: float, action, hint: str = "", lit=None,
             color: str = "#e9e9e5", width: int = 50) -> PadButton:
        pad = PadButton(label, hint, lit, self, color=color, width=width)
        pad.pressed.connect(action)
        pad.move(int(x), int(top))
        self.controls[f"_pad_{name}"] = pad
        return pad

    def _jack(self, kind: str, name: str, cx: float, top: float, label: str | None = None) -> Jack:
        jack = Jack(self, kind, name, label or name, self.fin["text"], self)
        self.jacks[(kind, name)] = jack
        return self._center(jack, cx, top)

    def _jack_strip(self, top: float = 44, pitch: float = 58) -> None:
        """All of the module's jacks, inputs first, down the right edge."""
        y = top
        for name in self.module.INPUTS:
            self._jack("in", name, self.strip_x, y)
            y += pitch
        if self.module.INPUTS and self.module.OUTPUTS:
            y += 12
        for name in self.module.OUTPUTS:
            self._jack("out", name, self.strip_x, y)
            y += pitch

    def _set(self, key: str, value) -> None:
        self.module.set(key, value)
        self.edited.emit()

    def _build(self) -> None:
        params = self.module.PARAMS
        knobs = [p for p in params if not p.is_choice]
        choices = [p for p in params if p.is_choice]
        usable = self.width() - STRIP_W - 16
        y = HEADER_H + 10
        for param in choices:
            self._field(param.key, 12, y, int(usable))
            y += 44
        cell = usable / self.COLUMNS
        for i, param in enumerate(knobs):
            self._knob(param.key, 12 + cell * (i % self.COLUMNS + 0.5), y + (i // self.COLUMNS) * 66)
        self._jack_strip(top=96, pitch=110)

    def rebuild(self) -> None:
        """Recreate the controls (after a finish change)."""
        for widget in [*self.controls.values(), *self.jacks.values()]:
            widget.setParent(None)
            widget.deleteLater()
        self.controls, self.jacks = {}, {}
        self._build()
        for widget in [*self.controls.values(), *self.jacks.values()]:
            widget.show()
        self.refresh()

    def refresh(self) -> None:
        """Pull every control's position back from the module's values."""
        for param in self.module.PARAMS:
            widget = self.controls.get(param.key)
            if isinstance(widget, Knob):
                widget.set_norm(param.to_norm(self.module.get(param.key)))
            elif isinstance(widget, CycleField):
                widget.set_index(int(self.module.get(param.key)))
        self.update()

    # -- hooks --------------------------------------------------------
    def tick(self) -> None:
        """Called ~30 times a second for meters, lamps and screens."""

    def key(self, key, down: bool, mods) -> bool:
        """Keyboard input while this module is selected. True if handled."""
        return False

    def menu_actions(self, menu) -> dict:
        """Extra context-menu entries: {QAction: callable}."""
        return {}

    def set_selected(self, selected: bool) -> None:
        if selected != self.selected:
            self.selected = selected
            self.update()

    def shutdown(self) -> None:
        """Called when the module leaves the rack."""

    # -- dragging is delegated to the rack --------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.rack.begin_drag(self, e.globalPosition())
        e.accept()

    def mouseMoveEvent(self, e):
        self.rack.drag_to(self, e.globalPosition())
        e.accept()

    def mouseReleaseEvent(self, e):
        self.rack.end_drag(self)
        e.accept()

    def contextMenuEvent(self, e):
        self.rack.module_menu(self, e.globalPos())

    def moveEvent(self, _):
        rack = getattr(self, "rack", None)
        if rack is not None:
            rack.cables_moved()

    # -- painting -----------------------------------------------------
    def _paint_key(self) -> tuple:
        """Everything the painted face depends on (controls paint themselves)."""
        return (self.lifted, self.selected, self.module.finish)

    def paintEvent(self, _):
        # The face is static between interactions, so it is rendered once and
        # blitted; that keeps repaints cheap while the audio thread wants the GIL.
        key = (self._paint_key(), self.devicePixelRatioF())
        if self._face is None or self._face_key != key:
            dpr = self.devicePixelRatioF()
            self._face = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            self._face.setDevicePixelRatio(dpr)
            self._face.fill(Qt.GlobalColor.transparent)
            painter = QPainter(self._face)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_face(painter)
            painter.end()
            self._face_key = key
        QPainter(self).drawPixmap(0, 0, self._face)

    def _paint_face(self, p: QPainter) -> None:
        fin = self.fin
        rect = QRectF(0, 0, self.width(), self.height())
        draw_panel(p, rect, QColor(fin["body"]), self.lifted)
        text = QColor(fin["text"])
        name = self.module.NAME.upper()
        room = self.width() - 44
        wide = self.width() >= 300
        p.setPen(text)
        accent = QColor(getattr(self.module, "ACCENT", self.ACCENT))
        if wide:
            p.setFont(font(13, bold=True, family="logo", spacing=3.5))
            p.drawText(QRectF(22, 4, room, HEADER_H - 4), Qt.AlignmentFlag.AlignVCenter, name)
            dim = QColor(text)
            dim.setAlpha(120)
            p.setPen(dim)
            p.setFont(font(8, medium=True, spacing=1.6))
            p.drawText(QRectF(22, 4, room, HEADER_H - 4),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       self.module.TAGLINE.upper())
        else:
            p.setFont(fit_font(name, room, 12, bold=True, family="logo", spacing=2.0))
            p.drawText(QRectF(22, 4, room, HEADER_H - 4), Qt.AlignmentFlag.AlignCenter, name)
        if self.selected:       # a short accent line under the name: the keyboard plays this module
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            x = 22.0 if wide else self.width() / 2.0 - 9.0
            p.drawRect(QRectF(x, HEADER_H - 1, 18, 2))
        if self.jacks and self.width() >= 160:   # hairline setting off the jack strip
            x = self.width() - STRIP_W - 4.5
            line = QColor(text)
            line.setAlpha(34)
            p.setPen(QPen(line, 1))
            p.drawLine(QPointF(x, HEADER_H + 10), QPointF(x, self.height() - 26))
        self._paint_details(p)

    def _paint_details(self, p: QPainter) -> None:
        """Extra static artwork for subclasses."""

    def caption(self, p: QPainter, text: str, rect: QRectF, align=Qt.AlignmentFlag.AlignCenter) -> None:
        color = QColor(self.fin["text"])
        color.setAlpha(150)
        p.setPen(color)
        p.setFont(font(8, medium=True, spacing=1.2))
        p.drawText(rect, align, text.upper())
