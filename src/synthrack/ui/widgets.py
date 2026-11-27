"""Custom-painted controls: encoders, pads, jacks, step keys, piano keys, meters.

Everything is flat: one fill, one hairline, one accent. Controls take the
panel's lettering colour so they sit on dark and light faceplates alike.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QMenu, QWidget

from .theme import KEY, KEY_LIGHT, RED, SCREEN_BG, UI_DIM, draw_jack, draw_led, fit_font, font, is_light

ROUND = (Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
FLAT = (Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)


def _alpha(color, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


class Knob(QWidget):
    """A flat encoder with a value arc. Drag up/down (Shift = fine), scroll,
    double-click or Option-click to reset. ``cap`` overrides the cap colour.
    With ``on_type`` set, a plain click (no drag) asks for a typed value."""

    HINT = "Drag up or down · Shift for fine steps\nDouble-click or Option-click to reset"

    changed = pyqtSignal(float)  # normalised 0..1

    def __init__(self, label: str, norm: float = 0.5, default: float = 0.5,
                 text_color: str = "#ffffff", diameter: int = 32, accent: str | None = None,
                 formatter=None, parent=None, cap: str | None = None):
        super().__init__(parent)
        self.label = label
        self.norm = norm
        self.default = default
        self.text_color = QColor(text_color)
        self.diameter = diameter
        self.accent = QColor(accent) if accent else None
        self.cap = QColor(cap) if cap else None
        self.formatter = formatter  # norm -> display string
        self.locked = False         # showing a per-step parameter lock
        self.on_reset = None        # callable -> True if it handled the double-click
        self.on_type = None         # callable: a plain click wants to type the value
        self._drag = None
        self._moved = False
        self.setToolTip(self.HINT)
        self._hover = False
        self.setFixedSize(diameter + 30, diameter + 34)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return self.size()

    def set_norm(self, norm: float, emit: bool = False) -> None:
        norm = min(1.0, max(0.0, norm))
        if norm != self.norm:
            self.norm = norm
            self.update()
            if emit:
                self.changed.emit(norm)

    def set_label(self, label: str) -> None:
        if label != self.label:
            self.label = label
            self.update()

    def set_locked(self, locked: bool) -> None:
        if locked != self.locked:
            self.locked = locked
            self.update()

    # -- interaction --------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if e.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.reset()
                return e.accept()
            self._drag = (e.globalPosition().y(), self.norm)
            self._moved = False
            self.update()
        e.accept()

    def reset(self) -> None:
        """Back to the default (or, on a held step, drop the lock)."""
        if not (self.on_reset and self.on_reset()):
            self.set_norm(self.default, emit=True)

    def mouseMoveEvent(self, e):
        if self._drag:
            y0, n0 = self._drag
            if abs(y0 - e.globalPosition().y()) > 2:
                self._moved = True
            span = 900.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 170.0
            self.set_norm(n0 + (y0 - e.globalPosition().y()) / span, emit=True)
        e.accept()

    def mouseReleaseEvent(self, e):
        clicked = self._drag is not None and not self._moved
        self._drag = None
        self.update()
        e.accept()
        if clicked and self.on_type is not None:
            self.on_type()

    def mouseDoubleClickEvent(self, e):
        if self.on_type is None:        # there, the first click already opened the typing box
            self.reset()
        e.accept()

    def wheelEvent(self, e):
        delta = e.angleDelta().y() or e.angleDelta().x()
        if delta:
            self.set_norm(self.norm + (0.02 if delta > 0 else -0.02), emit=True)
        e.accept()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    # -- painting -----------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.diameter / 2.0 - 3.0
        c = QPointF(self.width() / 2.0, 9 + self.diameter / 2.0)
        on_light = not is_light(self.text_color)       # dark lettering means a light panel
        arc_rect = QRectF(c.x() - r - 3.5, c.y() - r - 3.5, 2 * r + 7, 2 * r + 7)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_alpha(self.text_color, 46), 1.6, *FLAT))
        p.drawArc(arc_rect, 225 * 16, -270 * 16)
        arc = QColor(RED) if self.locked else (self.accent or self.text_color)
        if self.norm > 0.003:
            p.setPen(QPen(arc, 2.0, *FLAT))
            p.drawArc(arc_rect, 225 * 16, int(-270 * 16 * self.norm))

        cap = self.cap or QColor("#26272a" if on_light else "#3b3d42")
        p.setPen(QPen(QColor(0, 0, 0, 60) if on_light else QColor(255, 255, 255, 30), 1.0))
        p.setBrush(cap)
        p.drawEllipse(c, r - 1.0, r - 1.0)
        ang = math.radians(225 - 270 * self.norm)
        d = QPointF(math.cos(ang), -math.sin(ang))
        pointer = QColor("#1c1d1f") if is_light(cap) else QColor("#f2f2ee")
        p.setPen(QPen(pointer, 1.8, *ROUND))
        p.drawLine(c + d * (r * 0.35), c + d * (r - 3.0))

        active = self._drag is not None or self._hover
        if active and self.formatter:
            p.setPen(self.text_color)
            p.setFont(font(9, bold=True))
            text = self.formatter(self.norm)
        else:
            p.setPen(_alpha(self.text_color, 190))
            p.setFont(font(9, medium=True, spacing=0.9))
            text = self.label.upper()
        p.drawText(QRectF(-10, 9 + self.diameter + 6, self.width() + 20, 14),
                   Qt.AlignmentFlag.AlignCenter, text)


class LevelMeter(QWidget):
    """Thin horizontal peak meter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.setFixedSize(108, 5)

    def feed(self, peak: float) -> None:
        db = 20.0 * math.log10(max(peak, 1e-5))
        target = min(1.0, max(0.0, (db + 54.0) / 54.0))
        level = target if target > self.level else max(target, self.level - 0.035)
        if level != self.level:
            self.level = level
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(QRectF(0, 0, w, h), QColor(255, 255, 255, 26))
        lit = w * self.level
        p.fillRect(QRectF(0, 0, min(lit, w * 0.88), h), QColor("#d9dad6"))
        if lit > w * 0.88:
            p.fillRect(QRectF(w * 0.88, 0, lit - w * 0.88, h), QColor(RED))


