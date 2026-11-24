"""La sequenza completa usata da GUI, batch e CLI: istruzioni (AI) -> composizione -> ritocco AI.

Le fasi AI non sollevano mai eccezioni: in caso di problemi tornano un avviso e si va avanti.
"""
from __future__ import annotations

import dataclasses

from . import settings as _settings
from .compose import compose
from .harmonize import harmonize
from .instructions import parse_instructions
from .models import ComposeResult, Job


def apply_instructions(job: Job, settings=None, use_claude: bool = True) -> tuple[Job, str | None]:
    """Copia del job con i parametri aggiornati dalle istruzioni in testo libero."""
    if not use_claude or not (job.istruzioni or "").strip():
        return job, None
    params, warn = parse_instructions(job.istruzioni, job.params, settings)
    return dataclasses.replace(job, params=params), warn


def retouch(result: ComposeResult, settings=None) -> tuple[ComposeResult, str | None]:
    """Ritocco AI finale: nuovo risultato con l'immagine ritoccata (o l'originale e un avviso)."""
    img, warn = harmonize(result, result.mosaic_mask, settings)
    return dataclasses.replace(result, image=img, warnings=list(result.warnings)), warn


def render(job: Job, settings=None, *, use_claude: bool = True, retouch_ai: bool | None = None,
           preview_max: int | None = None) -> tuple[Job, ComposeResult, list[str]]:
    """Istruzioni + composizione + (se richiesto) ritocco. Ritorna (job usato, risultato, avvisi AI).

    `retouch_ai=None` usa `job.ritocco_ai`. Il ritocco non si applica all'anteprima ridotta.
    Gli avvisi della composizione restano in `result.warnings`.
    """
    settings = settings or _settings.load_settings()
    warns: list[str] = []
    job, warn = apply_instructions(job, settings, use_claude)
    if warn:
        warns.append(warn)
    result = compose(job, preview_max=preview_max)
    if job.ritocco_ai if retouch_ai is None else retouch_ai:
        if preview_max:
            warns.append("Il ritocco AI non si applica all'anteprima ridotta.")
        else:
            result, warn = retouch(result, settings)
            if warn:
                warns.append(warn)
    return job, result, warns
