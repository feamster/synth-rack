"""Colours, module finishes, rack skins and shared painting helpers.

The look is deliberately quiet: flat matte panels in a few neutral tones, one
accent colour per module, thin type. Nothing here uses image assets.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QRadialGradient

# name -> panel colour, lettering colour
MODULE_FINISHES = {
    "carbon": {"body": "#1b1c1e", "text": "#e9e9e5"},
    "slate":  {"body": "#2c2e32", "text": "#e2e2de"},
    "fog":    {"body": "#d3d4d2", "text": "#1c1d1f"},
    "paper":  {"body": "#ecebe6", "text": "#1c1d1f"},
    "sand":   {"body": "#d9d0bf", "text": "#2a2520"},
}
# The pedalboard's finishes, so Pedal Loop can show its pedals in their own colours.
PEDAL_FINISHES = {
    "graphite": {"body": "#3d4349", "text": "#f0f2f4"}, "gold": {"body": "#d9a62e", "text": "#2b1d02"},
    "tangerine": {"body": "#e4661c", "text": "#fff4e6"}, "violet": {"body": "#5a3fa6", "text": "#f3ecff"},
    "sky": {"body": "#3d9fd6", "text": "#04263b"}, "mint": {"body": "#7fceae", "text": "#0c3528"},
    "cream": {"body": "#e7ddc3", "text": "#3b2a18"}, "ocean": {"body": "#175f7c", "text": "#e2f6ff"},
    "pearl": {"body": "#e3e7eb", "text": "#1c2632"}, "crimson": {"body": "#b0252d", "text": "#fff0ee"},
    "midnight": {"body": "#191b1f", "text": "#e9edf2"}, "seafoam": {"body": "#9fd8cf", "text": "#143b38"},
}
FINISHES = {**PEDAL_FINISHES, **MODULE_FINISHES}

RACK_SKINS = ("graphite", "walnut", "aluminum")

MODULE_COLORS = ("#e2553a", "#d9a441", "#3d7fc4", "#5fae8b")   # the only four accent hues
CABLE_COLORS = ("#d9603f", "#d9a441", "#4f9fc4", "#5fae8b", "#9a86cf", "#b9bbbd")

PANEL_H = 372     # every module is this tall
ROW_H = 376       # rack row pitch
EAR = 12          # rack cheek width

SCREEN_BG = "#0c0d0e"
SCREEN_FG = "#e9e9e5"
SCREEN_DIM = "#6d6f73"
KEY = "#2a2b2e"          # pads and step keys
KEY_LIGHT = "#37393d"
RED = "#e2553a"

UI_BG = "#141516"
UI_PANEL = "#1c1d1f"
UI_TEXT = "#d9dad6"
UI_DIM = "#85878b"
UI_ACCENT = "#d9a441"


def finish_of(module) -> dict:
    return FINISHES.get(module.finish or module.FINISH, MODULE_FINISHES["slate"])


def is_light(color) -> bool:
    return QColor(color).lightness() > 140


def font(px: int, bold: bool = False, family: str = "ui", spacing: float = 0.0,
         medium: bool = False) -> QFont:
    f = QFont()
    families = {
        "ui": ["Helvetica Neue", "Arial"],
        "logo": ["Futura", "Avenir Next", "Helvetica Neue", "Arial"],
        "mono": ["Menlo", "Monaco", "Courier New"],
    }[family]
    f.setFamilies(families)
    f.setPixelSize(px)
    if bold:
        f.setBold(True)
    elif medium:
        f.setWeight(QFont.Weight.Medium)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def fit_font(text: str, max_width: float, start_px: int, **kwargs) -> QFont:
    """Largest font (<= start_px) at which ``text`` fits in ``max_width``."""
    from PyQt6.QtGui import QFontMetricsF

    px = start_px
    while px > 7:
        f = font(px, **kwargs)
        if QFontMetricsF(f).horizontalAdvance(text) <= max_width:
            return f
        px -= 1
    return font(px, **kwargs)


def draw_led(p: QPainter, center: QPointF, radius: float, color: QColor, on: bool) -> None:
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    if on:
        glow = QRadialGradient(center, radius * 3.0)
        c = QColor(color)
        c.setAlpha(110)
        glow.setColorAt(0.0, c)
        c.setAlpha(0)
        glow.setColorAt(1.0, c)
        p.setBrush(glow)
        p.drawEllipse(center, radius * 3.0, radius * 3.0)
        p.setBrush(QColor(color))
    else:
        p.setBrush(QColor(255, 255, 255, 38))
    p.drawEllipse(center, radius, radius)
    p.restore()


def draw_panel(p: QPainter, rect: QRectF, body: QColor, lifted: bool = False) -> None:
    """A rack faceplate: flat matte colour, hairline edge, four small screws."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if lifted:
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(8):
            p.setBrush(QColor(0, 0, 0, 20))
            p.drawRoundedRect(rect.adjusted(-i, -i + 4, i, i + 6), 4 + i, 4 + i)
    p.setBrush(body)
    p.setPen(QPen(body.darker(170) if is_light(body) else QColor(0, 0, 0), 1.0))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)
    screw = body.darker(125) if is_light(body) else body.lighter(170)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(screw)
    for sx, sy in ((rect.left() + 9, rect.top() + 9), (rect.right() - 9, rect.top() + 9),
                   (rect.left() + 9, rect.bottom() - 9), (rect.right() - 9, rect.bottom() - 9)):
        p.drawEllipse(QPointF(sx, sy), 2.4, 2.4)
    p.restore()