class VMeter(QWidget):
    """Thin vertical peak meter."""

    def __init__(self, height: int = 90, color: str = "#d9dad6", parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.color = QColor(color)
        self.setFixedSize(4, height)

    def feed(self, peak: float) -> None:
        db = 20.0 * math.log10(max(peak, 1e-5))
        target = min(1.0, max(0.0, (db + 54.0) / 54.0))
        level = target if target > self.level else max(target, self.level - 0.035)
        if level != self.level:
            self.level = level
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(QRectF(0, 0, w, h), _alpha(self.color, 34))
        lit = h * self.level
        p.fillRect(QRectF(0, h - min(lit, h * 0.88), w, min(lit, h * 0.88)), self.color)
        if lit > h * 0.88:
            p.fillRect(QRectF(0, h - lit, w, lit - h * 0.88), QColor(RED))


class _RoundButton(QWidget):
    toggled = pyqtSignal(bool)
    COLOR = "#5fae8b"

    def __init__(self, parent=None, size: int = 38):
        super().__init__(parent)
        self.on = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_on(self, on: bool) -> None:
        if on != self.on:
            self.on = on
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit(not self.on)
        e.accept()

    def _ring(self, p: QPainter):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        color = QColor(self.COLOR) if self.on else QColor(UI_DIM)
        p.setPen(QPen(color, 1.4))
        p.setBrush(QColor("#232427"))
        p.drawEllipse(c, self.width() / 2.0 - 3, self.width() / 2.0 - 3)
        return c, color


class PowerButton(_RoundButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setToolTip("Start / stop the audio engine")

    def paintEvent(self, _):
        p = QPainter(self)
        c, color = self._ring(p)
        p.setPen(QPen(color, 1.8, *ROUND))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(c.x() - 6.5, c.y() - 5.5, 13, 13), 125 * 16, 290 * 16)
        p.drawLine(c + QPointF(0, -8), c + QPointF(0, -2))


class TransportButton(_RoundButton):
    """Play/stop or record."""

    def __init__(self, kind: str = "play", parent=None):
        super().__init__(parent)
        self.kind = kind
        if kind == "rec":
            self.COLOR = RED

    def paintEvent(self, _):
        p = QPainter(self)
        c, color = self._ring(p)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color if self.on else QColor("#b9bbbd"))
        if self.kind == "rec":
            p.drawEllipse(c, 5.0, 5.0)
        elif self.on:
            p.drawRect(QRectF(c.x() - 4.5, c.y() - 4.5, 9, 9))
        else:
            p.drawPolygon(QPointF(c.x() - 3.5, c.y() - 6), QPointF(c.x() - 3.5, c.y() + 6),
                          QPointF(c.x() + 6.5, c.y()))


