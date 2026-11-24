"""Istruzioni in testo libero -> ComposeParams, suggerimento della luce, verifica di chiave e modelli.

Il servizio (Anthropic o OpenRouter) lo sceglie `ai.provider_for(settings)`; le risposte sono in cache
su disco (`DiskCache`). Mai eccezioni verso il chiamante: in caso di problemi si ritorna un avviso.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from . import ai
from . import settings as _settings
from .ai import OPENROUTER_URL, ROLE_NAMES, openrouter_models  # noqa: F401  (riesportati)
from .cache import DiskCache, make_key
from .imageio import encode_jpeg
from .models import ComposeParams

SCHEMA_VERSION = "1"
LIGHT_SEND_MAX = 1024   # lato lungo dell'immagine inviata per la luce
_cache_instr = DiskCache("istruzioni")
_cache_light = DiskCache("luce")

SYSTEM_PROMPT = """Sei l'assistente di Arloc, un programma che compone la foto di un mosaico su uno sfondo (un tavolo, un piano di lavoro).
Ricevi istruzioni in italiano e le traduci in parametri numerici. Restituisci SOLO i parametri citati o chiaramente implicati; ometti tutti gli altri.

Parametri (intervalli):
- rotazione_gradi (-180..180): rotazione extra del mosaico; positivo = senso orario.
- offset_x_cm, offset_y_cm (-100..100): spostamento dal centro dell'area; x positivo = destra, y positivo = basso.
- ombra_direzione_gradi (0..360): verso in cui cade l'ombra. 0 = destra, 90 = basso, 180 = sinistra, 270 = alto.
- riempimento (0.5..1): solo misure automatiche, quanto dello spazio dell'area occupa il mosaico (default 0.92); "più grande" = valore più alto.
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


def _clean(data: dict, keys) -> dict:
    return {k: float(v) for k in keys if isinstance(v := data.get(k), (int, float)) and not isinstance(v, bool)}


def _missing_key(prov) -> str:
    return f"Chiave API di {prov.label} mancante"


def parse_instructions(text, current: ComposeParams, settings=None):
    prov = None
    try:
        if not text or not str(text).strip():
            return current, None
        settings = settings or _settings.load_settings()
        prov, model = ai.provider_for(settings), settings.model("instructions")
        key = make_key(_normalize(str(text)), SCHEMA_VERSION, prov.name, model)
        changes = _cache_instr.get(key)
        if changes is None:
            if not prov.key():
                return current, _missing_key(prov) + ": istruzioni ignorate (impostala nelle Impostazioni)."
            data = prov.call_json(model, SYSTEM_PROMPT, str(text), params_schema())
            changes = _clean(data, ComposeParams.RANGES)
            _cache_instr.put(key, changes)
        return current.updated(**changes), None
    except Exception as e:  # mai eccezioni verso il chiamante
        return current, ai.message(e, prov or ai.provider_for(""), "instructions")


def suggest_light(bg_img_or_path, settings=None):
    prov = None
    try:
        settings = settings or _settings.load_settings()
        prov, model = ai.provider_for(settings), settings.model("light")
        img = bg_img_or_path
        if isinstance(img, (str, Path)):
            from .imageio import load_image
            img = load_image(Path(img))
        jpeg = encode_jpeg(img, LIGHT_SEND_MAX, 85)
        key = make_key(jpeg, SCHEMA_VERSION, prov.name, model)
        res = _cache_light.get(key)
        if res is None:
            if not prov.key():
                return None, _missing_key(prov) + ": impostala nelle Impostazioni."
            data = prov.call_json(model, "Sei un esperto di illuminazione fotografica.", LIGHT_PROMPT,
                                  params_schema(_LIGHT_KEYS), image_jpeg=jpeg)
            res = _clean(data, _LIGHT_KEYS)
            if not res:
                return None, f"{prov.label} non ha saputo stimare la luce."
            _cache_light.put(key, res)
        p = ComposeParams().updated(**res)
        return {k: getattr(p, k) for k in res}, None
    except Exception as e:
        return None, ai.message(e, prov or ai.provider_for(""), "light")


def verify_api_key(key: str, provider: str | None = None) -> tuple[bool, str]:
    try:
        if not key or not key.strip():
            return False, "Chiave vuota."
        settings = _settings.load_settings()
        prov = ai.provider_for(provider or settings.provider)
        return prov.verify_key(key.strip(), settings.model_instructions)
    except Exception:
        return False, "Verifica non riuscita."


def check_models(settings=None, key: str | None = None) -> list[tuple[str, str, str]]:
    """Controlla i modelli configurati per il servizio scelto.

    Ritorna [(ruolo, livello, messaggio)], livello = "ok" | "warn" | "error"; ruolo = instructions | light | retouch.
    Mai eccezioni. `key`: chiave da usare; default quella salvata.
    """
    try:
        settings = settings or _settings.load_settings()
        prov = ai.provider_for(settings)
        return prov.check_models(settings, key or prov.key())
    except Exception:  # noqa: BLE001
        return [("", "warn", "Non sono riuscito a controllare i modelli.")]
