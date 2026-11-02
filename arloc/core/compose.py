"""Composizione: mosaico raddrizzato, posizionato in prospettiva sullo sfondo."""
from __future__ import annotations

import cv2
import numpy as np

from . import effects
from .cutout import cutout_mosaic, inset_quad, quad_from_mask, use_shape
from .detect import find_green_area, find_mosaic_corners
from .geometry import order_quad, placement_quad, plane_size, px_per_cm
from .imageio import load_image
from .models import ArlocError, ComposeResult, Job, Quad

MAX_RECT_PX = 4000  # lato massimo del mosaico raddrizzato


def rectify_mosaic(img: np.ndarray, quad: Quad, w_cm: float, h_cm: float) -> np.ndarray:
    """Raddrizza il mosaico (BGRA: fuori dal quadrilatero l'alpha è 0), rapporto w_cm:h_cm."""
    if w_cm <= 0 or h_cm <= 0:
        raise ArlocError("Le misure del mosaico devono essere maggiori di zero.")
    q = order_quad(quad.as_array()).as_array()
    tl, tr, br, bl = q
    w = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    h = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    out_w = w if w / w_cm >= h / h_cm else h * w_cm / h_cm   # risoluzione nativa massima
    scale = min(1.0, MAX_RECT_PX / max(out_w, out_w * h_cm / w_cm))
    out_w = max(2, int(round(out_w * scale)))
    out_h = max(2, int(round(out_w * h_cm / w_cm)))
    if img.shape[2] == 3:
        img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    dst = np.float32([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]])
    M = cv2.getPerspectiveTransform(q, dst)
    return cv2.warpPerspective(img, M, (out_w, out_h), flags=cv2.INTER_LANCZOS4,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def _resize_to_long_side(img: np.ndarray, long_side: int) -> tuple[np.ndarray, float]:
    s = long_side / max(img.shape[:2])
    if s >= 1:
        return img, 1.0
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), s


def _apply_cutout(job: Job, mosaic: np.ndarray) -> tuple[np.ndarray, Quad]:
    """Quadrilatero del mosaico e immagine (BGRA se si usa la forma: alpha = maschera di scontorno)."""
    mode = (job.scontorno or "auto").strip().lower()
    if mode == "rettangolo":
        return mosaic, job.mosaico_quad or find_mosaic_corners(mosaic)
    mask = job.mosaico_maschera
    if mask is None:
        mask = cutout_mosaic(mosaic, job.mosaico_quad)
    elif mask.shape[:2] != mosaic.shape[:2]:
        mask = cv2.resize(mask, (mosaic.shape[1], mosaic.shape[0]), interpolation=cv2.INTER_LINEAR)
    qm = quad_from_mask(mask)
    if qm is None:
        return mosaic, job.mosaico_quad or find_mosaic_corners(mosaic)
    if not use_shape(mode, mask, job.mosaico_quad or qm, mosaic):
        return mosaic, job.mosaico_quad or inset_quad(qm)   # rettangolare: gli angoli dalla maschera sono più precisi
    alpha = mask if mosaic.shape[2] == 3 else cv2.min(mask, mosaic[:, :, 3])
    return np.dstack([mosaic[:, :, :3], alpha]), job.mosaico_quad or qm


def compose(job: Job, preview_max: int | None = None) -> ComposeResult:
    warnings: list[str] = []
    params = job.params.clamped()

    bg = load_image(job.sfondo)[:, :, :3]
    mosaic = load_image(job.mosaico)

    # 1. area di destinazione (sulle dimensioni originali dello sfondo)
    green_mask = None
    found = find_green_area(bg)
    if job.area is not None:
        area = order_quad(job.area.as_array())
        # il verde si ricostruisce solo se sta dentro l'area indicata
        if found is not None:
            c = tuple(float(v) for v in found[0].as_array().mean(axis=0))
            if cv2.pointPolygonTest(area.as_array(), c, False) >= 0:
                green_mask = found[1]
    elif found is not None:
        area, green_mask = found
    else:
        raise ArlocError("Non trovo il rettangolo verde: indica i 4 angoli dell'area sullo sfondo.")

    # anteprima veloce: tutto in scala ridotta
    s = 1.0
    if preview_max:
        bg, s = _resize_to_long_side(bg, preview_max)
        if s < 1:
            area = Quad.from_array(area.as_array() * s)
            if green_mask is not None:
                green_mask = cv2.resize(green_mask, (bg.shape[1], bg.shape[0]), interpolation=cv2.INTER_NEAREST)
    H, W = bg.shape[:2]

    # 2. mosaico raddrizzato
    mosaic, mquad = _apply_cutout(job, mosaic)
    rect = rectify_mosaic(mosaic, mquad, job.larghezza_mosaico_cm, job.altezza_mosaico_cm)

    # 3. scala e posizione
    ppc = px_per_cm(W, job.larghezza_sfondo_cm)
    mw, mh = job.larghezza_mosaico_cm * ppc, job.altezza_mosaico_cm * ppc
    dest = placement_quad(area, mw, mh, params, ppc)

    pw, ph = plane_size(area)
    if mw > pw * 1.15 or mh > ph * 1.15:
        warnings.append("Il mosaico risulterà più grande dell'area segnata: potrebbe coprire parte dello sfondo.")
    elif green_mask is not None and (mw < pw * 0.85 or mh < ph * 0.85):
        warnings.append("Il mosaico risulterà più piccolo dell'area segnata: il verde scoperto viene ricostruito.")

    # 4. warp del mosaico (prima riduzione "a pezzi" per evitare aliasing)
    if rect.shape[1] > 2 * mw:
        k = max(mw, 2) / rect.shape[1]
        rect = cv2.resize(rect, None, fx=k * 1.0, fy=k * 1.0, interpolation=cv2.INTER_AREA)
    rh, rw = rect.shape[:2]
    src = np.float32([[0, 0], [rw, 0], [rw, rh], [0, rh]])
    M = cv2.getPerspectiveTransform(src, dest.as_array())
    # canale alpha eroso di ~1 px dentro il mosaico per non portarsi dietro frange del bordo
    rect[:, :, 3] = cv2.erode(rect[:, :, 3], np.ones((3, 3), np.uint8))
    warped = cv2.warpPerspective(rect, M, (W, H), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    mosaic_px = warped[:, :, :3].astype(np.float32)
    alpha = warped[:, :, 3].astype(np.float32) / 255
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.7)

    if alpha.max() < 0.5:
        raise ArlocError("Il mosaico cade fuori dall'immagine: controlla area e spostamento.")

    # 5. effetti
    base, frac = effects.fill_green(bg, green_mask, alpha)
    if frac > 0.02:
        warnings.append("Resta del verde scoperto attorno al mosaico: è stato ricostruito, ma su sfondi con venature può vedersi.")
    base = base.astype(np.float32)
    mosaic_px = effects.harmonize(mosaic_px, alpha, base, params)
    mosaic_px = effects.add_grain(mosaic_px, alpha, base, params)
    shaded = effects.apply_shadows(base, alpha, params, ppc)
    shaded = effects.apply_thickness(shaded, mosaic_px, alpha, params, ppc)

    a3 = alpha[:, :, None]
    out = np.clip(shaded * (1 - a3) + mosaic_px * a3, 0, 255).astype(np.uint8)

    d = dest.as_array()
    return ComposeResult(image=out, center=(float(d[:, 0].mean()), float(d[:, 1].mean())),
                         mosaic_quad=Quad.from_array(d), warnings=warnings)
