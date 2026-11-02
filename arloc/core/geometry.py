"""Geometria: ordinamento dei quadrilateri, scala, posizionamento in prospettiva."""
from __future__ import annotations

import math

import cv2
import numpy as np

from .models import ArlocError, ComposeParams, Quad


def order_quad(pts) -> Quad:
    """Ordina 4 punti: alto-sx, alto-dx, basso-dx, basso-sx."""
    a = np.asarray(pts, dtype=np.float32).reshape(-1, 2)
    if len(a) != 4:
        raise ArlocError("Servono esattamente 4 punti.")
    c = a.mean(axis=0)
    # per angolo attorno al centro (coordinate immagine: y verso il basso, quindi orario)
    a = a[np.argsort(np.arctan2(a[:, 1] - c[1], a[:, 0] - c[0]))]
    start = int(np.argmin(a.sum(axis=1)))  # alto-sx = somma minima
    return Quad.from_array(np.roll(a, -start, axis=0))


def parse_area(text: str) -> Quad:
    """Legge "x1,y1;x2,y2;x3,y3;x4,y4" (ordine qualsiasi)."""
    try:
        pts = [tuple(float(v) for v in p.strip().split(",")) for p in text.replace("|", ";").split(";") if p.strip()]
        ok = len(pts) == 4 and all(len(p) == 2 for p in pts)
    except ValueError:
        ok = False
    if not ok:
        raise ArlocError('Area non valida: scrivi 4 punti in pixel, ad esempio "100,200;400,200;400,500;100,500".')
    q = order_quad(pts)
    if cv2.contourArea(q.as_array()) < 4:
        raise ArlocError("Area non valida: i 4 punti non formano un quadrilatero.")
    return q


def px_per_cm(bg_width_px: float, bg_width_cm: float) -> float:
    if bg_width_cm <= 0:
        raise ArlocError("La larghezza reale dello sfondo deve essere maggiore di zero.")
    return bg_width_px / bg_width_cm


def plane_size(area: Quad) -> tuple[float, float]:
    """Dimensioni (larghezza, altezza) del rettangolo del piano stimato dall'area."""
    tl, tr, br, bl = (np.array(p) for p in area.points)
    w = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    h = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    return float(w), float(h)


def auto_mosaic_size(area: Quad, mosaic_quad: Quad, riempimento: float) -> tuple[float, float, float]:
    """Misure automatiche: (larghezza px, altezza px, px_per_cm fittizio) del mosaico nel piano dell'area.

    Il mosaico mantiene le proprie proporzioni (lati opposti medi del suo quad) ed è la massima
    dimensione che entra nel rettangolo del piano dell'area, moltiplicata per `riempimento`.
    px/cm fittizio: il lato corto del mosaico vale AUTO_SHORT_SIDE_CM, così ombra, spessore e
    spostamenti hanno proporzioni simili alla modalità reale.
    """
    aw, ah = plane_size(area)
    mw0, mh0 = plane_size(mosaic_quad)
    if min(aw, ah, mw0, mh0) < 1:
        raise ArlocError("L'area o il mosaico sono troppo piccoli.")
    k = min(aw / mw0, ah / mh0) * riempimento
    mw, mh = mw0 * k, mh0 * k
    return mw, mh, min(mw, mh) / AUTO_SHORT_SIDE_CM


AUTO_SHORT_SIDE_CM = 30.0


def placement_quad(area: Quad, mosaic_w_px: float, mosaic_h_px: float,
                   params: ComposeParams, ppc: float) -> Quad:
    """Dove cade il mosaico (angoli in pixel) dentro l'area, con prospettiva."""
    w, h = plane_size(area)
    if w < 1 or h < 1:
        raise ArlocError("L'area indicata è troppo piccola.")
    rect = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(rect, area.as_array())

    cx = w / 2 + params.offset_x_cm * ppc
    cy = h / 2 + params.offset_y_cm * ppc
    hw, hh = mosaic_w_px / 2, mosaic_h_px / 2
    corners = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]], dtype=np.float32)
    t = math.radians(params.rotazione_gradi)
    rot = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]], dtype=np.float32)
    plane_pts = corners @ rot.T + np.array([cx, cy], dtype=np.float32)
    dst = cv2.perspectiveTransform(plane_pts.reshape(1, 4, 2), H).reshape(4, 2)
    return Quad.from_array(dst)  # senza riordinare: mantiene la corrispondenza con gli angoli del mosaico
