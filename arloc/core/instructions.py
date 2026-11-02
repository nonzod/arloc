"""Integrazione con Claude: istruzioni in testo libero -> ComposeParams, suggerimento luce.

Due servizi: Anthropic (`client.messages.create(output_config={"effort", "format": json_schema})`)
oppure OpenRouter (API compatibile OpenAI via `httpx`). Mai eccezioni verso il chiamante.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from pathlib import Path

try:  # dipendenza dell'SDK anthropic (il pacchetto si chiama httpx2 nelle versioni recenti)
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from .models import ComposeParams
from . import settings as _settings

SCHEMA_VERSION = "1"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
_OR_HEADERS = {"HTTP-Referer": "https://github.com/tourtools/arloc", "X-Title": "Arloc"}

SYSTEM_PROMPT = """Sei l'assistente di Arloc, un programma che compone la foto di un mosaico su uno sfondo (un tavolo, un piano di lavoro).
Ricevi istruzioni in italiano e le traduci in parametri numerici. Restituisci SOLO i parametri citati o chiaramente implicati; ometti tutti gli altri.

Parametri (intervalli):
- rotazione_gradi (-180..180): rotazione extra del mosaico; positivo = senso orario.
- offset_x_cm, offset_y_cm (-100..100): spostamento dal centro dell'area; x positivo = destra, y positivo = basso.
- ombra_direzione_gradi (0..360): verso in cui cade l'ombra. 0 = destra, 90 = basso, 180 = sinistra, 270 = alto.
- ombra_distanza_cm (0..5): distanza dell'ombra (default 0.6).
- ombra_morbidezza (0..1): sfocatura dell'ombra; 0 = netta, 1 = molto morbida (default 0.5).
- ombra_opacita (0..1): intensita' dell'ombra (default 0.45).
- spessore_mm (0..15): spessore simulato del mosaico (default 4).
- luminosita (-0.5..0.5): negativo = piu' scuro, positivo = piu' chiaro.
- temperatura (-0.5..0.5): negativo = piu' freddo, positivo = piu' caldo.
- armonizzazione (0..1): quanto adattare il mosaico alla luce dello sfondo (default 0.3).
- grana (0..1): rumore fotografico.

Esempi:
- "ombra a sinistra" -> {"ombra_direzione_gradi": 180}
- "ombra in basso a destra" -> {"ombra_direzione_gradi": 45}
- "ombra piu' netta" -> {"ombra_morbidezza": 0.2}
- "ombra morbida verso destra" -> {"ombra_morbidezza": 0.8, "ombra_direzione_gradi": 0}
- "ombra leggera" -> {"ombra_opacita": 0.25}
- "sposta il mosaico di 3 cm a destra" -> {"offset_x_cm": 3}
- "ruota di 5 gradi in senso antiorario" -> {"rotazione_gradi": -5}
- "piu' luminoso e piu' caldo" -> {"luminosita": 0.15, "temperatura": 0.15}
- "mosaico piu' spesso" -> {"spessore_mm": 8}
Se le istruzioni non riguardano nessun parametro, restituisci un oggetto vuoto."""

LIGHT_PROMPT = """Osserva la foto di sfondo e stima le ombre proiettate dagli oggetti gia' presenti (attrezzi, utensili, ecc.).
Restituisci: ombra_direzione_gradi (0..360; 0 = destra, 90 = basso, 180 = sinistra, 270 = alto: verso in cui cadono le ombre),
ombra_morbidezza (0 = netta, 1 = molto morbida), ombra_opacita (0 = invisibile, 1 = nera)."""

_LIGHT_KEYS = ("ombra_direzione_gradi", "ombra_morbidezza", "ombra_opacita")


def params_schema(keys=None) -> dict:
    """JSON Schema derivato da ComposeParams.RANGES: tutti i campi opzionali."""
    props = {}
    for name, (lo, hi) in ComposeParams.RANGES.items():
        if keys is not None and name not in keys:
            continue
        props[name] = {"type": "number", "description": f"Intervallo {lo}..{hi}"}
    return {"type": "object", "properties": props, "additionalProperties": False}


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).strip().lower()
    return re.sub(r"\s+", " ", t)


def _cache_file(name: str) -> Path:
    return _settings.cache_dir() / name


def _cache_get(name: str, key: str):
    try:
        return json.loads(_cache_file(name).read_text(encoding="utf-8")).get(key)
    except Exception:
        return None


def _cache_put(name: str, key: str, value: dict) -> None:
    try:
        p = _cache_file(name)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data[key] = value
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _client(api_key: str | None = None):
    import anthropic
    return anthropic.Anthropic(api_key=api_key or _settings.get_api_key(), max_retries=2, timeout=60.0)


def _call_structured(model: str, system: str, content, schema: dict, max_tokens: int = 1024) -> dict:
    """Chiama l'API con output strutturato e ritorna il dict. Solleva ValueError(msg italiano) sui problemi."""
    resp = _client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    )
    if getattr(resp, "stop_reason", None) == "refusal":
        raise ValueError("Claude ha rifiutato la richiesta.")
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    try:
        data = json.loads(text)
    except Exception:
        raise ValueError("Risposta di Claude non valida.")
    if not isinstance(data, dict):
        raise ValueError("Risposta di Claude non valida.")
    return data


