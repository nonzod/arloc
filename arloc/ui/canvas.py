"""Anteprima grande: zoom con la rotella, pan, maniglie trascinabili per i quadrilateri."""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsPixmapItem,
                               QGraphicsPolygonItem, QGraphicsScene, QGraphicsView, QLabel)

from arloc.core.models import Quad
from arloc.ui.common import to_pixmap

ACCENT = QColor("#1F7A6D")
BRUSH_COLORS = {"add": QColor("#1F7A6D"), "remove": QColor("#B3402F")}
VEIL_BGR = (36, 40, 43)   # velo sulla zona esclusa dallo scontorno
UNDO_LEVELS = 20


def order_points(pts) -> list[tuple[float, float]]:
    """Alto-sx, alto-dx, basso-dx, basso-sx."""
    a = np.asarray(pts, dtype=float).reshape(4, 2)
    s, d = a.sum(axis=1), a[:, 0] - a[:, 1]
    return [tuple(a[s.argmin()]), tuple(a[d.argmax()]), tuple(a[s.argmax()]), tuple(a[d.argmin()])]


class Handle(QGraphicsEllipseItem):
    R = 8

    def __init__(self, canvas: "Canvas"):
        super().__init__(-self.R, -self.R, 2 * self.R, 2 * self.R)
        self._canvas = canvas
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges
                      | QGraphicsItem.ItemIgnoresTransformations)
        pen = QPen(ACCENT, 2.5)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(255, 255, 255, 235)))
        self.setZValue(10)
        self.setCursor(Qt.SizeAllCursor)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._canvas._rect.width() > 0:
            r = self._canvas._rect
            return QPointF(min(max(value.x(), 0), r.width()), min(max(value.y(), 0), r.height()))
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._canvas._handles_moved()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._canvas._handle_released()


