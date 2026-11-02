"""Scontorno del mosaico: maschera con la forma reale (bordi irregolari, mosaici tondi o sagomati)."""
from __future__ import annotations

import cv2
import numpy as np

from .detect import _quad_from_contour, texture_mask
from .geometry import order_quad
from .models import Quad

WORK_SIZE = 1000          # lato lungo della copia di lavoro
SHAPE_AREA_RATIO = 0.92   # "auto": forma se la maschera copre meno del 92% del quadrilatero
MODES = ("auto", "rettangolo", "forma")


def has_alpha(img: np.ndarray) -> bool:
    return img.ndim == 3 and img.shape[2] == 4 and int(img[:, :, 3].min()) < 250


def _fill_external(mask: np.ndarray) -> np.ndarray:
    """Riempie i buchi interni (le fughe chiare tra le tessere non sono buchi)."""
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(mask)
    cv2.drawContours(out, cnts, -1, 255, cv2.FILLED)
    return out


def _largest(mask: np.ndarray) -> np.ndarray:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return mask
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (lab == k).astype(np.uint8) * 255


def _ellipse(d: int) -> np.ndarray:
    d = max(1, int(d)) | 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))


def _clean(mask: np.ndarray, r: int) -> np.ndarray:
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _ellipse(r // 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _ellipse(r))
    mask = _fill_external(_largest(mask))
    # piccole rientranze/buchi che toccano il bordo dell'immagine
    inv = (mask == 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    lim = 0.015 * int((mask > 0).sum())
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < lim:
            mask[lab == k] = 255
    return mask


def _soft_up(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Maschera piccola binaria -> risoluzione originale, con bordo leggermente sfumato."""
    sm = cv2.GaussianBlur(mask, (0, 0), 1.2)
    return cv2.resize(sm, size, interpolation=cv2.INTER_LINEAR)


def _grabcut(small: np.ndarray, quad: np.ndarray | None) -> np.ndarray:
    h, w = small.shape[:2]
    r = max(5, int(0.012 * max(w, h)))
    def compact(tex):
        if not tex.any():
            return np.zeros((h, w), np.uint8)
        return _fill_external(_largest(cv2.morphologyEx(tex, cv2.MORPH_CLOSE, _ellipse(2 * r))))
    # zona con grana; l'apertura toglie strisce sottili dello sfondo (venature, listelli)
    tex = texture_mask(small)
    opened = cv2.morphologyEx(tex, cv2.MORPH_OPEN, _ellipse(7 * r))
    cand = compact(opened if opened.any() else tex)
    strong = cand
    if quad is not None:
        qm = np.zeros((h, w), np.uint8)
        cv2.fillPoly(qm, [np.round(quad).astype(np.int32)], 255)
        margin = max(r, int(0.03 * max(w, h)))
        near = cv2.dilate(qm, _ellipse(2 * margin))
        inner = cv2.erode(qm, _ellipse(2 * margin))
        gc = np.full((h, w), cv2.GC_BGD, np.uint8)
        gc[near > 0] = cv2.GC_PR_BGD
        gc[qm > 0] = cv2.GC_PR_FGD
        # dentro il quad le zone lisce e lontane dal bordo restano comunque candidate
        gc[(inner > 0) & (cand > 0)] = cv2.GC_FGD
        gc[(inner > 0) & (cand == 0)] = cv2.GC_PR_FGD
        core = cv2.erode(inner, _ellipse(4 * r))
        gc[core > 0] = cv2.GC_FGD
    else:
        if not cand.any():
            return np.full((h, w), 255, np.uint8)
        b = max(2, int(0.03 * max(w, h)))
        border = np.ones((h, w), np.uint8)
        border[b:-b, b:-b] = 0
        # il bordo dell'immagine è sfondo certo, tranne dove c'è grana (mosaico a tutto campo)
        border[cv2.dilate(texture_mask(small), _ellipse(3 * r)) > 0] = 0
        gc = np.full((h, w), cv2.GC_BGD, np.uint8)
        gc[cv2.dilate(cand, _ellipse(32 * r)) > 0] = cv2.GC_PR_BGD
        gc[cv2.dilate(cand, _ellipse(16 * r)) > 0] = cv2.GC_PR_FGD
        gc[border > 0] = cv2.GC_BGD
        gc[cv2.erode(cand, _ellipse(4 * r)) > 0] = cv2.GC_FGD
    # la cornice dell'immagine è sempre sfondo certo solo se l'area non la tocca in modo evidente
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    if (gc == cv2.GC_FGD).sum() < 50 or (gc == cv2.GC_BGD).sum() < 50:
        return (gc != cv2.GC_BGD).astype(np.uint8) * 255
    cv2.grabCut(np.ascontiguousarray(small[:, :, :3]), gc, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
    return np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


def cutout_mosaic(img: np.ndarray, quad: Quad | None = None) -> np.ndarray:
    """Maschera uint8 (255 = mosaico) alla risoluzione di `img`, con bordo leggermente sfumato.

    PNG con trasparenza: si usa il canale alpha. Altrimenti GrabCut su una copia ridotta,
    inizializzato dal quadrilatero (se dato) e dalla "grana" delle fughe.
    """
    H, W = img.shape[:2]
    if has_alpha(img):
        a = (img[:, :, 3] > 127).astype(np.uint8) * 255
        s = min(1.0, WORK_SIZE / max(W, H))
        sm = cv2.resize(a, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else a
        sm = _clean((sm > 127).astype(np.uint8) * 255, max(3, int(0.004 * max(sm.shape))))
        return _soft_up(sm, (W, H))
    s = min(1.0, WORK_SIZE / max(W, H))
    small = cv2.resize(img[:, :, :3], None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img[:, :, :3]
    q = order_quad(quad.as_array()).as_array() * s if quad is not None else None
    m = _grabcut(small, q)
    m = _clean(m, max(5, int(0.008 * max(small.shape[:2]))))
    if not m.any():
        m = np.full(small.shape[:2], 255, np.uint8)
    return _soft_up(m, (W, H))


def quad_from_mask(mask: np.ndarray) -> Quad | None:
    """Quadrilatero che contiene la forma: 4 vertici dal contorno se la racchiudono, altrimenti il rettangolo minimo."""
    cnts, _ = cv2.findContours((mask > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    hull = cv2.convexHull(max(cnts, key=cv2.contourArea))
    tol = 0.01 * np.sqrt(cv2.contourArea(hull))
    q = _quad_from_contour(hull)
    poly = q.as_array()
    tight = cv2.contourArea(poly) <= 1.06 * cv2.contourArea(hull)   # altrimenti (es. forma tonda) un 4 lati qualsiasi non è un bel rettangolo
    if tight and all(cv2.pointPolygonTest(poly, (float(x), float(y)), True) >= -tol for x, y in hull.reshape(-1, 2)):
        return q
    rect = cv2.minAreaRect(hull)
    x, y, bw, bh = cv2.boundingRect(hull)
    if bw * bh <= 1.15 * rect[1][0] * rect[1][1]:   # forme tonde: meglio un rettangolo dritto
        return order_quad([(x, y), (x + bw, y), (x + bw, y + bh), (x, y + bh)])
    return order_quad(cv2.boxPoints(rect))


def inset_quad(q: Quad, k: float = 0.99) -> Quad:
    """Quadrilatero rimpicciolito verso il centro: evita le frange del bordo."""
    a = q.as_array()
    c = a.mean(axis=0)
    return Quad.from_array(c + (a - c) * k)


def quad_coverage(mask: np.ndarray, quad: Quad) -> float:
    """Frazione dell'area del quadrilatero coperta dalla maschera."""
    qm = np.zeros(mask.shape[:2], np.uint8)
    cv2.fillPoly(qm, [np.round(quad.as_array()).astype(np.int32)], 1)
    tot = int(qm.sum())
    if tot == 0:
        return 1.0
    return float(((mask > 127) & (qm > 0)).sum()) / tot


def use_shape(mode: str, mask: np.ndarray | None, quad: Quad, img: np.ndarray | None = None) -> bool:
    """Decide se usare la forma o il rettangolo. mode: auto | rettangolo | forma."""
    mode = (mode or "auto").strip().lower()
    if mode == "rettangolo" or mask is None:
        return False
    if mode == "forma":
        return True
    if img is not None and has_alpha(img):
        return True
    return quad_coverage(mask, quad) < SHAPE_AREA_RATIO
