"""Lettura e scrittura immagini (percorsi con spazi/unicode, orientamento EXIF, alpha)."""
from __future__ import annotations

from functools import lru_cache
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


def file_key(path) -> tuple[str, int, int]:
    """Identità di un file su disco (percorso, data di modifica, dimensione): cambia se il file cambia."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        raise ArlocError(f"Non trovo il file: {p}") from None
    return str(p.resolve()), st.st_mtime_ns, st.st_size


@lru_cache(maxsize=4)
def _load_cached(key: tuple[str, int, int]) -> np.ndarray:
    img = load_image(key[0])
    img.flags.writeable = False
    return img


def load_image_cached(path) -> np.ndarray:
    """Come `load_image`, ma tiene in memoria le ultime immagini lette (anteprime ripetute).

    L'array restituito è in SOLA LETTURA: chi deve modificarlo ne faccia una copia.
    """
    return _load_cached(file_key(path))


def downscale(img: np.ndarray, long_side: int,
              interpolation: int = cv2.INTER_AREA) -> tuple[np.ndarray, float]:
    """Riduce l'immagine (o la maschera) finché il lato lungo è al massimo `long_side`. Ritorna (img, scala)."""
    s = long_side / max(img.shape[:2])
    if s >= 1:
        return img, 1.0
    return cv2.resize(img, None, fx=s, fy=s, interpolation=interpolation), s


def encode_jpeg(img: np.ndarray, long_side: int, quality: int = 90) -> bytes:
    """JPEG (BGR, alpha ignorato) ridotto al lato lungo indicato: per inviare immagini ai servizi AI."""
    if img.ndim == 3 and img.shape[2] == 4:
        img = img[:, :, :3]
    img, _ = downscale(img, long_side)
    ok, buf = cv2.imencode(".jpg", np.ascontiguousarray(img), [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise ValueError("Impossibile preparare l'immagine.")
    return buf.tobytes()


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
