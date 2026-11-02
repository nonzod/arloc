"""Ritocco AI finale (SPERIMENTALE, facoltativo, solo OpenRouter).

Un modello che riceve e restituisce immagini armonizza luce, ombre e colore attorno al mosaico.
Il mosaico però non viene mai "inventato": dentro la sua maschera si rimettono i pixel originali.
Mai eccezioni verso il chiamante: in caso di problemi si ritorna l'immagine originale e un avviso.
"""
from __future__ import annotations

import base64
import hashlib

import cv2
import numpy as np

from . import settings as _settings
from .instructions import OPENROUTER_URL, _or_err_text, _or_headers, httpx, openrouter_models
from .models import ComposeResult

PROMPT_VERSION = "1"
SEND_MAX = 1536          # lato lungo dell'immagine inviata
SHIFT_MAX = 0.015        # spostamento massimo ammesso (frazione del lato lungo)
DEFORM_MAX = 0.02        # deformazione massima ammessa (scarto della matrice dall'identità)
GAIN_MAX = 0.10          # correzione di luminosità massima sul mosaico (±10%)
MOVED_MSG = "Il ritocco AI ha spostato l'immagine: tenuto il risultato originale."
# stima: token d'immagine in uscita (≈1K px) e in ingresso per il calcolo del costo
_OUT_TOKENS, _IN_TOKENS = 1120, 1500

PROMPT = (
    "You are a photo retoucher. Edit this photo, a composite in which a mosaic panel was digitally placed on a "
    "background scene. Make the composite look like a single real photograph: harmonize the lighting, "
    "the color temperature, the soft shadows and the contact shadows of the scene around the mosaic and along "
    "its border so that it looks naturally integrated.\n"
    "STRICT RULES: Do NOT change the composition, the framing, the crop or the aspect ratio. Do NOT move, resize, "
    "rotate, redraw or recolor the mosaic or any of its tiles: its position, shape, pattern and tile colors "
    "must stay exactly as they are. Do NOT add, remove or invent any object, text or logo. "
    "Return the full image at the same framing, with only subtle lighting and color adjustments."
)


# ---------------------------------------------------------------- utilità
def _encode_jpeg(img: np.ndarray) -> bytes:
    h, w = img.shape[:2]
    s = SEND_MAX / max(h, w)
    if s < 1:
        img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", np.ascontiguousarray(img), [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError("Impossibile preparare l'immagine.")
    return buf.tobytes()


def _decode(raw: bytes) -> np.ndarray | None:
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    return img if img is not None and img.size else None


def _cache_path(digest: str):
    return _settings.cache_dir() / f"ritocco_{digest}.bin"


def _prune_cache(keep: int = 40) -> None:
    try:
        files = sorted(_settings.cache_dir().glob("ritocco_*.bin"), key=lambda p: p.stat().st_mtime)
        for p in files[:-keep]:
            p.unlink(missing_ok=True)
    except Exception:
        pass


def _image_from_response(data) -> bytes | None:
    """Estrae la prima immagine da choices[0].message.images[].image_url.url (data URL base64)."""
    msg = data["choices"][0]["message"]
    cands = list(msg.get("images") or [])
    content = msg.get("content")
    if isinstance(content, list):   # alcuni servizi mettono le immagini tra le parti del contenuto
        cands += [p for p in content if isinstance(p, dict) and p.get("type") in ("image_url", "output_image")]
    for c in cands:
        url = c
        if isinstance(c, dict):
            url = c.get("image_url", c.get("url"))
            if isinstance(url, dict):
                url = url.get("url")
        if not isinstance(url, str):
            continue
        if url.startswith("data:"):
            try:
                return base64.b64decode(url.split(",", 1)[1])
            except Exception:
                continue
        if url.startswith("http"):
            try:
                r = httpx.get(url, timeout=60.0)
                if r.status_code < 400:
                    return r.content
            except Exception:
                continue
    return None


