"""Effetti: ombre, spessore, armonizzazione, grana, ricostruzione del verde residuo.

Tutte le funzioni lavorano su array float/uint8 BGR e su maschere alpha float32 in [0, 1].
"""
from __future__ import annotations

import math

import cv2
import numpy as np


def _shift(mask: np.ndarray, dx: float, dy: float) -> np.ndarray:
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(mask, M, (mask.shape[1], mask.shape[0]), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def _blur(mask: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(mask, (0, 0), max(sigma, 0.3))


def fill_green(bg: np.ndarray, green_mask: np.ndarray | None, alpha: np.ndarray) -> tuple[np.ndarray, float]:
    """Ricostruisce il verde non coperto dal mosaico. Restituisce (sfondo, frazione residua)."""
    if green_mask is None or not green_mask.any():
        return bg, 0.0
    covered = (alpha > 0.5).astype(np.uint8) * 255
    covered = cv2.dilate(covered, np.ones((3, 3), np.uint8))  # il bordo del mosaico copre i pixel di confine
    residual = cv2.bitwise_and(green_mask, cv2.bitwise_not(covered))
    frac = float((residual > 0).sum()) / max(1, int((green_mask > 0).sum()))
    # i pixel di bordo del verde sono misti: si allarga la maschera di 3 px
    residual = cv2.dilate(residual, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    residual[covered > 0] = 0
    if not residual.any():
        return bg, 0.0
    out = cv2.inpaint(bg, residual, 3, cv2.INPAINT_TELEA)
    return out, frac


def apply_shadows(bg: np.ndarray, alpha: np.ndarray, params, ppc: float) -> np.ndarray:
    """Ombra proiettata + ombra di contatto, in moltiplicazione sullo sfondo."""
    f = bg.astype(np.float32)
    a = math.radians(params.ombra_direzione_gradi)
    dist = params.ombra_distanza_cm * ppc
    dx, dy = dist * math.cos(a), dist * math.sin(a)

    sigma = ppc * (0.05 + 0.35 * params.ombra_morbidezza)
    moved = _shift(alpha, dx, dy)
    # nucleo più netto vicino al bordo + alone morbido: più naturale di una sola sfocatura
    cast = np.clip(0.6 * _blur(moved, sigma * 0.5) + 0.4 * _blur(moved, sigma * 1.6), 0, 1) * params.ombra_opacita * 1.3
    contact = _blur(cv2.dilate(alpha, np.ones((3, 3), np.uint8)), max(1.0, ppc * 0.05)) * 0.35
    shade = 1 - (1 - (1 - cast) * (1 - contact))  # le due ombre si compongono
    shade = np.clip(shade, 0, 1)
    return np.clip(f * shade[:, :, None], 0, 255)


def apply_thickness(bg: np.ndarray, mosaic: np.ndarray, alpha: np.ndarray, params, ppc: float) -> np.ndarray:
    """Fiancata scura del mosaico dal lato dell'ombra (spessore delle tessere)."""
    t = min(params.spessore_mm / 10.0 * ppc * 0.5, 12.0)
    if t < 1:
        return bg
    a = math.radians(params.ombra_direzione_gradi)
    ux, uy = math.cos(a), math.sin(a)
    wall = np.zeros_like(alpha)
    for k in np.linspace(0, t, max(2, int(t) + 1)):
        wall = np.maximum(wall, _shift(alpha, ux * k, uy * k))
    wall = np.clip(wall - alpha, 0, 1)
    solid = alpha > 0.5
    color = mosaic[solid].mean(axis=0) * 0.55 if solid.any() else np.zeros(3, np.float32)
    w = wall[:, :, None]
    return bg * (1 - w) + color.reshape(1, 1, 3) * w


def _lab(img_bgr_f: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.clip(img_bgr_f, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)


def harmonize(mosaic: np.ndarray, alpha: np.ndarray, bg: np.ndarray, params) -> np.ndarray:
    """Avvicina luce e colore del mosaico a quelli dello sfondo; poi correzioni manuali."""
    lab = _lab(mosaic)
    k = params.armonizzazione
    solid = alpha > 0.5
    if k > 0 and solid.sum() > 100:
        outer = cv2.dilate((alpha > 0.5).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1)
        r = int(0.15 * math.sqrt(solid.sum()))
        outer = cv2.dilate(outer, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        ring = (outer > 0) & ~cv2.dilate(solid.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        if ring.sum() > 100:
            blab = _lab(bg)
            for c, strength in ((0, 0.5), (1, 0.5), (2, 0.5)):
                m_mu, m_sd = lab[..., c][solid].mean(), lab[..., c][solid].std() + 1e-3
                r_mu, r_sd = blab[..., c][ring].mean(), blab[..., c][ring].std() + 1e-3
                gain = 1 + k * strength * (np.clip(r_sd / m_sd, 0.6, 1.5) - 1)
                lab[..., c] = (lab[..., c] - m_mu) * gain + m_mu + k * strength * (r_mu - m_mu)
    lab[..., 0] += params.luminosita * 255 * 0.4
    lab[..., 2] += params.temperatura * 40      # più giallo = più caldo
    lab[..., 1] += params.temperatura * 10
    lab = np.clip(lab, 0, 255).astype(np.uint8)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR).astype(np.float32)


def add_grain(mosaic: np.ndarray, alpha: np.ndarray, bg: np.ndarray, params) -> np.ndarray:
    """Rumore simile a quello dello sfondo (livello stimato dall'alta frequenza)."""
    if params.grana <= 0:
        return mosaic
    gray = cv2.cvtColor(np.clip(bg, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    sigma = float((gray - cv2.GaussianBlur(gray, (0, 0), 1.5))[alpha < 0.01].std())
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, alpha.shape).astype(np.float32) * sigma * (0.5 + 1.5 * params.grana)
    return mosaic + noise[:, :, None]
