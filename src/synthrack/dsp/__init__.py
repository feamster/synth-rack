"""Module registry."""

from __future__ import annotations

from .core import Module, Param
from .groovebox import Forge, GrooveBox, Knockbox
from .reel import Reel
from .transport import Clock, Transport
from .utility import Afterglow, LineIn, MainOut, PedalLoop, Summit
from .wander import Wander

# Shelf order.
MODULE_CLASSES = (Knockbox, Forge, Wander, Reel, Afterglow, Summit, PedalLoop, LineIn, MainOut)
REGISTRY = {cls.TYPE: cls for cls in MODULE_CLASSES}


def create_module(type_name: str, sr: float = 48000.0) -> Module:
    return REGISTRY[type_name](sr)


def module_from_dict(data: dict, sr: float = 48000.0) -> Module:
    module = create_module(data["type"], sr)
    module.uid = str(data.get("id", ""))
    module.load_dict(data)
    return module


__all__ = ["MODULE_CLASSES", "REGISTRY", "Afterglow", "Clock", "Forge", "GrooveBox", "Knockbox",
           "LineIn", "MainOut", "Module", "Param", "PedalLoop", "Reel", "Summit", "Transport",
           "Wander", "create_module", "module_from_dict"]
