"""Piccola cache su disco: un file per chiave in `cache_dir()/<nome>/`, si tengono solo i più recenti.

Serve a non ripetere le chiamate ai servizi AI (istruzioni, luce, ritocco). È solo cache:
qualsiasi errore di lettura o scrittura viene ignorato.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import settings as _settings


def make_key(*parts) -> str:
    """Hash stabile delle parti (str o bytes)."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode())
        h.update(b"|")
    return h.hexdigest()


class DiskCache:
    def __init__(self, name: str, max_items: int = 500, suffix: str = ".json"):
        self.name, self.max_items, self.suffix = name, max_items, suffix

    def _dir(self) -> Path:
        return _settings.cache_dir() / self.name

    def get_bytes(self, key: str) -> bytes | None:
        try:
            return (self._dir() / (key + self.suffix)).read_bytes()
        except Exception:
            return None

    def put_bytes(self, key: str, data: bytes) -> None:
        try:
            d = self._dir()
            d.mkdir(parents=True, exist_ok=True)
            (d / (key + self.suffix)).write_bytes(data)
            files = sorted(d.glob("*" + self.suffix), key=lambda p: p.stat().st_mtime)
            for p in files[:-self.max_items]:
                p.unlink(missing_ok=True)
        except Exception:
            pass

    def get(self, key: str):
        raw = self.get_bytes(key)
        try:
            return json.loads(raw) if raw is not None else None
        except Exception:
            return None

    def put(self, key: str, value) -> None:
        self.put_bytes(key, json.dumps(value, ensure_ascii=False).encode())
