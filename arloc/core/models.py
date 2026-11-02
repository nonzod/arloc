"""Strutture dati condivise da core, batch, CLI e UI.

QUESTO FILE È IL CONTRATTO tra i moduli: cambiarlo solo in modo retrocompatibile.
Le immagini in memoria sono numpy array OpenCV (BGR uint8, oppure BGRA se c'è trasparenza).
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
from pathlib import Path

import numpy as np

Point = tuple[float, float]


@dataclass
class Quad:
    """Quadrilatero in pixel, ordine: alto-sx, alto-dx, basso-dx, basso-sx."""
    points: list[Point]

    def as_array(self) -> np.ndarray:
        return np.asarray(self.points, dtype=np.float32).reshape(4, 2)

    @classmethod
    def from_array(cls, arr) -> "Quad":
        a = np.asarray(arr, dtype=np.float32).reshape(4, 2)
        return cls([(float(x), float(y)) for x, y in a])


@dataclass
class ComposeParams:
    """Regolazioni della composizione (vedi IMPLEMENTAZIONE.md §6.1)."""
    rotazione_gradi: float = 0.0
    offset_x_cm: float = 0.0
    offset_y_cm: float = 0.0
    ombra_direzione_gradi: float = 135.0  # 0 = destra, 90 = basso (coordinate immagine)
    ombra_distanza_cm: float = 0.6
    ombra_morbidezza: float = 0.5
    ombra_opacita: float = 0.45
    spessore_mm: float = 4.0
    luminosita: float = 0.0
    temperatura: float = 0.0
    armonizzazione: float = 0.3
    grana: float = 0.0
    riempimento: float = 0.92  # solo misure automatiche: quanto dello spazio dell'area occupa il mosaico

    # (min, max) per ogni campo: usato per clamp, cursori UI e JSON schema
    RANGES = {
        "rotazione_gradi": (-180.0, 180.0),
        "offset_x_cm": (-100.0, 100.0),
        "offset_y_cm": (-100.0, 100.0),
        "ombra_direzione_gradi": (0.0, 360.0),
        "ombra_distanza_cm": (0.0, 5.0),
        "ombra_morbidezza": (0.0, 1.0),
        "ombra_opacita": (0.0, 1.0),
        "spessore_mm": (0.0, 15.0),
        "luminosita": (-0.5, 0.5),
        "temperatura": (-0.5, 0.5),
        "armonizzazione": (0.0, 1.0),
        "grana": (0.0, 1.0),
        "riempimento": (0.5, 1.0),
    }

    def clamped(self) -> "ComposeParams":
        vals = {}
        for f in fields(self):
            lo, hi = self.RANGES[f.name]
            vals[f.name] = float(min(hi, max(lo, getattr(self, f.name))))
        return ComposeParams(**vals)

    def updated(self, **changes) -> "ComposeParams":
        """Copia con i soli campi noti aggiornati, poi clamp."""
        d = asdict(self)
        d.update({k: float(v) for k, v in changes.items() if k in d and v is not None})
        return ComposeParams(**d).clamped()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OutputPreset:
    nome: str            # "shopify" | "etsy" | "custom"
    larghezza: int
    altezza: int
    formato: str = "jpg"  # "jpg" | "png" | "webp"
    qualita: int = 90


@dataclass
class Job:
    """Tutto ciò che serve per generare un'immagine."""
    sfondo: Path
    mosaico: Path
    larghezza_sfondo_cm: float = 0.0   # 0 = non indicata (ok solo con misure automatiche)
    larghezza_mosaico_cm: float = 0.0
    altezza_mosaico_cm: float = 0.0
    area: Quad | None = None          # None = cerca il rettangolo verde
    mosaico_quad: Quad | None = None  # None = ritaglio automatico
    istruzioni: str = ""
    params: ComposeParams = field(default_factory=ComposeParams)
    preset: OutputPreset | None = None
    nome_output: str | None = None
    scontorno: str = "auto"                      # "auto" | "rettangolo" | "forma"
    misure: str = "reali"                        # "reali" (cm obbligatori) | "automatiche" (il mosaico riempie l'area, senza cm)
    mosaico_maschera: np.ndarray | None = None   # maschera uint8 0/255 (anche a risoluzione ridotta) dopo i ritocchi; None = automatica
    ritocco_ai: bool = False                     # ritocco AI finale (sperimentale, solo OpenRouter), applicato dal chiamante


@dataclass
class ComposeResult:
    image: np.ndarray                 # BGR uint8, dimensioni dello sfondo (o ridotte in anteprima)
    center: Point                     # centro del mosaico nell'immagine risultante, in px
    mosaic_quad: Quad                 # dove è finito il mosaico nell'immagine risultante
    warnings: list[str] = field(default_factory=list)  # messaggi in italiano per l'utente
    mosaic_mask: np.ndarray | None = None  # uint8 0/255, dimensioni di `image`: dove sta il mosaico nell'immagine finale


class ArlocError(Exception):
    """Errore da mostrare all'utente così com'è (messaggio in italiano semplice)."""
