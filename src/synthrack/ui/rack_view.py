"""The rack (modules flow into rows; cables patch them) and the module shelf."""

from __future__ import annotations

import zlib

from PyQt6.QtCore import (
    QEasingCurve,
    QMimeData,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QDrag, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QMenu, QWidget

from ..dsp import MODULE_CLASSES, GrooveBox, create_module, module_from_dict
from ..engine import would_loop
from ..racks import new_uid
from .modules import make_module_widget
from .theme import (
    CABLE_COLORS,
    EAR,
    FINISHES,
    MODULE_FINISHES,
    PANEL_H,
    ROW_H,
    UI_ACCENT,
    UI_DIM,
    draw_mini,
    font,
    is_light,
    paint_cheek,
    rack_tile,
)

MIME = "application/x-synthrack-type"
MAX_MODULES = 16


def cable_color(cable) -> QColor:
    """All cables from one output share a colour, and keep it between sessions."""
    return QColor(CABLE_COLORS[zlib.crc32(f"{cable[0]}/{cable[1]}".encode()) % len(CABLE_COLORS)])


class CableOverlay(QWidget):
    """Paints the patch cables over the modules; mouse events pass through."""

    OPACITY = (0.9, 0.28, 0.0)     # rack.cable_view: full, dim, hidden

    def __init__(self, rack):
        super().__init__(rack)
        self.rack = rack
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def _cable(self, p: QPainter, a: QPointF, b: QPointF, color: QColor, loose: bool = False) -> None:
        span = abs(b.x() - a.x()) + abs(b.y() - a.y())
        sag = min(64.0, 14.0 + span * 0.1)
        path = QPainterPath(a)
        path.cubicTo(a + QPointF((b.x() - a.x()) * 0.2, sag), b - QPointF((b.x() - a.x()) * 0.2, -sag), b)
        round_cap = (Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 46), 4.5, *round_cap))
        p.drawPath(path.translated(0, 2))
        body = QColor(color)
        p.setPen(QPen(body, 2.6, *round_cap))
        p.drawPath(path)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.setBrush(body)
        for end in (a, b):           # the plugs
            p.drawEllipse(end, 5.5, 5.5)

    def paintEvent(self, _):
        rack = self.rack
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.OPACITY[rack.cable_view])
        for cable in rack.cables:
            a, b = rack.jack_point("out", cable[0], cable[1]), rack.jack_point("in", cable[2], cable[3])
            if a is not None and b is not None:
                self._cable(p, a, b, cable_color(cable))
        p.setOpacity(1.0)
        if rack.loose is not None:
            anchor, pos, color = rack.loose
            self._cable(p, rack.jack_center(anchor), pos, color, loose=True)


