"""Impostazioni utente, chiave API e cartella cache."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path

import platformdirs

from .models import OutputPreset

APP = "arloc"
_SERVICE = "arloc"
PROVIDERS = ("anthropic", "openrouter")
# servizio -> (voce nel portachiavi, variabile d'ambiente di riserva)
_KEYS = {"anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
         "openrouter": ("openrouter_api_key", "OPENROUTER_API_KEY")}


@dataclass
class Settings:
    output_dir: str = ""
    custom_preset: OutputPreset = field(
        default_factory=lambda: OutputPreset("custom", 1600, 1200, "jpg", 90))
    default_preset: str = "shopify"
    model_instructions: str = "claude-haiku-5-5"
    model_light: str = "claude-sonnet-5-5"
    provider: str = "anthropic"  # "anthropic" | "openrouter"
    openrouter_model_instructions: str = "anthropic/claude-haiku-5.5"
    openrouter_model_light: str = "anthropic/claude-sonnet-5.5"
    # ritocco AI finale (sperimentale, solo OpenRouter): modello che riceve e restituisce immagini
    openrouter_model_retouch: str = "google/gemini-3.1-flash-image"
    last_dirs: dict = field(default_factory=dict)

    def model(self, role: str) -> str:
        """Modello configurato per il ruolo (instructions | light | retouch) sul servizio scelto; "" se non previsto."""
        prefix = "openrouter_model_" if self.provider == "openrouter" else "model_"
        return getattr(self, prefix + role, "") or ""


def _config_path() -> Path:
    return Path(platformdirs.user_config_dir(APP)) / "settings.json"


def load_settings() -> Settings:
    s = Settings()
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except Exception:
        return s
    if not isinstance(data, dict):
        return s
    for f in fields(Settings):   # stringhe non vuote e dizionari: si prendono così come sono
        v = data.get(f.name)
        if (isinstance(v, str) and v and isinstance(getattr(s, f.name), str)) or \
                (isinstance(v, dict) and isinstance(getattr(s, f.name), dict)):
            setattr(s, f.name, v)
    if s.provider not in PROVIDERS:
        s.provider = "anthropic"
    cp = data.get("custom_preset")
    if isinstance(cp, dict):
        try:
            s.custom_preset = OutputPreset(
                str(cp.get("nome", "custom")), int(cp["larghezza"]), int(cp["altezza"]),
                str(cp.get("formato", "jpg")), int(cp.get("qualita", 90)))
        except Exception:
            pass
    return s


def save_settings(s: Settings) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")


def get_key(provider: str) -> str | None:
    """Chiave del servizio: portachiavi, altrimenti variabile d'ambiente."""
    user, env = _KEYS[provider]
    try:
        import keyring
        key = keyring.get_password(_SERVICE, user)
        if key:
            return key
    except Exception:
        pass
    return os.environ.get(env) or None


def set_key(provider: str, key: str | None) -> None:
    """Salva (o cancella con None) nel portachiavi; senza portachiavi non fa nulla."""
    user, _ = _KEYS[provider]
    try:
        import keyring
        if key:
            keyring.set_password(_SERVICE, user, key)
        else:
            try:
                keyring.delete_password(_SERVICE, user)
            except Exception:
                pass
    except Exception:
        pass


def get_api_key() -> str | None:
    return get_key("anthropic")


def set_api_key(key: str | None) -> None:
    set_key("anthropic", key)


def get_openrouter_key() -> str | None:
    return get_key("openrouter")


def set_openrouter_key(key: str | None) -> None:
    set_key("openrouter", key)


def cache_dir() -> Path:
    p = Path(platformdirs.user_cache_dir(APP))
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p
