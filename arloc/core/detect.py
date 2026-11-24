"""Rilevamento: area verde nello sfondo e angoli del mosaico."""
from __future__ import annotations

import cv2
import numpy as np

from .geometry import order_quad
from .imageio import downscale
from .models import Quad

GREEN_LO = (50, 150, 150)   # H (0-180), S, V
GREEN_HI = (70, 255, 255)
MIN_GREEN_FRACTION = 0.005
MIN_MOSAIC_FRACTION = 0.20


def _quad_from_contour(cnt: np.ndarray) -> Quad:
    """4 vertici dal contorno: approxPolyDP, altrimenti rettangolo minimo."""
    hull = cv2.convexHull(cnt)
    peri = cv2.arcLength(hull, True)
    for eps in np.linspace(0.01, 0.1, 19):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            return order_quad(approx.reshape(4, 2))
        if len(approx) < 4:
            break
    return order_quad(cv2.boxPoints(cv2.minAreaRect(hull)))


def find_green_area(img: np.ndarray) -> tuple[Quad, np.ndarray] | None:
    """Cerca il rettangolo #00FF00. Restituisce (quad, maschera 255 = verde) o None."""
    hsv = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, GREEN_LO, GREEN_HI)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    big = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(big) < MIN_GREEN_FRACTION * img.shape[0] * img.shape[1]:
        return None
    # solo il blocco principale: altri elementi verdi (nastri, loghi) non vanno ricostruiti
    out = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(out, [big], -1, 255, cv2.FILLED)
    return _quad_from_contour(big), out


def _full_quad(w: int, h: int) -> Quad:
    return Quad([(0.0, 0.0), (w - 1.0, 0.0), (w - 1.0, h - 1.0), (0.0, h - 1.0)])


def texture_mask(small: np.ndarray, factor: float = 0.6) -> np.ndarray:
    """Maschera (255) della zona con molta "grana" (fughe tra le tessere): nastro, supporto e sfondo sono lisci."""
    h, w = small.shape[:2]
    gray = cv2.cvtColor(small[:, :, :3], cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 5, 40, 5)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    grad = cv2.magnitude(gx, gy)
    r = max(5, int(0.012 * max(w, h)))
    dens = cv2.blur(grad, (2 * r + 1, 2 * r + 1))
    d8 = cv2.normalize(dens, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    t, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = (d8 > factor * t).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    return cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r + 1, r + 1)))  # compensa la sfocatura


def find_mosaic_corners(img: np.ndarray) -> Quad:
    """Angoli del mosaico (esclude nastro/bordo bianco). Fallback: immagine intera."""
    H, W = img.shape[:2]
    full = _full_quad(W, H)
    small, s = downscale(img, 1200)
    h, w = small.shape[:2]

    # PNG con trasparenza: la maschera è il canale alpha
    if small.shape[2] == 4 and small[:, :, 3].min() < 250:
        mask = (small[:, :, 3] > 127).astype(np.uint8) * 255
    else:
        mask = texture_mask(small)

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return full
    big = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(big) < MIN_MOSAIC_FRACTION * w * h:
        return full
    q = _quad_from_contour(big).as_array() / s
    # piccolo margine verso l'interno per non includere frange del bordo
    c = q.mean(axis=0)
    q = c + (q - c) * 0.99
    return Quad.from_array(q)