def _http_warning(status: int, detail: str, model: str) -> str:
    d = (detail or "").lower()
    if status in (401, 403):
        return "Ritocco AI non eseguito: chiave OpenRouter non valida."
    if status == 402:
        return "Ritocco AI non eseguito: credito OpenRouter esaurito (ricaricalo sul sito di OpenRouter)."
    if status == 429:
        return "Ritocco AI non eseguito: troppe richieste a OpenRouter, riprova tra poco."
    if status == 404 or "no endpoints" in d or "not a valid model" in d:
        return (f"Ritocco AI non eseguito: il modello «{model}» non esiste su OpenRouter "
                "(controllalo nelle Impostazioni, Modelli avanzati, Verifica).")
    if status == 400:
        return (f"Ritocco AI non eseguito: il modello «{model}» non accetta questa richiesta "
                "(deve ricevere e restituire immagini).")
    return "Ritocco AI non eseguito: errore di OpenRouter."


def _request(model: str, jpeg: bytes, key: str) -> tuple[bytes | None, str | None]:
    """Chiama OpenRouter. Ritorna (immagine, None) oppure (None, avviso in italiano)."""
    body = {
        "model": model,
        "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,"
                                                + base64.standard_b64encode(jpeg).decode("ascii")}},
        ]}],
    }
    try:
        r = httpx.post(OPENROUTER_URL + "/chat/completions", headers=_or_headers(key), json=body, timeout=180.0)
    except httpx.TimeoutException:
        return None, "Ritocco AI non eseguito: OpenRouter non risponde (tempo scaduto)."
    except httpx.HTTPError:
        return None, "Ritocco AI non eseguito: impossibile contattare OpenRouter (rete)."
    try:
        data = r.json()
    except Exception:
        data = None
    err = isinstance(data, dict) and data.get("error")
    if r.status_code >= 400 or err:
        code = r.status_code
        if code < 400 and isinstance(err, dict) and isinstance(err.get("code"), int):
            code = err["code"]
        return None, _http_warning(code, _or_err_text(data), model)
    try:
        raw = _image_from_response(data)
    except Exception:
        raw = None
    if raw is None:
        return None, f"Ritocco AI non eseguito: il modello «{model}» non ha restituito nessuna immagine."
    return raw, None


