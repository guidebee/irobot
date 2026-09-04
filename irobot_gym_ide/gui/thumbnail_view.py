"""Persistent display for irobot's AgentStream color thumbnail.

The video port sends two independent image streams (see
tools/agent_client.py's BLOB_MSG_TYPE_SCREEN_SHOT vs BLOB_MSG_TYPE_OPENCV_MAT
and connection.py's LiveConnection.latest_thumbnail/latest_frame): a full-size
grayscale mirror (shown interactively in CanvasView) and a small color
"screen_shot" thumbnail paired with a perceptual hash for cheap change
detection. This widget is a plain, always-visible sink for that second
stream -- not a floating picture-in-picture over the canvas -- so the device
feed stays sanity-checkable regardless of which workflow tab is active.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .._agent_client import agent_client as ac


class ThumbnailView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_phash: bytes | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Device thumbnail")
        layout.addWidget(title)

        self._image_label = QLabel("(no thumbnail yet)")
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setStyleSheet("border: 1px solid #888;")
        layout.addWidget(self._image_label)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

    def update_thumbnail(self, width: int, height: int, color, phash: bytes) -> None:
        """`color` is a numpy ndarray, shape (height, width, channels). Shown
        at its native size, unscaled -- it's already small (a downscaled
        AgentStream thumbnail), so stretching it would only blur it."""
        channels = color.shape[2] if color.ndim == 3 else 1
        fmt = QImage.Format_RGB888 if channels == 3 else QImage.Format_Grayscale8
        bytes_per_line = width * channels
        image = QImage(color.tobytes(), width, height, bytes_per_line, fmt)
        self._image_label.setPixmap(QPixmap.fromImage(image))

        if self._last_phash is not None and phash:
            dist = ac.hamming(phash, self._last_phash)
            status = "changed" if dist != 0 else "unchanged"
            self._status_label.setText(f"{width}x{height}  ({status}, hamming={dist})")
        else:
            self._status_label.setText(f"{width}x{height}")
        if phash:
            self._last_phash = phash
