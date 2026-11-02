"""Lettura e scrittura immagini (percorsi con spazi/unicode, orientamento EXIF, alpha)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from .models import ArlocError

FORMATI = {"jpg": ".jpg", "jpeg": ".jpg", "png": ".png", "webp": ".webp"}


def load_image(path) -> np.ndarray:
    """Legge un'immagine come BGR uint8 (BGRA se ha trasparenza)."""
    p = Path(path)
    if not p.is_file():
        raise ArlocError(f"Non trovo il file: {p}")
    try:
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im)
            has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            im = im.convert("RGBA" if has_alpha else "RGB")
            arr = np.asarray(im)
    except Exception as e:  # file corrotto o formato non supportato
        raise ArlocError(f"Non riesco a leggere l'immagine: {p.name}") from e
    code = cv2.COLOR_RGBA2BGRA if arr.shape[2] == 4 else cv2.COLOR_RGB2BGR
    return np.ascontiguousarray(cv2.cvtColor(arr, code))


def save_image(img: np.ndarray, path, formato: str = "jpg", qualita: int = 90) -> Path:
    """Salva in sRGB senza EXIF. L'estensione viene adattata al formato."""
    fmt = formato.lower().lstrip(".")
    if fmt not in FORMATI:
        raise ArlocError(f"Formato non supportato: {formato} (usa jpg, png o webp)")
    ext = FORMATI[fmt]
    p = Path(path)
    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
        p = p.with_suffix(ext)
    else:
        p = p.with_name(p.name + ext)
    p.parent.mkdir(parents=True, exist_ok=True)

    if img.shape[2] == 4 and ext != ".png":
        a = img[:, :, 3:4].astype(np.float32) / 255
        img = (img[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)  # su bianco
    code = cv2.COLOR_BGRA2RGBA if img.shape[2] == 4 else cv2.COLOR_BGR2RGB
    im = Image.fromarray(cv2.cvtColor(img, code))
    try:
        if ext == ".jpg":
            im.save(p, "JPEG", quality=int(qualita), optimize=True)
        elif ext == ".webp":
            im.save(p, "WEBP", quality=int(qualita))
        else:
            im.save(p, "PNG", optimize=True)
    except OSError as e:
        raise ArlocError(f"Non riesco a salvare il file: {p}") from e
    return p
