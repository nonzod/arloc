"""Servizi AI (Anthropic, OpenRouter) dietro un'unica interfaccia: chiamata JSON, verifica chiave e modelli.

Ogni servizio è una classe con gli stessi metodi (`provider_for(settings)` sceglie quella giusta).
Gli errori diventano `AIError(kind)`; `message()` li traduce in italiano in un solo punto.
Client HTTP riusati tra le chiamate (connessioni tenute aperte).
"""
from __future__ import annotations

import base64
import difflib
import json
import re
from functools import lru_cache

try:  # dipendenza dell'SDK anthropic (il pacchetto si chiama httpx2 nelle versioni recenti)
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from . import settings as _settings

OPENROUTER_URL = "https://openrouter.ai/api/v1"
_OR_HEADERS = {"HTTP-Referer": "https://github.com/tourtools/arloc", "X-Title": "Arloc"}
_http = httpx.Client(timeout=60.0)   # condiviso (thread-safe): keep-alive verso OpenRouter

ROLES = ("instructions", "light", "retouch")
ROLE_NAMES = {"instructions": "Modello per le istruzioni", "light": "Modello per la luce",
              "retouch": "Modello per il ritocco"}
_STRUCTURED = {"structured_outputs", "response_format"}


# ---------------------------------------------------------------- errori
class AIError(Exception):
    """kind: auth | credit | rate | timeout | network | not_found | no_image | bad_request |
    refusal | bad_response | no_output_image | other."""

    def __init__(self, kind: str, model: str = ""):
        super().__init__(kind)
        self.kind, self.model = kind, model


_BASE = {
    "auth": "Chiave di {svc} non valida o non autorizzata.",
    "credit": "Credito {svc} esaurito: ricaricalo sul sito di {svc}.",
    "rate": "Troppe richieste a {svc}: riprova tra poco.",
    "timeout": "{svc} non risponde (tempo scaduto).",
    "network": "Impossibile contattare {svc} (rete).",
    "not_found": "Il modello {m} non esiste su {platform}: correggi il nome nelle Impostazioni "
                 "(Modelli avanzati, pulsante Verifica).",
    "no_image": "Il modello {m} non accetta le immagini: scegline un altro nelle Impostazioni "
                "(Modelli avanzati, pulsante Verifica).",
    "bad_request": "Il modello {m} non accetta questa richiesta: controllalo nelle Impostazioni "
                   "(Modelli avanzati, pulsante Verifica).",
    "refusal": "{svc} ha rifiutato la richiesta.",
    "bad_response": "Risposta di {svc} non valida.",
    "no_output_image": "Il modello {m} non ha restituito nessuna immagine.",
    "no_key": "Chiave API di {svc} mancante (impostala nelle Impostazioni).",
    "other": "Errore di {svc}.",
}
_SUFFIX = {"instructions": " Uso i parametri attuali.", "light": " Nessun suggerimento.", "retouch": ""}


def message(err: Exception, provider: "Provider", context: str) -> str:
    """Messaggio in italiano per l'utente. context: instructions | light | retouch."""
    e = err if isinstance(err, AIError) else provider.to_error(err)
    m = f"«{e.model}»" if e.model else "scelto"
    text = _BASE.get(e.kind, _BASE["other"]).format(svc=provider.label, platform=provider.platform, m=m)
    if context == "retouch":
        if not text.startswith(provider.label):
            text = text[0].lower() + text[1:]
        return "Ritocco AI non eseguito: " + text
    return text + _SUFFIX[context]


def _http_error(e: Exception) -> AIError | None:
    if isinstance(e, httpx.TimeoutException):
        return AIError("timeout")
    if isinstance(e, httpx.HTTPError):
        return AIError("network")
    return None


def _extract_json(text: str):
    """Oggetto JSON da un testo, anche dentro ```json ... ``` o circondato da altro testo."""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    a, b = text.find("{"), text.rfind("}")
    for cand in (text, m.group(1).strip() if m else None, text[a:b + 1] if 0 <= a < b else None):
        if cand:
            try:
                return json.loads(cand)
            except Exception:
                pass
    return None