def draw_screen(p: QPainter, rect: QRectF, radius: float = 4.0) -> None:
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(SCREEN_BG))
    p.drawRoundedRect(rect, radius, radius)
    p.restore()


def draw_jack(p: QPainter, c: QPointF, r: float = 9.0, hot: bool = False, light: bool = False) -> None:
    """A socket: a flat metal ring around a dark hole."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if hot:
        p.setPen(QPen(QColor(UI_ACCENT), 2.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r + 4.0, r + 4.0)
    p.setPen(QPen(QColor(0, 0, 0, 90 if light else 200), 1.0))
    p.setBrush(QColor("#a9abad") if light else QColor("#8d8f92"))
    p.drawEllipse(c, r, r)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#0a0a0b"))
    p.drawEllipse(c, r * 0.5, r * 0.5)
    p.restore()


def draw_mini(p: QPainter, rect: QRectF, body: QColor) -> None:
    """A tiny flat panel, for shelf thumbnails."""
    p.save()
    p.setPen(QPen(body.darker(170) if is_light(body) else body.lighter(190), 1.0))
    p.setBrush(body)
    p.drawRoundedRect(rect, 2.5, 2.5)
    p.restore()


_tile_cache: dict = {}
_CHEEK = {"graphite": "#1c1d1f", "walnut": "#4f3423", "aluminum": "#8a8d91"}


def rack_tile(skin: str, width: int = 960) -> QPixmap:
    """One empty rack row, horizontally tileable: a dark case with two rails."""
    if skin in _tile_cache:
        return _tile_cache[skin]
    pm = QPixmap(width, ROW_H)
    p = QPainter(pm)
    p.fillRect(0, 0, width, ROW_H, QColor("#0b0c0d"))
    rail = QColor("#9a9da1") if skin == "aluminum" else QColor("#232427")
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for top in (2, PANEL_H - 16):
        p.fillRect(0, top, width, 16, rail)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0b0c0d"))
        for x in range(10, width, 20):
            p.drawEllipse(QPointF(x, top + 8), 2.2, 2.2)
    p.end()
    _tile_cache[skin] = pm
    return pm


def paint_cheek(p: QPainter, rect: QRectF, skin: str) -> None:
    """The rack's side panel."""
    p.fillRect(rect, QColor(_CHEEK.get(skin, _CHEEK["graphite"])))