class CycleField(QWidget):
    """Labelled value window; click the right half for next, the left for
    previous, and (with ``menu``) the middle for a list of every choice.
    ``picker`` replaces that list with something better (the sound browser);
    ``fmt`` turns a choice into the text shown."""

    changed = pyqtSignal(int)

    def __init__(self, label: str, choices, index: int = 0, text_color: str = "#ffffff",
                 width: int = 132, parent=None, menu: bool = False):
        super().__init__(parent)
        self.menu = menu
        self.picker = None
        self.fmt = str
        self.label = label
        self.choices = list(choices) or ["-"]
        self.index = index
        self.text_color = QColor(text_color)
        self.setFixedSize(width, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_index(self, index: int, emit: bool = False) -> None:
        index = int(index) % len(self.choices)
        if index != self.index:
            self.index = index
            self.update()
            if emit:
                self.changed.emit(index)

    def set_choices(self, choices, index: int | None = None) -> None:
        self.choices = list(choices) or ["-"]
        self.index = (self.index if index is None else int(index)) % len(self.choices)
        self.update()

    def mousePressEvent(self, e):
        x = e.position().x()
        if self.menu and 20 <= x <= self.width() - 20 and e.button() == Qt.MouseButton.LeftButton:
            if self.picker is not None:
                self.picker()
                return e.accept()
            menu = QMenu(self)
            for i, name in enumerate(self.choices):
                action = menu.addAction(self.fmt(name))
                action.setCheckable(True)
                action.setChecked(i == self.index)
                action.setData(i)
            chosen = menu.exec(e.globalPosition().toPoint())
            if chosen is not None:
                self.set_index(chosen.data(), emit=True)
            return e.accept()
        back = e.button() == Qt.MouseButton.RightButton or x < self.width() / 2
        self.set_index(self.index + (-1 if back else 1), emit=True)
        e.accept()

    def contextMenuEvent(self, e):
        e.accept()   # right-click steps backwards; don't open the module menu

    def wheelEvent(self, e):
        self.set_index(self.index + (1 if e.angleDelta().y() < 0 else -1), emit=True)
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(_alpha(self.text_color, 170))
        p.setFont(font(9, medium=True, spacing=0.9))
        p.drawText(QRectF(1, 0, self.width(), 12), Qt.AlignmentFlag.AlignVCenter, self.label.upper())
        box = QRectF(0, 15, self.width(), 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SCREEN_BG))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1.3, *ROUND))
        y = box.center().y()
        p.drawPolyline(QPointF(10, y - 3.5), QPointF(6.5, y), QPointF(10, y + 3.5))
        right = box.right()
        p.drawPolyline(QPointF(right - 10, y - 3.5), QPointF(right - 6.5, y), QPointF(right - 10, y + 3.5))
        p.setPen(QColor("#e9e9e5"))
        text = self.fmt(self.choices[self.index])
        p.setFont(fit_font(text, box.width() - 34, 11, bold=True, family="mono"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class PadButton(QWidget):
    """A flat key with a caption and an optional lamp. ``hint`` is its tooltip."""

    pressed = pyqtSignal()

    def __init__(self, label: str, hint: str = "", lit=None, parent=None,
                 color: str = "#e9e9e5", width: int = 50):
        super().__init__(parent)
        self.label = label
        self.lit = lit      # callable -> bool, or None for no lamp
        self.color = QColor(color)
        self._down = False
        self.setFixedSize(width, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if hint:
            self.setToolTip(hint)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.update()
            self.pressed.emit()
        e.accept()

    def mouseReleaseEvent(self, e):
        self._down = False
        self.update()
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height() - 4)
        on = self.lit is not None and bool(self.lit())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1d1e20") if self._down else QColor(KEY))
        p.drawRoundedRect(rect, 4, 4)
        if self.lit is not None:
            p.setBrush(self.color if on else QColor(255, 255, 255, 34))
            p.drawRoundedRect(QRectF(rect.left() + 8, rect.top() + 6, rect.width() - 16, 2.5), 1.2, 1.2)
        p.setPen(self.color if on else QColor("#d6d7d3"))
        p.setFont(font(9, medium=True, spacing=0.9))
        p.drawText(rect.adjusted(0, 7 if self.lit is not None else 0, 0, 0),
                   Qt.AlignmentFlag.AlignCenter, self.label.upper())


class Jack(QWidget):
    """A patch point. Dragging from it is handled by the rack."""

    W, H = 44, 44

    def __init__(self, owner, kind: str, name: str, label: str, text_color: str, parent=None):
        super().__init__(parent)
        self.owner = owner       # the module widget
        self.kind = kind         # "in" or "out"
        self.name = name
        self.label = label
        self.text_color = QColor(text_color)
        self.hot = False         # a cable being dragged can land here
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(f"{label} ({'output' if kind == 'out' else 'input'}) - drag to another jack to patch")

    def hole(self) -> QPointF:
        return QPointF(self.W / 2.0, 15.0)

    def set_hot(self, hot: bool) -> None:
        if hot != self.hot:
            self.hot = hot
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.owner.rack.jack_press(self, e.globalPosition())
        e.accept()

    def mouseMoveEvent(self, e):
        self.owner.rack.jack_move(e.globalPosition())
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.owner.rack.jack_release(e.globalPosition())
        e.accept()

    def contextMenuEvent(self, e):
        self.owner.rack.jack_menu(self, e.globalPos())
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = self.label.upper()
        p.setFont(fit_font(text, self.W - 6, 8, medium=True, spacing=0.8))
        plate = QRectF(4, 30, self.W - 8, 12)
        if self.kind == "out":       # outputs get a filled label, inputs plain text
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.text_color)
            p.drawRoundedRect(plate, 2, 2)
            p.setPen(QColor("#141516") if is_light(self.text_color) else QColor("#f2f2ee"))
        else:
            p.setPen(_alpha(self.text_color, 190))
        p.drawText(plate, Qt.AlignmentFlag.AlignCenter, text)
        draw_jack(p, self.hole(), 9.0, self.hot, light=not is_light(self.text_color))


class StepRow(QWidget):
    """Sixteen step keys. ``state(i)`` -> None, or a dict with on, locks, vel,
    playing, held and number."""

    toggled = pyqtSignal(int)
    held = pyqtSignal(int)       # right-click / shift-click: hold the step for editing

    KEY_W, KEY_H, PITCH = 30, 40, 33

    def __init__(self, state, accent: str, parent=None):
        super().__init__(parent)
        self.state = state
        self.accent = QColor(accent)
        self.setFixedSize(self.PITCH * 16 - 3, self.KEY_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        i = int(e.position().x() // self.PITCH)
        if 0 <= i < 16:
            if e.button() == Qt.MouseButton.RightButton or \
                    e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.held.emit(i)
            elif e.button() == Qt.MouseButton.LeftButton:
                self.toggled.emit(i)
        e.accept()

    def contextMenuEvent(self, e):
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(16):
            st = self.state(i)
            rect = QRectF(i * self.PITCH, 0, self.KEY_W, self.KEY_H)
            p.setPen(Qt.PenStyle.NoPen)
            if st is None:           # beyond the pattern's length
                p.setBrush(_alpha(KEY, 70))
                p.drawRoundedRect(rect, 3, 3)
                continue
            p.setBrush(QColor(KEY_LIGHT if i % 4 == 0 else KEY))
            p.drawRoundedRect(rect, 3, 3)
            if st["held"]:
                p.setPen(QPen(QColor(RED), 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect.adjusted(0.8, 0.8, -0.8, -0.8), 3, 3)
                p.setPen(Qt.PenStyle.NoPen)
            lamp = QRectF(rect.left() + 6, rect.top() + 7, rect.width() - 12, 4)
            if st["playing"]:
                p.setBrush(QColor("#ffffff"))
            elif st["on"]:
                p.setBrush(_alpha(self.accent, int(120 + 135 * st["vel"])))
            else:
                p.setBrush(QColor(255, 255, 255, 26))
            p.drawRoundedRect(lamp, 2, 2)
            if st["locks"]:
                p.setBrush(QColor(RED))
                p.drawEllipse(QPointF(rect.center().x(), rect.top() + 20), 2.0, 2.0)
            if i % 4 == 0:
                p.setPen(QColor(255, 255, 255, 120))
                p.setFont(font(8, medium=True, family="mono"))
                p.drawText(QRectF(rect.left(), rect.bottom() - 13, rect.width(), 11),
                           Qt.AlignmentFlag.AlignCenter, str(st["number"]))


class PageSelect(QWidget):
    """Four small page lamps above the step keys; click to switch page."""

    changed = pyqtSignal(int)

    def __init__(self, accent: str, parent=None):
        super().__init__(parent)
        self.accent = QColor(accent)
        self.page = 0
        self.pages = 1          # pages the pattern uses
        self.playing = -1       # page the playhead is on
        self.setFixedSize(96, 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_state(self, page: int, pages: int, playing: int) -> None:
        if (page, pages, playing) != (self.page, self.pages, self.playing):
            self.page, self.pages, self.playing = page, pages, playing
            self.update()

    def mousePressEvent(self, e):
        i = int(e.position().x() // 24)
        if 0 <= i < self.pages:
            self.changed.emit(i)
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(4):
            if i >= self.pages:
                color = QColor(128, 128, 128, 40)
            elif i == self.page:
                color = QColor(self.accent)
            else:
                color = QColor(128, 128, 128, 230 if i == self.playing else 110)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(i * 24 + 2, 4, 18, 3), 1.5, 1.5)


class TrackPads(QWidget):
    """Eight track pads. ``info(i)`` -> dict(label, selected, muted, flash 0..1)."""

    pressed = pyqtSignal(int)

    PAD_W, PITCH = 50, 54

    def __init__(self, info, accent: str, parent=None, count: int = 8):
        super().__init__(parent)
        self.info = info
        self.count = count
        self.accent = QColor(accent)
        self._down = -1
        self.setFixedSize(self.PITCH * count - 4, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        i = int(e.position().x() // self.PITCH)
        if e.button() == Qt.MouseButton.LeftButton and 0 <= i < self.count:
            self._down = i
            self.pressed.emit(i)
            self.update()
        e.accept()

    def mouseReleaseEvent(self, e):
        self._down = -1
        self.update()
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(self.count):
            info = self.info(i)
            rect = QRectF(i * self.PITCH, 0, self.PAD_W, 36)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#1d1e20") if self._down == i else QColor(KEY))
            p.drawRoundedRect(rect, 4, 4)
            if info["flash"] > 0.02:
                p.setBrush(_alpha(self.accent, int(150 * info["flash"])))
                p.drawRoundedRect(rect, 4, 4)
            if info["selected"]:
                p.setBrush(self.accent)
                bar = QRectF(rect.left() + 8, rect.bottom() - 5, rect.width() - 16, 2.5)
                p.drawRoundedRect(bar, 1.2, 1.2)
            faded = info["muted"]
            p.setPen(QColor(233, 233, 229, 80 if faded else 255))
            p.setFont(font(11, bold=True, family="mono"))
            p.drawText(QRectF(rect.left(), rect.top() + 3, rect.width(), 14),
                       Qt.AlignmentFlag.AlignCenter, "M" if faded else str(i + 1))
            p.setPen(QColor(233, 233, 229, 50 if faded else 140))
            label = info["label"].upper()
            p.setFont(fit_font(label, rect.width() - 6, 8, medium=True, spacing=0.4))
            p.drawText(QRectF(rect.left(), rect.top() + 16, rect.width(), 12),
                       Qt.AlignmentFlag.AlignCenter, label)


class Keyboard(QWidget):
    """A flat piano keyboard. Click or drag to play."""

    note_on = pyqtSignal(int)
    note_off = pyqtSignal(int)

    BLACK = (1, 3, 6, 8, 10)

    def __init__(self, low: int = 48, whites: int = 15, width: int = 398, height: int = 82,
                 accent: str = "#3d7fc4", parent=None):
        super().__init__(parent)
        self.low = low
        self.whites = whites
        self.accent = QColor(accent)
        self.lit: set = set()        # notes to show as held (from the synth)
        self._mouse = None
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._white_notes = []
        note = low
        while len(self._white_notes) < whites:
            if note % 12 not in self.BLACK:
                self._white_notes.append(note)
            note += 1

    def set_lit(self, notes) -> None:
        notes = set(notes)
        if notes != self.lit:
            self.lit = notes
            self.update()

    def _white_w(self) -> float:
        return self.width() / self.whites

    def _black_rects(self):
        w = self._white_w()
        for i, note in enumerate(self._white_notes[:-1]):
            if (note + 1) % 12 in self.BLACK:
                yield note + 1, QRectF((i + 1) * w - w * 0.29, 0, w * 0.58, self.height() * 0.58)

    def _note_at(self, pos) -> int | None:
        if not self.rect().contains(pos.toPoint()):
            return None
        for note, rect in self._black_rects():
            if rect.contains(pos):
                return note
        return self._white_notes[min(self.whites - 1, int(pos.x() // self._white_w()))]

    def _play(self, note) -> None:
        if note == self._mouse:
            return
        if self._mouse is not None:
            self.note_off.emit(self._mouse)
        self._mouse = note
        if note is not None:
            self.note_on.emit(note)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._play(self._note_at(e.position()))
        e.accept()

    def mouseMoveEvent(self, e):
        if self._mouse is not None:
            self._play(self._note_at(e.position()) or self._mouse)
        e.accept()

    def mouseReleaseEvent(self, e):
        self._play(None)
        e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self._white_w(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        for i, note in enumerate(self._white_notes):
            p.setBrush(self.accent if note in self.lit else QColor("#fbfbf8"))
            p.drawRoundedRect(QRectF(i * w + 0.75, 0, w - 1.5, h), 2.5, 2.5)
            if note % 12 == 0:
                p.setPen(QColor(0, 0, 0, 90))
                p.setFont(font(8, medium=True))
                p.drawText(QRectF(i * w, h - 13, w, 11), Qt.AlignmentFlag.AlignCenter, f"C{note // 12 - 1}")
                p.setPen(Qt.PenStyle.NoPen)
        for note, rect in self._black_rects():
            p.setBrush(self.accent.darker(140) if note in self.lit else QColor("#1b1c1e"))
            p.drawRoundedRect(rect, 2, 2)


__all__ = ["CycleField", "Jack", "Keyboard", "Knob", "LevelMeter", "PadButton", "PageSelect",
           "PowerButton", "StepRow", "TrackPads", "TransportButton", "VMeter", "draw_led"]
