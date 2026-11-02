"""Riga di comando: `python -m arloc compose ...` (e `batch`, se disponibile)."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import fields
from pathlib import Path

from .core.compose import compose
from .core.geometry import parse_area
from .core.imageio import FORMATI, save_image
from .core.models import ArlocError, ComposeParams, Job
from .core.presets import export, parse_preset

# nome opzione -> campo di ComposeParams
PARAM_FLAGS = {
    "--rotazione": "rotazione_gradi",
    "--offset-x": "offset_x_cm",
    "--offset-y": "offset_y_cm",
    "--ombra-direzione": "ombra_direzione_gradi",
    "--ombra-distanza": "ombra_distanza_cm",
    "--ombra-morbidezza": "ombra_morbidezza",
    "--ombra-opacita": "ombra_opacita",
    "--spessore": "spessore_mm",
    "--luminosita": "luminosita",
    "--temperatura": "temperatura",
    "--armonizzazione": "armonizzazione",
    "--grana": "grana",
}


def _parse_size_cm(text: str) -> tuple[float, float]:
    m = re.fullmatch(r"\s*([\d.,]+)\s*[x×]\s*([\d.,]+)\s*", text)
    if not m:
        raise ArlocError('Misure del mosaico non valide: scrivi larghezza e altezza in cm, ad esempio "30x20".')
    return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))


def _add_compose(sub) -> None:
    p = sub.add_parser("compose", help="compone un mosaico su uno sfondo")
    p.add_argument("--sfondo", required=True, help="foto di sfondo")
    p.add_argument("--mosaico", required=True, help="foto del mosaico")
    p.add_argument("--sfondo-cm", required=True, type=float, help="larghezza reale dell'intero sfondo, in cm")
    p.add_argument("--mosaico-cm", required=True, help='misure del mosaico in cm, es. "30x20"')
    p.add_argument("--scontorno", choices=["auto", "rettangolo", "forma"], default="auto",
                   help="scontorno del mosaico (default: auto)")
    p.add_argument("--area", help='4 angoli in pixel "x1,y1;x2,y2;x3,y3;x4,y4" (default: rettangolo verde)')
    p.add_argument("--preset", help='shopify, etsy oppure "custom 1600x1200 png" (default: dimensioni dello sfondo)')
    p.add_argument("--out", required=True, help="file di output (l'estensione dipende dal formato)")
    p.add_argument("--anteprima", type=int, metavar="PX", help="lavora su una copia ridotta (lato lungo in px)")
    p.add_argument("--istruzioni", help="istruzioni in testo libero (richiede la chiave API Claude)")
    for flag, name in PARAM_FLAGS.items():
        p.add_argument(flag, type=float, dest=name, help=f"{name} (default {getattr(ComposeParams(), name)})")
    p.set_defaults(func=_run_compose)


def _run_compose(a: argparse.Namespace) -> int:
    w_cm, h_cm = _parse_size_cm(a.mosaico_cm)
    params = ComposeParams().updated(**{f.name: getattr(a, f.name) for f in fields(ComposeParams)})
    warnings: list[str] = []
    if a.istruzioni:
        try:
            from .core.instructions import parse_instructions
            params, warn = parse_instructions(a.istruzioni, params)
            if warn:
                warnings.append(warn)
        except ImportError:
            warnings.append("Le istruzioni in testo libero non sono ancora disponibili.")
    preset = parse_preset(a.preset) if a.preset else None
    job = Job(sfondo=Path(a.sfondo), mosaico=Path(a.mosaico), larghezza_sfondo_cm=a.sfondo_cm,
              larghezza_mosaico_cm=w_cm, altezza_mosaico_cm=h_cm,
              area=parse_area(a.area) if a.area else None,
              istruzioni=a.istruzioni or "", params=params, preset=preset, scontorno=a.scontorno)

    result = compose(job, preview_max=a.anteprima)
    out = Path(a.out)
    if preset:
        path = export(result, preset, out)
    else:
        fmt = out.suffix.lower().lstrip(".") or "jpg"
        path = save_image(result.image, out, fmt if fmt in FORMATI else "jpg", 92)
    for w in warnings + result.warnings:
        print(f"Attenzione: {w}", file=sys.stderr)
    print(f"Creato: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arloc", description="Arloc: compone il mosaico su uno sfondo")
    sub = parser.add_subparsers(dest="comando", required=True)
    _add_compose(sub)
    try:  # il sottocomando batch lo registra arloc.core.batch, se presente
        from .core.batch import register_batch
        register_batch(sub)
    except ImportError:
        pass
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ArlocError as e:
        print(f"Errore: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
