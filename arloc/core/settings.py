"""Impostazioni utente, chiave API e cartella cache."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

import platformdirs

from .models import OutputPreset

APP = "arloc"
_SERVICE = "arloc"
_USER = "anthropic_api_key"
_USER_OR = "openrouter_api_key"


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
    last_dirs: dict = field(default_factory=dict)


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
    for k in ("output_dir", "default_preset", "model_instructions", "model_light",
              "provider", "openrouter_model_instructions", "openrouter_model_light"):
        if isinstance(data.get(k), str) and data[k]:
            setattr(s, k, data[k])
    if s.provider not in ("anthropic", "openrouter"):
        s.provider = "anthropic"
    if isinstance(data.get("last_dirs"), dict):
        s.last_dirs = data["last_dirs"]
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


def _get_key(user: str, env: str) -> str | None:
    try:
        import keyring
        key = keyring.get_password(_SERVICE, user)
        if key:
            return key
    except Exception:
        pass
    return os.environ.get(env) or None


def _set_key(user: str, key: str | None) -> None:
    """Salva (o cancella con None) nel portachiavi; senza portachiavi non fa nulla."""
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
    return _get_key(_USER, "ANTHROPIC_API_KEY")


def set_api_key(key: str | None) -> None:
    _set_key(_USER, key)


def get_openrouter_key() -> str | None:
    return _get_key(_USER_OR, "OPENROUTER_API_KEY")


def set_openrouter_key(key: str | None) -> None:
    _set_key(_USER_OR, key)


def cache_dir() -> Path:
    p = Path(platformdirs.user_cache_dir(APP))
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p