class RackView(QWidget):
    patch_changed = pyqtSignal()       # modules or cables changed
    selection_changed = pyqtSignal()
    edited = pyqtSignal()              # anything at all changed
    need_engine = pyqtSignal()         # a module wants audio running (a key was played)
    need_play = pyqtSignal()           # ... and the transport rolling (tape record)
    sample_renamed = pyqtSignal(str, str)

    def __init__(self, sample_rate_getter, transport, parent=None):
        super().__init__(parent)
        self._sr = sample_rate_getter
        self.transport = transport
        self.skin = "graphite"
        self.widgets: list = []
        self.cables: list = []         # (src uid, out jack, dst uid, in jack)
        self.selected = None           # the module the keyboard plays
        self.loose = None              # (anchor jack, mouse pos, colour) while dragging a cable
        self.cable_view = 0            # 0 full, 1 dim, 2 hidden
        self._anims: dict = {}
        self._drag = None
        self._insert_at = None
        self.overlay = CableOverlay(self)
        self.setAcceptDrops(True)
        self.setMinimumHeight(ROW_H)
        self.patch_changed.connect(self.edited)

    # -- model --------------------------------------------------------
    def modules(self) -> list:
        return [w.module for w in self.widgets]

    def widget_for(self, uid: str):
        return next((w for w in self.widgets if w.module.uid == uid), None)

    def set_rack(self, modules, cables) -> None:
        self.shutdown()
        for w in self.widgets:
            w.setParent(None)
            w.deleteLater()
        self.widgets, self.selected, self.loose = [], None, None
        self.cables = [tuple(c) for c in cables]
        for module in modules:
            self._attach(module, len(self.widgets))
        self.relayout(animate=False)
        self.patch_changed.emit()
        playable = next((w for w in self.widgets if w.module.TYPE in ("knockbox", "forge", "wander")), None)
        self.select(playable or (self.widgets[0] if self.widgets else None))

    def _attach(self, module, index: int):
        widget = make_module_widget(module, self)
        widget.edited.connect(self.edited)
        self.widgets.insert(index, widget)
        widget.show()
        self.overlay.raise_()
        return widget

    def add_module(self, type_name: str, index: int | None = None, data: dict | None = None):
        if len(self.widgets) >= MAX_MODULES:
            return None
        index = len(self.widgets) if index is None else max(0, min(index, len(self.widgets)))
        module = module_from_dict(data, self._sr()) if data else create_module(type_name, self._sr())
        module.uid = new_uid(module.TYPE, [m.uid for m in self.modules()])
        widget = self._attach(module, index)
        slots = self._slots()
        widget.move(slots[index].x(), slots[index].y() - 40)   # drops in from above
        self.relayout()
        self.patch_changed.emit()
        self.select(widget)
        return widget

    def remove(self, widget) -> None:
        if widget not in self.widgets or not widget.module.REMOVABLE:
            return
        index = self.widgets.index(widget)
        self.widgets.remove(widget)
        uid = widget.module.uid
        self.cables = [c for c in self.cables if uid not in (c[0], c[2])]
        if widget is self.selected:
            self.selected = None
            self.select(self.widgets[min(index, len(self.widgets) - 1)] if self.widgets else None)
        self._anims.pop(widget, None)
        widget.shutdown()
        widget.setParent(None)
        widget.deleteLater()
        self.relayout()
        self.patch_changed.emit()

    def shutdown(self) -> None:
        for w in self.widgets:
            w.shutdown()

    def set_skin(self, skin: str) -> None:
        self.skin = skin
        self.update()
        self.edited.emit()

    # -- selection ----------------------------------------------------
    def select(self, widget) -> None:
        if widget is self.selected:
            return
        if self.selected is not None and self.selected in self.widgets:
            self.selected.set_selected(False)
        self.selected = widget
        if widget is not None:
            widget.set_selected(True)
        self.selection_changed.emit()

    def select_step(self, step: int) -> None:
        if not self.widgets:
            return
        index = (self.widgets.index(self.selected) + step) % len(self.widgets) \
            if self.selected in self.widgets else 0
        self.select(self.widgets[index])

    def pattern_chosen(self, box, index: int) -> None:
        """A groovebox changed pattern; linked boxes follow."""
        box.select_pattern(index)
        if box.link:
            for w in self.widgets:
                other = w.module
                if other is not box and isinstance(other, GrooveBox) and other.link:
                    other.select_pattern(index)
                    w.refresh()

    # -- the sample library, as far as the modules on the rack are concerned --
    def rename_sample(self, old: str, new: str) -> None:
        """An imported sample was renamed: keep every track that plays it pointing at it."""
        for w in self.widgets:
            module = w.module
            for track in getattr(module, "tracks", ()):
                if getattr(track, "sample", None) is not None and track.sound == old:
                    track.sound = new
            if getattr(module, "sample_name", None) == old:
                module.sample_name = new
            w.refresh()
        self.sample_renamed.emit(old, new)
        self.edited.emit()

    def forget_sample(self, name: str) -> None:
        """An imported sample was deleted: tracks that played it go back to their default sound."""
        for w in self.widgets:
            module = w.module
            for t, track in enumerate(getattr(module, "tracks", ())):
                if getattr(track, "sample", None) is not None and track.sound == name:
                    module.set_sound(t, module.DEFAULT_KIT[t])
            if getattr(module, "sample_name", None) == name:
                module.set_sample("Keys")
            w.refresh()
        self.edited.emit()

    # -- layout: modules flow left to right and wrap into rows --------------
    def _flow(self, widgets) -> list:
        inner = max(200, self.width() - 2 * EAR)
        x, row, slots = 0, 0, []
        for w in widgets:
            if x and x + w.width() > inner:
                x, row = 0, row + 1
            slots.append(QPoint(EAR + x, row * ROW_H + 2))
            x += w.width()
        return slots

    def _slots(self) -> list:
        return self._flow(self.widgets)

    def rows(self) -> int:
        slots = self._slots()
        return (slots[-1].y() // ROW_H + 1) if slots else 1

    def relayout(self, animate: bool = True, skip=None) -> None:
        slots = self._slots()
        self.setMinimumHeight(self.rows() * ROW_H)
        for w, target in zip(self.widgets, slots):
            if w is skip:
                continue
            running = self._anims.pop(w, None)
            if running:
                running.stop()
            if not animate or not self.isVisible():
                w.move(target)
                continue
            if w.pos() == target:
                continue
            anim = QPropertyAnimation(w, b"pos", self)
            anim.setDuration(170)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setEndValue(target)
            anim.finished.connect(lambda w=w, a=anim: self._anims.get(w) is a and self._anims.pop(w))
            self._anims[w] = anim
            anim.start()
        self.overlay.setGeometry(self.rect())
        self.overlay.raise_()
        self.update()

    def resizeEvent(self, _):
        self.relayout(animate=False, skip=self._drag[0] if self._drag else None)

    def _index_for(self, pos: QPointF, ignore=None) -> int:
        """Where in the flow a module centred at ``pos`` belongs."""
        row = max(0, int(pos.y() // ROW_H))
        index = 0
        for w, slot in zip(self.widgets, self._slots()):   # judged against the layout as it stands
            if w is ignore:
                continue
            w_row = slot.y() // ROW_H
            if w_row < row or (w_row == row and pos.x() > slot.x() + w.width() / 2.0):
                index += 1
        return index

    # -- drag to reorder (driven by ModuleWidget mouse events) --------
    def begin_drag(self, widget, global_pos: QPointF) -> None:
        self.select(widget)
        self._drag = [widget, widget.mapFromGlobal(global_pos.toPoint()), False]

    def drag_to(self, widget, global_pos: QPointF) -> None:
        if not self._drag or self._drag[0] is not widget:
            return
        _, offset, started = self._drag
        pos = self.mapFromGlobal(global_pos.toPoint()) - offset
        if not started:
            if (pos - widget.pos()).manhattanLength() < 9:
                return
            self._drag[2] = True
            old = self._anims.pop(widget, None)
            if old:
                old.stop()
            widget.lifted = True
            widget.raise_()
            widget.setCursor(Qt.CursorShape.ClosedHandCursor)
        widget.move(pos)
        center = QPointF(pos.x() + widget.width() / 2.0, pos.y() + PANEL_H / 2.0)
        off_rack = widget.module.REMOVABLE and (center.y() < -40 or center.y() > self.height() + 40)
        self._set_ghost(widget, off_rack)
        new_index = self._index_for(center, ignore=widget)
        if new_index != self.widgets.index(widget):
            self.widgets.remove(widget)
            self.widgets.insert(new_index, widget)
            self.relayout(skip=widget)
            self.edited.emit()
        self.overlay.update()

    def end_drag(self, widget) -> None:
        if not self._drag or self._drag[0] is not widget:
            return
        started = self._drag[2]
        self._drag = None
        if not started:
            return
        widget.lifted = False
        widget.setCursor(Qt.CursorShape.OpenHandCursor)
        if widget.graphicsEffect() is not None:  # released off the rack: remove it
            self.remove(widget)
            return
        widget.update()
        self.relayout()

    def _set_ghost(self, widget, ghost: bool) -> None:
        if ghost and widget.graphicsEffect() is None:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.35)
            widget.setGraphicsEffect(effect)
        elif not ghost and widget.graphicsEffect() is not None:
            widget.setGraphicsEffect(None)

    # -- cables -------------------------------------------------------
    def cycle_cable_view(self) -> int:
        self.cable_view = (self.cable_view + 1) % 3
        self.overlay.update()
        return self.cable_view

    def cables_moved(self) -> None:
        self.overlay.update()

    def jack_center(self, jack) -> QPointF:
        return QPointF(jack.mapTo(self, jack.hole().toPoint()))

    def jack_point(self, kind: str, uid: str, name: str) -> QPointF | None:
        widget = self.widget_for(uid)
        jack = widget.jacks.get((kind, name)) if widget is not None else None
        return self.jack_center(jack) if jack is not None else None

    def _jacks(self):
        for w in self.widgets:
            yield from w.jacks.values()

    def jack_at(self, global_pos: QPointF):
        pos = self.mapFromGlobal(global_pos.toPoint())
        best, best_d = None, 22.0 ** 2
        for jack in self._jacks():
            c = self.jack_center(jack)
            d = (c.x() - pos.x()) ** 2 + (c.y() - pos.y()) ** 2
            if d < best_d:
                best, best_d = jack, d
        return best

    def _cables_at(self, jack) -> list:
        uid = jack.owner.module.uid
        if jack.kind == "out":
            return [c for c in self.cables if c[0] == uid and c[1] == jack.name]
        return [c for c in self.cables if c[2] == uid and c[3] == jack.name]

    def can_connect(self, a, b) -> bool:
        """Can a cable run between jacks ``a`` and ``b`` (either order)?"""
        if a is None or b is None or a.kind == b.kind:
            return False
        out, inp = (a, b) if a.kind == "out" else (b, a)
        cable = (out.owner.module.uid, out.name, inp.owner.module.uid, inp.name)
        return cable not in self.cables and not would_loop(self.cables, cable[0], cable[2])

    def connect_jacks(self, a, b) -> bool:
        if not self.can_connect(a, b):
            return False
        out, inp = (a, b) if a.kind == "out" else (b, a)
        self.cables.append((out.owner.module.uid, out.name, inp.owner.module.uid, inp.name))
        self.overlay.update()
        self.patch_changed.emit()
        return True

    def disconnect(self, cable) -> None:
        if cable in self.cables:
            self.cables.remove(cable)
            self.overlay.update()
            self.patch_changed.emit()

    def jack_press(self, jack, global_pos: QPointF) -> None:
        """Start a cable. From an input that is already patched, pick that cable up."""
        anchor, color = jack, None
        if jack.kind == "in":
            existing = self._cables_at(jack)
            if existing:
                cable = existing[-1]
                color = cable_color(cable)
                self.disconnect(cable)
                anchor = self.widget_for(cable[0]).jacks[("out", cable[1])]
        if color is None:
            color = cable_color((anchor.owner.module.uid, anchor.name)) if anchor.kind == "out" \
                else QColor("#d9dde2")
        self.loose = (anchor, QPointF(self.mapFromGlobal(global_pos.toPoint())), color)
        self.cable_view = 0            # patching brings the cables back into view
        self.overlay.update()

    def jack_move(self, global_pos: QPointF) -> None:
        if self.loose is None:
            return
        anchor, _, color = self.loose
        self.loose = (anchor, QPointF(self.mapFromGlobal(global_pos.toPoint())), color)
        target = self.jack_at(global_pos)
        for jack in self._jacks():
            jack.set_hot(jack is target and self.can_connect(anchor, jack))
        self.overlay.update()

    def jack_release(self, global_pos: QPointF) -> None:
        if self.loose is None:
            return
        anchor = self.loose[0]
        self.loose = None
        for jack in self._jacks():
            jack.set_hot(False)
        self.connect_jacks(anchor, self.jack_at(global_pos))
        self.overlay.update()

    def jack_menu(self, jack, global_pos) -> None:
        cables = self._cables_at(jack)
        menu = QMenu(self)
        actions = {}
        for cable in cables:
            other = self.widget_for(cable[2] if jack.kind == "out" else cable[0])
            name = other.module.NAME if other is not None else "?"
            end = cable[3] if jack.kind == "out" else cable[1]
            actions[menu.addAction(f"Unplug {name} · {end}")] = [cable]
        if len(cables) > 1:
            actions[menu.addAction("Unplug All")] = cables
        if not cables:
            menu.addAction("Nothing patched here").setEnabled(False)
        chosen = menu.exec(global_pos)
        for cable in actions.get(chosen, []):
            self.disconnect(cable)

    # -- context menu -------------------------------------------------
    def module_menu(self, widget, global_pos) -> None:
        module = widget.module
        self.select(widget)
        menu = QMenu(self)
        extra = widget.menu_actions(menu)
        if extra:
            menu.addSeparator()
        duplicate = menu.addAction("Duplicate") if module.REMOVABLE else None
        reset = menu.addAction("Reset Knobs")
        finish_menu = menu.addMenu("Finish")
        finish_actions = {}
        for name in MODULE_FINISHES:
            action = finish_menu.addAction(name.title())
            action.setCheckable(True)
            action.setChecked(name == (module.finish or module.FINISH))
            finish_actions[action] = name
        unplug = menu.addAction("Unplug All Cables")
        remove = None
        if module.REMOVABLE:
            menu.addSeparator()
            remove = menu.addAction("Remove from Rack")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen in extra:
            extra[chosen]()
        elif chosen is duplicate:
            self.add_module(module.TYPE, self.widgets.index(widget) + 1, module.to_dict())
        elif chosen is reset:
            for param in module.PARAMS:
                module.set(param.key, param.default)
            widget.refresh()
            self.edited.emit()
        elif chosen is unplug:
            self.cables = [c for c in self.cables if module.uid not in (c[0], c[2])]
            self.overlay.update()
            self.patch_changed.emit()
        elif chosen is remove:
            self.remove(widget)
        elif chosen in finish_actions:
            module.finish = finish_actions[chosen]
            widget.rebuild()
            self.overlay.raise_()
            self.edited.emit()

    # -- drops from the shelf ------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME) and len(self.widgets) < MAX_MODULES:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        self._insert_at = self._index_for(e.position())
        self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, _):
        self._insert_at = None
        self.update()

    def dropEvent(self, e):
        type_name = bytes(e.mimeData().data(MIME)).decode()
        index = self._index_for(e.position())
        self._insert_at = None
        self.add_module(type_name, index)
        e.acceptProposedAction()

    def mousePressEvent(self, e):
        e.accept()

    # -- painting -----------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        tile = rack_tile(self.skin)
        for row in range(max(self.rows(), self.height() // ROW_H + 1)):
            p.drawTiledPixmap(0, row * ROW_H, self.width(), ROW_H, tile)
        paint_cheek(p, QRectF(0, 0, EAR, self.height()), self.skin)
        paint_cheek(p, QRectF(self.width() - EAR, 0, EAR, self.height()), self.skin)
        if not self.widgets:
            p.setPen(QColor(UI_DIM))
            p.setFont(font(13, medium=True, family="logo", spacing=3.0))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "DRAG A MODULE HERE FROM THE SHELF BELOW")
        if self._insert_at is not None:
            slots = self._slots()
            if not slots:
                x, y = EAR + 4.0, 2.0
            elif self._insert_at < len(slots):
                x, y = slots[self._insert_at].x(), slots[self._insert_at].y()
            else:
                x, y = slots[-1].x() + self.widgets[-1].width(), slots[-1].y()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(UI_ACCENT), 2))
            p.drawLine(QPointF(x, y + 12), QPointF(x, y + PANEL_H - 12))