# ---------------------------------------------------------------- Anthropic
@lru_cache(maxsize=4)
def _anthropic_client(key: str):
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=2, timeout=60.0)


class AnthropicProvider:
    name, label, platform = "anthropic", "Claude", "Anthropic"
    roles = ("instructions", "light")

    def key(self) -> str | None:
        return _settings.get_api_key()

    def to_error(self, e: Exception, model: str = "") -> AIError:
        if isinstance(e, AIError):
            return e
        try:
            import anthropic
        except ImportError:  # pragma: no cover
            return AIError("other", model)
        if isinstance(e, anthropic.NotFoundError):
            return AIError("not_found", model)
        if isinstance(e, anthropic.BadRequestError):
            return AIError("no_image" if "image" in str(e).lower() else "bad_request", model)
        if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return AIError("auth", model)
        if isinstance(e, anthropic.RateLimitError):
            return AIError("rate", model)
        if isinstance(e, anthropic.APITimeoutError):
            return AIError("timeout", model)
        if isinstance(e, anthropic.APIConnectionError):
            return AIError("network", model)
        return AIError("other", model)

    def call_json(self, model: str, system: str, text: str, schema: dict, image_jpeg: bytes | None = None,
                  max_tokens: int = 1024) -> dict:
        content = text
        if image_jpeg:
            content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.standard_b64encode(image_jpeg).decode("ascii")}},
                       {"type": "text", "text": text}]
        try:
            resp = _anthropic_client(self.key() or "").messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as e:
            raise self.to_error(e, model) from e
        if getattr(resp, "stop_reason", None) == "refusal":
            raise AIError("refusal", model)
        data = _extract_json("".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"))
        if not isinstance(data, dict):
            raise AIError("bad_response", model)
        return data

    def verify_key(self, key: str, model: str) -> tuple[bool, str]:
        import anthropic
        try:
            anthropic.Anthropic(api_key=key, max_retries=1, timeout=30.0).messages.create(
                model=model, max_tokens=8, messages=[{"role": "user", "content": "ok"}])
            return True, "Chiave valida."
        except Exception as e:
            kind = self.to_error(e).kind
        if kind == "auth":
            return False, "Chiave non valida."
        if kind in ("network", "timeout"):
            return False, "Impossibile contattare Anthropic: controlla la connessione."
        if kind == "rate":
            return True, "Chiave valida (limite di richieste raggiunto)."
        return False, "Verifica non riuscita."

    def check_models(self, settings, key: str | None) -> list[tuple[str, str, str]]:
        out = []
        client = None
        for role in self.roles:
            label, model = ROLE_NAMES[role], settings.model(role)
            if not key:
                out.append((role, "warn", f"{label}: non posso controllare «{model}» senza la chiave."))
                continue
            try:
                import anthropic
                client = client or anthropic.Anthropic(api_key=key, max_retries=1, timeout=30.0)
                client.models.retrieve(model)
                out.append((role, "ok", f"{label}: «{model}» va bene."))
                continue
            except Exception as e:
                kind = self.to_error(e).kind
            if kind == "not_found":
                sug = []
                try:
                    sug = difflib.get_close_matches(model, [m.id for m in client.models.list(limit=100)], n=3, cutoff=0.4)
                except Exception:
                    pass
                tail = (" Modelli simili: " + ", ".join(f"«{s}»" for s in sug) + ".") if sug else ""
                out.append((role, "error", f"{label}: «{model}» non esiste su Anthropic.{tail}"))
            elif kind == "auth":
                out.append((role, "error", f"{label}: la chiave non è valida, non posso controllare «{model}»."))
            else:
                out.append((role, "warn", f"{label}: non sono riuscito a controllare «{model}» "
                                          "(rete o servizio non raggiungibile)."))
        return out


# ---------------------------------------------------------------- OpenRouter
_MODELS_CACHE: dict | None = None   # id -> voce di /models, per la durata della sessione


def openrouter_models(refresh: bool = False) -> dict | None:
    """Elenco pubblico dei modelli OpenRouter (id -> voce), in cache per la sessione. None se non raggiungibile."""
    global _MODELS_CACHE
    if _MODELS_CACHE is not None and not refresh:
        return _MODELS_CACHE
    try:
        r = _http.get(OPENROUTER_URL + "/models", headers=_OR_HEADERS, timeout=30.0)
        if r.status_code >= 400:
            return None
        models = {m["id"]: m for m in r.json().get("data") or [] if isinstance(m, dict) and m.get("id")}
        if models:
            _MODELS_CACHE = models
        return models or None
    except Exception:
        return None


def _modalities(entry: dict) -> tuple[set, set, set]:
    a = entry.get("architecture") or {}
    return (set(a.get("input_modalities") or []), set(a.get("output_modalities") or []),
            set(entry.get("supported_parameters") or []))


def _fits_role(entry: dict, role: str) -> bool:
    i, o, _ = _modalities(entry)
    if role == "instructions":
        return "text" in o
    if role == "light":
        return "text" in o and "image" in i
    return "image" in o and "image" in i


def _suggest(model: str, models: dict, role: str, n: int = 3) -> list[str]:
    ids = [k for k, v in models.items() if _fits_role(v, role) and not k.startswith("openrouter/") and ":" not in k]
    want = model.lower()
    ratio = {k: difflib.SequenceMatcher(None, want, k.lower()).ratio() for k in ids}
    scored = sorted(ids, key=lambda k: -ratio[k])
    best = [k for k in scored if ratio[k] >= 0.35][:n]
    vendor = want.split("/")[0]
    if len(best) < n:   # stesso produttore, nomi più vicini
        best += [k for k in scored if k.split("/")[0] == vendor and k not in best][: n - len(best)]
    return best


def _check_or_model(models: dict, role: str, model: str) -> tuple[str, str]:
    label = ROLE_NAMES[role]
    entry = models.get(model)
    if entry is None:
        sug = _suggest(model, models, role)
        tail = (" Modelli simili adatti: " + ", ".join(f"«{s}»" for s in sug) + ".") if sug else ""
        return "error", f"{label}: «{model}» non esiste su OpenRouter.{tail}"
    i, o, sup = _modalities(entry)
    if role == "retouch":
        if "image" not in o:
            return "error", f"{label}: «{model}» non produce immagini, ma qui serve un modello che le restituisce."
        if "image" not in i:
            return "error", f"{label}: «{model}» non accetta immagini in ingresso, ma qui serve per ritoccare la foto."
        return "ok", f"{label}: «{model}» va bene."
    if "text" not in o:
        return "error", f"{label}: «{model}» genera immagini, ma qui serve un modello che risponde con testo."
    if role == "light" and "image" not in i:
        return "error", f"{label}: «{model}» non legge le immagini, ma per la luce serve un modello che le guarda."
    if not (_STRUCTURED & sup):
        return "warn", f"{label}: «{model}» non supporta le risposte strutturate: funzionerà, ma meno affidabile."
    return "ok", f"{label}: «{model}» va bene."


class OpenRouterProvider:
    name, label, platform = "openrouter", "OpenRouter", "OpenRouter"
    roles = ROLES

    def key(self) -> str | None:
        return _settings.get_openrouter_key()

    def to_error(self, e: Exception, model: str = "") -> AIError:
        if isinstance(e, AIError):
            return e
        return _http_error(e) or AIError("other", model)

    @staticmethod
    def _status_error(status: int, detail: str, model: str) -> AIError:
        d = detail.lower()
        if status in (401, 403):
            return AIError("auth", model)
        if status == 402:
            return AIError("credit", model)
        if status == 429:
            return AIError("rate", model)
        if status in (400, 404) and "image" in d and ("support" in d or "input" in d or "modalit" in d):
            return AIError("no_image", model)
        if status == 404 or any(s in d for s in ("no endpoints", "not a valid model", "not found")):
            return AIError("not_found", model)
        if status == 400:
            return AIError("bad_request", model)
        return AIError("other", model)

    def chat(self, body: dict, timeout: float = 60.0) -> dict:
        """POST /chat/completions. Ritorna il JSON della risposta; solleva AIError."""
        model = body.get("model", "")
        headers = {"Authorization": f"Bearer {self.key() or ''}", "Content-Type": "application/json", **_OR_HEADERS}
        try:
            r = _http.post(OPENROUTER_URL + "/chat/completions", headers=headers, json=body, timeout=timeout)
        except Exception as e:
            raise self.to_error(e, model) from e
        try:
            data = r.json()
        except Exception:
            data = None
        err = data.get("error") if isinstance(data, dict) else None
        if r.status_code < 400 and not err:
            if not isinstance(data, dict):
                raise AIError("bad_response", model)
            return data
        code = r.status_code
        if code < 400 and isinstance(err, dict) and isinstance(err.get("code"), int):
            code = err["code"]
        detail = str(err.get("message") or "") if isinstance(err, dict) else str(err or "")
        e = self._status_error(code, detail, model)
        e.status = code
        raise e

    def call_json(self, model: str, system: str, text: str, schema: dict, image_jpeg: bytes | None = None,
                  max_tokens: int = 1024) -> dict:
        user = text
        if image_jpeg:
            url = "data:image/jpeg;base64," + base64.standard_b64encode(image_jpeg).decode("ascii")
            user = [{"type": "image_url", "image_url": {"url": url}}, {"type": "text", "text": text}]
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        with_format = dict(body, response_format={"type": "json_schema", "json_schema": {
            "name": "arloc_params", "strict": True, "schema": schema}})
        # se l'elenco dei modelli (già in cache) dice che lo schema non è supportato, niente tentativo a vuoto
        entry = (_MODELS_CACHE or {}).get(model)
        attempts = [body] if entry is not None and not (_STRUCTURED & _modalities(entry)[2]) else [with_format, body]
        for n, b in enumerate(attempts):
            try:
                payload = self.chat(b)
                break
            except AIError as e:
                # response_format non supportato dal modello/servizio: si riprova una volta senza
                if n + 1 < len(attempts) and getattr(e, "status", 0) in (400, 404, 422, 500, 502, 503):
                    continue
                raise
        try:
            content = payload["choices"][0]["message"].get("content")
            if isinstance(content, list):
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            out = _extract_json(content or "")
        except Exception:
            out = None
        if not isinstance(out, dict):
            raise AIError("bad_response", model)
        return out

    def verify_key(self, key: str, model: str = "") -> tuple[bool, str]:
        try:
            r = _http.get(OPENROUTER_URL + "/key", headers={"Authorization": f"Bearer {key}", **_OR_HEADERS},
                          timeout=30.0)
        except Exception as e:
            kind = self.to_error(e).kind
            return False, ("OpenRouter non risponde (tempo scaduto)." if kind == "timeout"
                           else "Impossibile contattare OpenRouter: controlla la connessione.")
        if r.status_code < 400:
            return True, "Chiave valida."
        return {401: (False, "Chiave non valida."), 403: (False, "Chiave non valida."),
                402: (True, "Chiave valida, ma il credito è esaurito."),
                429: (True, "Chiave valida (limite di richieste raggiunto).")}.get(
            r.status_code, (False, "Verifica non riuscita."))

    def check_models(self, settings, key: str | None = None) -> list[tuple[str, str, str]]:
        models = openrouter_models()
        out = []
        for role in self.roles:
            m = settings.model(role)
            if models is None:
                out.append((role, "warn", f"{ROLE_NAMES[role]}: non riesco a controllare «{m}» "
                                          "(elenco dei modelli di OpenRouter non raggiungibile)."))
            else:
                out.append((role, *_check_or_model(models, role, m)))
        return out


_PROVIDERS = {"anthropic": AnthropicProvider(), "openrouter": OpenRouterProvider()}
Provider = AnthropicProvider | OpenRouterProvider


def provider_for(settings_or_name) -> Provider:
    name = settings_or_name if isinstance(settings_or_name, str) else getattr(settings_or_name, "provider", "")
    return _PROVIDERS.get(name, _PROVIDERS["anthropic"])