def _or_headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **_OR_HEADERS}


def _or_http_message(status: int) -> str:
    if status in (401, 403):
        return "Chiave OpenRouter non valida o non autorizzata."
    if status == 402:
        return "Credito OpenRouter esaurito: ricaricalo sul sito di OpenRouter."
    if status == 429:
        return "Troppe richieste a OpenRouter: riprova tra poco."
    if status in (404, 400):
        return "Il modello scelto non e' disponibile su OpenRouter: controlla il nome nelle Impostazioni."
    return "Errore di OpenRouter."


def _extract_json(text: str):
    """Estrae un oggetto JSON da un testo, anche dentro ```json ... ```."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    a, b = text.find("{"), text.rfind("}")
    if 0 <= a < b:
        try:
            return json.loads(text[a:b + 1])
        except Exception:
            pass
    return None


def _call_openrouter(model: str, system: str, text: str, schema: dict, image_b64: str | None = None,
                     max_tokens: int = 1024) -> dict:
    """Chiama OpenRouter. Solleva ValueError(msg italiano) sui problemi."""
    key = _settings.get_openrouter_key()
    if image_b64:
        user = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}},
                {"type": "text", "text": text}]
    else:
        user = text
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    with_format = dict(body, response_format={"type": "json_schema", "json_schema": {
        "name": "arloc_params", "strict": True, "schema": schema}})
    payload = None
    for attempt, b in enumerate((with_format, body)):
        try:
            r = httpx.post(OPENROUTER_URL + "/chat/completions", headers=_or_headers(key or ""),
                           json=b, timeout=60.0)
        except httpx.TimeoutException:
            raise ValueError("OpenRouter non risponde (tempo scaduto).")
        except httpx.HTTPError:
            raise ValueError("Impossibile contattare OpenRouter (rete).")
        try:
            data = r.json()
        except Exception:
            data = None
        status = r.status_code
        err = isinstance(data, dict) and data.get("error")
        if status < 400 and not err:
            payload = data
            break
        code = status if status >= 400 else (err.get("code") if isinstance(err, dict) else 0)
        code = code if isinstance(code, int) else 0
        # response_format non supportato dal modello/servizio: riprova una volta senza
        if attempt == 0 and code in (400, 404, 422, 500, 502, 503):
            continue
        raise ValueError(_or_http_message(code))
    try:
        msg = payload["choices"][0]["message"]
        content = msg.get("content")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        out = _extract_json(content or "")
    except Exception:
        out = None
    if not isinstance(out, dict):
        raise ValueError("Risposta di OpenRouter non valida.")
    return out


def _call_json(settings, model: str, system: str, text: str, schema: dict, image_b64: str | None = None) -> dict:
    """Chiama il servizio scelto e ritorna il dict JSON. Solleva ValueError(msg italiano)."""
    if settings.provider == "openrouter":
        return _call_openrouter(model, system, text, schema, image_b64)
    if image_b64:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
            {"type": "text", "text": text},
        ]
    else:
        content = text
    return _call_structured(model, system, content, schema)


def _model_for(settings, kind: str) -> str:
    if settings.provider == "openrouter":
        return getattr(settings, "openrouter_model_" + kind)
    return getattr(settings, "model_" + kind)


def _key_for(settings):
    return _settings.get_openrouter_key() if settings.provider == "openrouter" else _settings.get_api_key()


def _missing_key_msg(settings) -> str:
    who = "OpenRouter" if settings.provider == "openrouter" else "Claude"
    return f"Chiave API di {who} mancante"


def _error_message(e: Exception) -> str:
    if isinstance(e, ValueError):
        return f"{e} Uso i parametri attuali."
    name = type(e).__name__
    if "Authentication" in name or "PermissionDenied" in name:
        return "Chiave API non valida o non autorizzata: uso i parametri attuali."
    if "Connection" in name or "Timeout" in name:
        return "Impossibile contattare Claude (rete): uso i parametri attuali."
    if "RateLimit" in name:
        return "Troppe richieste a Claude: uso i parametri attuali."
    return "Errore nella chiamata a Claude: uso i parametri attuali."


def _clean(data: dict, keys) -> dict:
    out = {}
    for k in keys:
        v = data.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = float(v)
    return out


def parse_instructions(text, current: ComposeParams, settings=None):
    try:
        if not text or not str(text).strip():
            return current, None
        settings = settings or _settings.load_settings()
        key = hashlib.sha256(
            (_normalize(str(text)) + "|" + SCHEMA_VERSION + "|" + settings.provider + "|"
             + _model_for(settings, "instructions")).encode()
        ).hexdigest()
        changes = _cache_get("instructions.json", key)
        if changes is None:
            if not _key_for(settings):
                return current, _missing_key_msg(settings) + ": istruzioni ignorate (impostala nelle Impostazioni)."
            data = _call_json(settings, _model_for(settings, "instructions"), SYSTEM_PROMPT,
                              str(text), params_schema())
            changes = _clean(data, ComposeParams.RANGES)
            _cache_put("instructions.json", key, changes)
        return current.updated(**changes), None
    except Exception as e:  # mai eccezioni verso il chiamante
        return current, _error_message(e)


def _light_image_b64(bg) -> tuple[str, str]:
    """Ritorna (base64 JPEG ridotto a 1024px, hash dell'immagine originale ridotta)."""
    import cv2
    import numpy as np
    if isinstance(bg, (str, Path)):
        from .imageio import load_image
        img = load_image(Path(bg))
    else:
        img = bg
    if img.ndim == 3 and img.shape[2] == 4:
        img = img[:, :, :3]
    h, w = img.shape[:2]
    s = 1024 / max(h, w)
    if s < 1:
        img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", np.ascontiguousarray(img), [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("Impossibile preparare l'immagine.")
    raw = buf.tobytes()
    return base64.standard_b64encode(raw).decode("ascii"), hashlib.sha256(raw).hexdigest()


def suggest_light(bg_img_or_path, settings=None):
    try:
        settings = settings or _settings.load_settings()
        b64, h = _light_image_b64(bg_img_or_path)
        key = hashlib.sha256((h + "|" + SCHEMA_VERSION + "|" + settings.provider + "|"
                                  + _model_for(settings, "light")).encode()).hexdigest()
        res = _cache_get("light.json", key)
        if res is None:
            if not _key_for(settings):
                return None, _missing_key_msg(settings) + ": impostala nelle Impostazioni."
            data = _call_json(settings, _model_for(settings, "light"),
                              "Sei un esperto di illuminazione fotografica.", LIGHT_PROMPT,
                              params_schema(_LIGHT_KEYS), image_b64=b64)
            res = _clean(data, _LIGHT_KEYS)
            if not res:
                return None, "Claude non ha saputo stimare la luce."
            _cache_put("light.json", key, res)
        p = ComposeParams().updated(**res)
        return {k: getattr(p, k) for k in res}, None
    except Exception as e:
        msg = re.sub("[Uu]so i parametri attuali", "nessun suggerimento", _error_message(e))
        return None, msg


def _verify_openrouter(key: str) -> tuple[bool, str]:
    try:
        r = httpx.get(OPENROUTER_URL + "/key", headers=_or_headers(key), timeout=30.0)
    except httpx.TimeoutException:
        return False, "OpenRouter non risponde (tempo scaduto)."
    except httpx.HTTPError:
        return False, "Impossibile contattare OpenRouter: controlla la connessione."
    if r.status_code < 400:
        return True, "Chiave valida."
    if r.status_code in (401, 403):
        return False, "Chiave non valida."
    if r.status_code == 402:
        return True, "Chiave valida, ma il credito e' esaurito."
    if r.status_code == 429:
        return True, "Chiave valida (limite di richieste raggiunto)."
    return False, "Verifica non riuscita."


def verify_api_key(key: str, provider: str | None = None) -> tuple[bool, str]:
    try:
        if not key or not key.strip():
            return False, "Chiave vuota."
        settings = _settings.load_settings()
        if (provider or settings.provider) == "openrouter":
            return _verify_openrouter(key.strip())
        import anthropic
        client = anthropic.Anthropic(api_key=key.strip(), max_retries=1, timeout=30.0)
        client.messages.create(model=settings.model_instructions, max_tokens=8,
                               messages=[{"role": "user", "content": "ok"}])
        return True, "Chiave valida."
    except Exception as e:
        name = type(e).__name__
        if "Authentication" in name or "PermissionDenied" in name:
            return False, "Chiave non valida."
        if "Connection" in name or "Timeout" in name:
            return False, "Impossibile contattare Anthropic: controlla la connessione."
        if "RateLimit" in name:
            return True, "Chiave valida (limite di richieste raggiunto)."
        return False, "Verifica non riuscita."
