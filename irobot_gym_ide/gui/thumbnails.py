"""Shared helper for turning a captured ImageTemplate's stored pixels into a
QImage -- used by both the Library tree's icon and the Template inspector's
larger preview, so the base64 decode exists in exactly one place."""
from __future__ import annotations

import base64

from PySide6.QtGui import QImage

from ..model import ImageTemplate


def decode_template_qimage(template: ImageTemplate) -> QImage | None:
    if not template or not template.pixels_b64 or not template.image_w or not template.image_h:
        return None
    raw = base64.b64decode(template.pixels_b64)
    return QImage(raw, template.image_w, template.image_h, template.image_w, QImage.Format_Grayscale8)