# ---------------------------------------------------------------------------
def paint_mini_module(p: QPainter, rect: QRectF, cls) -> None:
    """Thumbnail of a module for the shelf and drag pixmaps."""
    fin = FINISHES[cls.FINISH]
    draw_mini(p, rect, QColor(fin["body"]))
    p.setPen(Qt.PenStyle.NoPen)
    knob = QColor("#26272a") if is_light(fin["body"]) else QColor("#8d8f92")
    w, left, top = rect.width(), rect.left(), rect.top()
    wide = w > 60
    screens = {"knockbox": 0.28, "forge": 0.28, "wander": 0.34, "reel": 0.7, "mainout": 0.7, "pedalloop": 0.7}
    body_right = rect.right() - (9 if wide else 0)
    x0 = left + 5
    if cls.TYPE in screens:
        sw = (body_right - left - 10) * screens[cls.TYPE]
        p.setBrush(QColor("#0c0d0e"))
        p.drawRoundedRect(QRectF(left + 5, top + 8, sw, 22), 2, 2)
        p.setBrush(QColor("#e9e9e5"))
        p.drawRect(QRectF(left + 8, top + 18, sw * 0.6, 1.5))
        x0 = left + 9 + sw if wide else x0
    if wide:      # knob dots
        p.setBrush(knob)
        count = max(2, int((body_right - x0) // 11))
        for row in range(2 if cls.TYPE != "reel" else 0):
            for i in range(count):
                p.drawEllipse(QPointF(x0 + 6 + i * 11, top + 14 + row * 13), 3.2, 3.2)
    else:
        p.setBrush(knob)
        for i in range(2 if cls.TYPE not in screens else 1):
            y = top + (14 if cls.TYPE not in screens else 40) + i * 14
            p.drawEllipse(QPointF(rect.center().x(), y), 4.0, 4.0)
    if cls.TYPE in ("knockbox", "forge"):
        p.setBrush(QColor(getattr(cls, "ACCENT", "#ffb224")))
        for i in range(8):
            p.setOpacity(1.0 if i % 3 == 0 else 0.35)
            p.drawRect(QRectF(left + 6 + i * 9, top + 50, 6, 7))
        p.setOpacity(1.0)
    elif cls.TYPE == "wander":
        p.setBrush(QColor("#fbfbf8"))
        p.drawRect(QRectF(left + 5, top + 44, body_right - left - 14, 14))
        p.setBrush(QColor("#1a1a1a"))
        for i in range(1, 9):
            if i % 7 not in (3, 0):
                p.drawRect(QRectF(left + 5 + i * 5.4 - 1.5, top + 44, 3, 8))
    # jacks
    p.setBrush(QColor("#0a0a0b"))
    p.setPen(QPen(QColor("#8d8f92"), 1.6))
    jacks = len(cls.INPUTS) + len(cls.OUTPUTS)
    for i in range(min(jacks, 4)):
        if wide:
            p.drawEllipse(QPointF(rect.right() - 7, top + 12 + i * 13), 3.0, 3.0)
        else:
            p.drawEllipse(QPointF(rect.center().x() + (i - (jacks - 1) / 2) * 9, rect.bottom() - 9), 3.0, 3.0)


class ModuleTile(QWidget):
    def __init__(self, cls, rack: RackView, parent=None):
        super().__init__(parent)
        self.cls = cls
        self.rack = rack
        self._press = None
        self._hover = False
        self.mini_w = max(30, int(cls.WIDTH / 7.2))
        self.setFixedSize(max(78, self.mini_w + 30), 96)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(f"{cls.NAME} - {cls.TAGLINE}\nDrag into the rack, or double-click to add")

    def _mini_rect(self) -> QRectF:
        return QRectF((self.width() - self.mini_w) / 2.0, 5, self.mini_w, 66)

    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < 8:
            return
        self._press = None
        pm = QPixmap(int(self.mini_w * 2 + 16), 150)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2.0, 2.0)
        paint_mini_module(painter, QRectF(4, 2, self.mini_w, 66), self.cls)
        painter.end()
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, self.cls.TYPE.encode())
        drag.setMimeData(mime)
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        drag.exec(Qt.DropAction.CopyAction)

    def mouseDoubleClickEvent(self, _):
        if self.cls.REMOVABLE:
            self.rack.add_module(self.cls.TYPE)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 1, -2, -1), 4, 4)
        paint_mini_module(p, self._mini_rect(), self.cls)
        p.setPen(QColor("#e9e9e5") if self._hover else QColor(UI_DIM))
        p.setFont(font(9, medium=True, spacing=1.0))
        p.drawText(QRectF(-10, 76, self.width() + 20, 16), Qt.AlignmentFlag.AlignCenter,
                   self.cls.NAME.upper())


class ModuleBrowser(QWidget):
    """The shelf of available modules along the bottom of the window."""

    def __init__(self, rack: RackView, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 2, 18, 2)
        row.setSpacing(10)
        row.addStretch(1)
        for cls in MODULE_CLASSES:
            if cls.REMOVABLE:
                row.addWidget(ModuleTile(cls, rack, self))
        row.addStretch(1)
