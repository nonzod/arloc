"""Preset di output (Shopify, Etsy, personalizzato) ed esportazione."""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from .imageio import FORMATI, save_image
from .models import ArlocError, ComposeResult, OutputPreset

SHOPIFY = OutputPreset("shopify", 2048, 2048, "jpg", 90)
ETSY = OutputPreset("etsy", 2700, 2025, "jpg", 90)


def parse_preset(text: str) -> OutputPreset:
    """"shopify", "etsy" oppure "custom 1600x1200 png" (formato opzionale, default jpg)."""
    t = text.strip().lower()
    if t == "shopify":
        return SHOPIFY
    if t == "etsy":
        return ETSY
    m = re.fullmatch(r"custom\s+(\d{2,5})\s*[x×]\s*(\d{2,5})(?:\s+(\w+))?", t)
    if not m:
        raise ArlocError(f'Preset non valido: "{text}". Usa shopify, etsy oppure "custom 1600x1200 png".')
    fmt = (m.group(3) or "jpg").lower()
    if fmt not in FORMATI:
        raise ArlocError(f"Formato non supportato: {fmt} (usa jpg, png o webp).")
    return OutputPreset("custom", int(m.group(1)), int(m.group(2)), "jpg" if fmt == "jpeg" else fmt, 90)


def apply_preset(result: ComposeResult, preset: OutputPreset) -> np.ndarray:
    """Ritaglio "cover" centrato sul mosaico, poi ridimensionamento alle misure del preset."""
    img = result.image
    h, w = img.shape[:2]
    W, H = preset.larghezza, preset.altezza
    scale = max(W / w, H / h)
    cw, ch = min(w, W / scale), min(h, H / scale)  # finestra di ritaglio nell'immagine sorgente
    cx = min(max(result.center[0], cw / 2), w - cw / 2)
    cy = min(max(result.center[1], ch / 2), h - ch / 2)
    x0, y0 = int(round(cx - cw / 2)), int(round(cy - ch / 2))
    crop = img[y0:y0 + int(round(ch)), x0:x0 + int(round(cw))]
    if scale > 1:
        msg = "Lo sfondo è più piccolo del formato richiesto: l'immagine è stata ingrandita e può risultare meno nitida."
        if msg not in result.warnings:
            result.warnings.append(msg)
    interp = cv2.INTER_LANCZOS4 if scale > 1 else cv2.INTER_AREA
    return cv2.resize(crop, (W, H), interpolation=interp)


def export(result: ComposeResult, preset: OutputPreset, path_senza_estensione) -> Path:
    img = apply_preset(result, preset)
    return save_image(img, Path(path_senza_estensione), preset.formato, preset.qualita)