class Canvas(QGraphicsView):
    quadEdited = Signal(object)  # Quad (coordinate dell'immagine logica)
    maskEdited = Signal(object)  # maschera uint8 dopo un ritocco col pennello (o Annulla)
    undoChanged = Signal(bool)   # c'è almeno un tratto da annullare

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Canvas")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#ECE9E4")))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._pix = QGraphicsPixmapItem()
        self._pix.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._pix)
        self._poly = QGraphicsPolygonItem()
        pen = QPen(ACCENT, 2)
        pen.setCosmetic(True)
        self._poly.setPen(pen)
        self._poly.setBrush(QBrush(QColor(31, 122, 109, 38)))
        self._poly.setZValue(5)
        self._scene.addItem(self._poly)
        # scontorno: velo sulla zona esclusa + pennello
        self._veil = QGraphicsPixmapItem()
        self._veil.setZValue(3)
        self._veil.setAcceptedMouseButtons(Qt.NoButton)
        self._veil.hide()
        self._scene.addItem(self._veil)
        self._mask: np.ndarray | None = None
        self._show_veil = False
        self._undo: list[np.ndarray] = []
        self._brush: str | None = None      # None | "add" | "remove"
        self._brush_frac = 0.04             # diametro / larghezza dell'immagine
        self._painting = False
        self._last_pt: QPointF | None = None
        self._cursor = QGraphicsEllipseItem()
        self._cursor.setZValue(20)
        self._cursor.setAcceptedMouseButtons(Qt.NoButton)
        self._cursor.hide()
        self._scene.addItem(self._cursor)
        self.setMouseTracking(True)
        self._handles: list[Handle] = []
        self._rect = QRectF()
        self._editable = False
        self._picking = False
        self._updating = False
        self._user_zoom = False
        self._has_image = False

        self._placeholder = QLabel(self.viewport())
        self._placeholder.setObjectName("CanvasPlaceholder")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._hint = QLabel(self.viewport())
        self._hint.setObjectName("CanvasHint")
        self._hint.hide()

    # ---- API
    def set_image(self, img: np.ndarray | None, logical_size: tuple[int, int] | None = None,
                  fit: bool = True):
        if img is None:
            self._has_image = False
            self._pix.setPixmap(to_pixmap(np.zeros((1, 1, 3), np.uint8)))
            self._pix.hide()
            self._rect = QRectF()
            self.set_quad(None)
            self._veil.hide()
            self._placeholder.show()
            self._layout_overlays()
            return
        h, w = img.shape[:2]
        lw, lh = logical_size or (w, h)
        self._pix.setPixmap(to_pixmap(img))
        self._pix.setScale(lw / w)
        self._pix.show()
        new_rect = QRectF(0, 0, lw, lh)
        changed = new_rect != self._rect
        self._rect = new_rect
        self._scene.setSceneRect(new_rect.adjusted(-lw, -lh, lw, lh))
        self._has_image = True
        self._placeholder.hide()
        self._update_veil()
        if fit or changed:
            self.fit()

    # ---- scontorno
    def set_mask(self, mask: np.ndarray | None, visible: bool = True, reset_undo: bool = True):
        """Maschera di scontorno (uint8 0/255). visible=False: tiene la maschera ma senza velo."""
        self._mask = None if mask is None else np.ascontiguousarray(mask.copy())
        self._show_veil = visible and mask is not None
        if reset_undo:
            self._undo.clear()
            self.undoChanged.emit(False)
        self._update_veil()

    def clear_undo(self):
        self._undo.clear()
        self.undoChanged.emit(False)

    def mask(self) -> np.ndarray | None:
        return self._mask

    def set_brush(self, mode: str | None):
        """mode: None (sposta/zoom), "add" o "remove"."""
        self._brush = mode if self._mask is not None else None
        active = self._brush is not None
        self.setDragMode(QGraphicsView.NoDrag if active else QGraphicsView.ScrollHandDrag)
        self.viewport().setCursor(Qt.BlankCursor if active else Qt.ArrowCursor)
        self._style_cursor()
        self._cursor.setVisible(False)

    def set_brush_size(self, frac: float):
        self._brush_frac = float(frac)
        self._style_cursor()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self):
        if self._undo and self._mask is not None:
            self._mask = self._undo.pop()
            self.undoChanged.emit(bool(self._undo))
            self._update_veil()
            self.maskEdited.emit(self._mask.copy())

    def _update_veil(self):
        m = self._mask
        if m is None or not self._show_veil or self._rect.isEmpty():
            self._veil.hide()
            return
        h, w = m.shape[:2]
        veil = np.empty((h, w, 4), np.uint8)
        veil[:, :, :3] = VEIL_BGR
        veil[:, :, 3] = (255 - m.astype(np.uint16)) * 160 // 255
        self._veil.setPixmap(to_pixmap(veil))
        self._veil.setScale(self._rect.width() / w)
        self._veil.show()

    def _brush_diameter(self) -> float:
        return max(2.0, self._brush_frac * self._rect.width())

    def _style_cursor(self):
        col = BRUSH_COLORS.get(self._brush or "add", ACCENT)
        d = self._brush_diameter() if not self._rect.isEmpty() else 20.0
        self._cursor.setRect(-d / 2, -d / 2, d, d)
        pen = QPen(col, 2)
        pen.setCosmetic(True)
        self._cursor.setPen(pen)
        fill = QColor(col)
        fill.setAlpha(55)
        self._cursor.setBrush(QBrush(fill))

    def _paint_to(self, p: QPointF):
        m = self._mask
        k = m.shape[1] / self._rect.width()
        v = 255 if self._brush == "add" else 0
        th = max(1, int(round(self._brush_diameter() * k)))
        p1 = (int(round(p.x() * k)), int(round(p.y() * k)))
        p0 = p1 if self._last_pt is None else (int(round(self._last_pt.x() * k)),
                                               int(round(self._last_pt.y() * k)))
        cv2.line(m, p0, p1, v, th)
        cv2.circle(m, p1, th // 2, v, -1)
        self._last_pt = p
        self._update_veil()

    def set_placeholder(self, text: str):
        self._placeholder.setText(text)
        self._layout_overlays()

    def set_hint(self, text: str):
        self._hint.setText(text)
        self._hint.setVisible(bool(text))
        self._hint.adjustSize()
        self._layout_overlays()

    def set_quad(self, quad: Quad | None, editable: bool = True, picking: bool = False):
        self._editable = editable
        self._picking = picking and editable
        self._clear_handles()
        pts = list(quad.points) if quad is not None else []
        self._set_points(pts)

    def set_quad_filled(self, filled: bool):
        self._poly.setBrush(QBrush(QColor(31, 122, 109, 38 if filled else 0)))

    def current_points(self) -> list[tuple[float, float]]:
        return [(h.pos().x(), h.pos().y()) for h in self._handles]

    def fit(self):
        if self._rect.isEmpty():
            return
        self.resetTransform()
        self.fitInView(self._rect, Qt.KeepAspectRatio)
        self._user_zoom = False

    # ---- interni
    def _clear_handles(self):
        for h in self._handles:
            self._scene.removeItem(h)
        self._handles = []
        self._poly.setPolygon(QPolygonF())

    def _set_points(self, pts):
        self._updating = True
        for p in pts:
            self._add_handle(p)
        self._updating = False
        self._update_poly()

    def _add_handle(self, p):
        h = Handle(self)
        h.setPos(QPointF(*p))
        h.setFlag(QGraphicsItem.ItemIsMovable, self._editable)
        h.setVisible(self._editable)
        self._scene.addItem(h)
        self._handles.append(h)

    def _update_poly(self):
        if len(self._handles) >= 2:
            self._poly.setPolygon(QPolygonF([h.pos() for h in self._handles]))
        else:
            self._poly.setPolygon(QPolygonF())
        self._poly.setVisible(len(self._handles) >= 2)

    def _handles_moved(self):
        if not self._updating:
            self._update_poly()

    def _handle_released(self):
        if len(self._handles) == 4 and self._editable:
            self.quadEdited.emit(Quad([tuple(map(float, p)) for p in self.current_points()]))

    def _layout_overlays(self):
        vp = self.viewport().rect()
        self._placeholder.setGeometry(vp.adjusted(48, 48, -48, -48))
        self._hint.adjustSize()
        self._hint.move(max(8, (vp.width() - self._hint.width()) // 2), 16)

    # ---- eventi
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._has_image and not self._user_zoom:
            self.fit()
        self._layout_overlays()

    def wheelEvent(self, e):
        if not self._has_image:
            return
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        cur = self.transform().m11()
        base = self.viewport().width() / max(1.0, self._rect.width())
        if (f < 1 and cur < base * 0.2) or (f > 1 and cur > base * 40):
            return
        self.scale(f, f)
        self._user_zoom = True

    def _on_handle(self, pos) -> bool:
        return any(isinstance(i, Handle) for i in self.items(pos))

    def mousePressEvent(self, e):
        if (self._brush and self._mask is not None and e.button() == Qt.LeftButton
                and not self._on_handle(e.position().toPoint())):
            p = self.mapToScene(e.position().toPoint())
            if self._rect.contains(p):
                self._undo.append(self._mask.copy())
                del self._undo[:-UNDO_LEVELS]
                self.undoChanged.emit(True)
                self._painting, self._last_pt = True, None
                self._paint_to(p)
            return
        if (self._picking and e.button() == Qt.LeftButton and len(self._handles) < 4
                and self.itemAt(e.position().toPoint()) in (None, self._pix, self._poly)):
            p = self.mapToScene(e.position().toPoint())
            if self._rect.contains(p):
                self._add_handle((p.x(), p.y()))
                self._update_poly()
                if len(self._handles) == 4:
                    pts = order_points(self.current_points())
                    self._updating = True
                    for h, q in zip(self._handles, pts):
                        h.setPos(QPointF(*q))
                    self._updating = False
                    self._update_poly()
                    self._picking = False
                    self._handle_released()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._brush and self._mask is not None:
            p = self.mapToScene(e.position().toPoint())
            self._cursor.setPos(p)
            self._cursor.setVisible(self._rect.contains(p) or self._painting)
            if self._painting:
                self._paint_to(p)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._painting:
            self._painting = False
            self._last_pt = None
            self.maskEdited.emit(self._mask.copy())
            return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        self._cursor.hide()
        super().leaveEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self._has_image:
            self.fit()
        else:
            super().mouseDoubleClickEvent(e)