# ---------------------------------------------------------------- allineamento e protezione
def _align(orig: np.ndarray, out: np.ndarray):
    """Stima come `out` (già alle dimensioni di `orig`) è spostata/deformata rispetto a `orig`.

    Ritorna (ok, matrice 2x3 per riportare out su orig o None).
    """
    h, w = orig.shape[:2]
    s = 320 / max(h, w)
    sw, sh = max(8, round(w * s)), max(8, round(h * s))
    a = cv2.cvtColor(cv2.resize(orig, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(cv2.resize(out, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
    a, b = cv2.GaussianBlur(a, (0, 0), 1.0), cv2.GaussianBlur(b, (0, 0), 1.0)
    # luminosità: il ritocco cambia la luce, l'allineamento no
    a, b = a - a.mean(), b - b.mean()
    win = cv2.createHanningWindow((sw, sh), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a, b, win)
    if max(abs(dx), abs(dy)) / max(sw, sh) > SHIFT_MAX * 2:
        return False, None
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)
        cc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_AFFINE, crit, None, 5)
        reliable = cc >= 0.8
    except cv2.error:
        reliable = False
    if reliable:
        dev = float(np.abs(warp[:, :2] - np.eye(2)).max())
    else:   # ECC non affidabile (il ritocco ha cambiato molto): basta lo spostamento globale, se la stima è credibile
        if resp < 0.1:
            return False, None
        warp, dev = np.float32([[1, 0, dx], [0, 1, dy]]), 0.0
    shift = float(max(abs(warp[0, 2]), abs(warp[1, 2]))) / max(sw, sh)
    if shift > SHIFT_MAX or dev > DEFORM_MAX:
        return False, None
    # matrice alla scala reale (le traslazioni scalano con le dimensioni)
    full = warp.copy()
    full[:, 2] = warp[:, 2] / s
    return True, full


def _protect(orig: np.ndarray, out: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Fuori dalla maschera il ritocco AI; dentro (erosa) i pixel originali, con piccola correzione di luminosità."""
    h, w = orig.shape[:2]
    long_side = max(h, w)
    sigma = max(1.2, long_side / 900)
    er = int(round(2 * sigma)) + 1
    m = (mask > 127).astype(np.uint8)
    inner = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * er + 1, 2 * er + 1)))
    alpha = cv2.GaussianBlur(inner.astype(np.float32), (0, 0), sigma)
    sel = inner > 0
    o = orig.astype(np.float32)
    ai = out.astype(np.float32)
    gain = 1.0
    if sel.sum() > 50:
        lo = float(cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY)[sel].mean())
        la = float(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[sel].mean())
        if lo > 1:
            gain = float(min(1 + GAIN_MAX, max(1 - GAIN_MAX, la / lo)))
    keep = np.clip(o * gain, 0, 255)
    a3 = alpha[:, :, None]
    return np.clip(ai * (1 - a3) + keep * a3, 0, 255).astype(np.uint8)


def _mask_for(result: ComposeResult, mask) -> np.ndarray:
    h, w = result.image.shape[:2]
    if mask is None:
        mask = result.mosaic_mask
    if mask is None:
        mask = np.zeros((h, w), np.uint8)
        cv2.fillPoly(mask, [np.round(result.mosaic_quad.as_array()).astype(np.int32)], 255)
    if mask.shape[:2] != (h, w):
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
    return mask


# ---------------------------------------------------------------- API pubblica
def estimate_cost_usd(settings=None) -> float | None:
    """Stima del costo di un ritocco (dollari), dai prezzi pubblici di OpenRouter; None se non disponibile."""
    try:
        settings = settings or _settings.load_settings()
        models = openrouter_models()
        pr = (models or {}).get(settings.openrouter_model_retouch, {}).get("pricing") or {}
        img_out = float(pr.get("image_output") or pr.get("completion") or 0)
        cost = img_out * _OUT_TOKENS + float(pr.get("prompt") or 0) * _IN_TOKENS
        return cost if cost > 0 else None
    except Exception:
        return None


def harmonize(result: ComposeResult, mosaic_mask_out: np.ndarray | None, settings=None) -> tuple[np.ndarray, str | None]:
    """Ritocco AI finale. Ritorna (immagine BGR finale, avviso in italiano o None). Mai eccezioni."""
    orig = result.image
    try:
        settings = settings or _settings.load_settings()
        if settings.provider != "openrouter":
            return orig, "Il ritocco AI funziona solo con OpenRouter: scegli OpenRouter nelle Impostazioni."
        key = _settings.get_openrouter_key()
        if not key:
            return orig, "Ritocco AI non eseguito: manca la chiave di OpenRouter (impostala nelle Impostazioni)."
        model = settings.openrouter_model_retouch
        mask = _mask_for(result, mosaic_mask_out)
        jpeg = _encode_jpeg(orig)
        digest = hashlib.sha256(jpeg + b"|" + model.encode() + b"|" + PROMPT_VERSION.encode()
                                + b"|" + PROMPT.encode()).hexdigest()
        raw = None
        try:
            raw = _cache_path(digest).read_bytes()
        except Exception:
            pass
        if raw is None:
            raw, warn = _request(model, jpeg, key)
            if raw is None:
                return orig, warn
            try:
                _cache_path(digest).write_bytes(raw)
                _prune_cache()
            except Exception:
                pass
        out = _decode(raw)
        if out is None:
            return orig, "Ritocco AI non eseguito: l'immagine ricevuta non è leggibile."
        h, w = orig.shape[:2]
        if abs((out.shape[1] / out.shape[0]) / (w / h) - 1) > 0.03:
            return orig, MOVED_MSG
        if out.shape[:2] != (h, w):
            out = cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC if out.shape[1] < w else cv2.INTER_AREA)
        ok, warp = _align(orig, out)
        if not ok:
            return orig, MOVED_MSG
        if warp is not None and np.abs(warp - np.eye(2, 3)).max() > 1e-4:
            out = cv2.warpAffine(out, warp, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                 borderMode=cv2.BORDER_REPLICATE)
        return _protect(orig, out, mask), None
    except Exception:  # noqa: BLE001
        return orig, "Ritocco AI non riuscito: tenuto il risultato originale."
