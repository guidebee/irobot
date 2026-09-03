"""Live-frame canvas: shows the most recent device frame and lets the user
click on it to place a PrimitiveEvent's (x, y). Coordinates emitted by
`pointClicked` are in *frame pixel space* (the currently displayed image's
own width/height) -- callers scale to the project's reference resolution
(see main_window.py's `_frame_to_reference`), the same ratio-scaling
agent_client.py's `interactive`/`record` commands already do and for the
same reason: touch coordinates must land in the real device resolution,
not the (possibly downscaled) frame's own dimensions.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QPen, QBrush, QColor, QPainter
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsSimpleTextItem

_POINTER_COLORS = [
    QColor("#e74c3c"), QColor("#3498db"), QColor("#2ecc71"),
    QColor("#f39c12"), QColor("#9b59b6"), QColor("#1abc9c"),
]


def pointer_color(pointer_id: int) -> QColor:
    return _POINTER_COLORS[pointer_id % len(_POINTER_COLORS)]


class CanvasView(QGraphicsView):
    pointClicked = Signal(int, int)   # frame-space (x, y)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = None
        self._markers = []
        self._frame_size = (0, 0)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)

    def update_frame(self, width: int, height: int, frame) -> None:
        """`frame` is a 2D grayscale numpy array, shape (height, width)."""
        self._frame_size = (width, height)
        image = QImage(frame.tobytes(), width, height, width, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(image)
        if self._pixmap_item is None:
            self._pixmap_item = self._scene.addPixmap(pixmap)
            self.setSceneRect(0, 0, width, height)
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)
        else:
            self._pixmap_item.setPixmap(pixmap)

    def set_markers(self, events) -> None:
        """`events` is a list of model.PrimitiveEvent with resolved (x, y) in
        frame-space (caller scales down from reference resolution first)."""
        for item in self._markers:
            self._scene.removeItem(item)
        self._markers = []
        radius = 10
        for i, (x, y, pointer_id, label) in enumerate(events):
            color = pointer_color(pointer_id)
            ellipse = QGraphicsEllipseItem(x - radius, y - radius, radius * 2, radius * 2)
            ellipse.setPen(QPen(color, 2))
            ellipse.setBrush(Qt.NoBrush)
            self._scene.addItem(ellipse)
            self._markers.append(ellipse)
            text = QGraphicsSimpleTextItem(label)
            text.setBrush(QBrush(color))
            text.setPos(x + radius, y - radius)
            self._scene.addItem(text)
            self._markers.append(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def mousePressEvent(self, event) -> None:
        if self._pixmap_item is not None and event.button() == Qt.LeftButton:
            pos = self.mapToScene(event.pos())
            w, h = self._frame_size
            x, y = int(pos.x()), int(pos.y())
            if 0 <= x < w and 0 <= y < h:
                self.pointClicked.emit(x, y)
        super().mousePressEvent(event)
