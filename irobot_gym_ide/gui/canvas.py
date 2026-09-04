"""Live-frame canvas: shows the most recent device frame and lets the user
click on it to place a PrimitiveEvent's (x, y). Coordinates emitted by
`pointClicked` are in *frame pixel space* (the currently displayed image's
own width/height) -- callers scale to the project's reference resolution
(see main_window.py's `_frame_to_reference`), the same ratio-scaling
agent_client.py's `interactive`/`record` commands already do and for the
same reason: touch coordinates must land in the real device resolution,
not the (possibly downscaled) frame's own dimensions.

Capture mode (see `set_capture_mode`) repurposes the same canvas for a second
kind of interaction: instead of a single click placing a touch event, a
click-drag-release marks a rectangle, emitted by `regionSelected` (also in
frame pixel space) so MainWindow can crop that region out of the live frame
into an ImageTemplate for a Compare run-node -- see model.py's ImageTemplate
and gui/run_editor.py's COMPARE node support.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QPen, QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsSimpleTextItem,
)

_POINTER_COLORS = [
    QColor("#e74c3c"), QColor("#3498db"), QColor("#2ecc71"),
    QColor("#f39c12"), QColor("#9b59b6"), QColor("#1abc9c"),
]

_HUD_REGION_COLOR = QColor("#00bcd4")
_HUD_REGION_SELECTED_COLOR = QColor("#ff5722")


def pointer_color(pointer_id: int) -> QColor:
    return _POINTER_COLORS[pointer_id % len(_POINTER_COLORS)]


_MIN_CAPTURE_SIZE = 4   # px, in frame space -- below this, treat a drag as an accidental click, not a capture


class CanvasView(QGraphicsView):
    pointClicked = Signal(int, int)   # frame-space (x, y)
    regionSelected = Signal(int, int, int, int)   # frame-space (x0, y0, x1, y1), x0<x1, y0<y1 -- capture mode only

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = None
        self._markers = []
        self._hud_region_items = []
        self._frame_size = (0, 0)
        self._capture_mode = False
        self._rect_origin = None
        self._rect_item = None
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)

    def set_capture_mode(self, enabled: bool) -> None:
        """Toggles between the default click-to-place-a-point behavior and
        click-drag-release-to-select-a-rectangle. Cancels any in-progress drag
        when turned off mid-drag."""
        self._capture_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        if not enabled and self._rect_item is not None:
            self._scene.removeItem(self._rect_item)
            self._rect_item = None
            self._rect_origin = None

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

    def set_hud_regions(self, regions) -> None:
        """`regions` is [(x0, y0, x1, y1, label, selected), ...] in
        frame-space (caller scales down from reference resolution first,
        same as set_markers) -- draws each HudRegion's rectangle over the
        live mirror so it's visible right after capture, with the
        currently-selected one (if any) highlighted in a different color."""
        for item in self._hud_region_items:
            self._scene.removeItem(item)
        self._hud_region_items = []
        for x0, y0, x1, y1, label, selected in regions:
            color = _HUD_REGION_SELECTED_COLOR if selected else _HUD_REGION_COLOR
            rect = QGraphicsRectItem(QRectF(x0, y0, x1 - x0, y1 - y0))
            rect.setPen(QPen(color, 2 if selected else 1))
            rect.setBrush(Qt.NoBrush)
            rect.setZValue(2)
            self._scene.addItem(rect)
            self._hud_region_items.append(rect)
            text = QGraphicsSimpleTextItem(label)
            text.setBrush(QBrush(color))
            text.setPos(x0, max(0, y0 - 14))
            self._scene.addItem(text)
            self._hud_region_items.append(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def mousePressEvent(self, event) -> None:
        if self._capture_mode and self._pixmap_item is not None and event.button() == Qt.LeftButton:
            self._rect_origin = self.mapToScene(event.pos())
            self._rect_item = QGraphicsRectItem(QRectF(self._rect_origin, self._rect_origin))
            self._rect_item.setPen(QPen(QColor("#f1c40f"), 2, Qt.DashLine))
            self._rect_item.setZValue(3)
            self._scene.addItem(self._rect_item)
            return
        if self._pixmap_item is not None and event.button() == Qt.LeftButton:
            pos = self.mapToScene(event.pos())
            w, h = self._frame_size
            x, y = int(pos.x()), int(pos.y())
            if 0 <= x < w and 0 <= y < h:
                self.pointClicked.emit(x, y)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._rect_origin is not None:
            pos = self.mapToScene(event.pos())
            self._rect_item.setRect(QRectF(self._rect_origin, pos).normalized())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._rect_origin is not None:
            rect = self._rect_item.rect()
            self._scene.removeItem(self._rect_item)
            self._rect_item = None
            self._rect_origin = None
            w, h = self._frame_size
            x0 = max(0, min(w, round(rect.left())))
            y0 = max(0, min(h, round(rect.top())))
            x1 = max(0, min(w, round(rect.right())))
            y1 = max(0, min(h, round(rect.bottom())))
            if x1 - x0 >= _MIN_CAPTURE_SIZE and y1 - y0 >= _MIN_CAPTURE_SIZE:
                self.regionSelected.emit(x0, y0, x1, y1)
            return
        super().mouseReleaseEvent(event)
