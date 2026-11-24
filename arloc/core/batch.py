"""Modalità batch: lettura CSV/XLSX, validazione, esecuzione e report (IMPLEMENTAZIONE.md §7)."""
from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import ArlocError, ComposeParams, Job, OutputPreset

REQUIRED = ["sfondo", "mosaico"]
CM_COLUMNS = ["larghezza_sfondo_cm", "larghezza_mosaico_cm", "altezza_mosaico_cm"]
OPTIONAL = ["area", "istruzioni", "preset", "nome_output", "scontorno", "misure", "ritocco_ai"]
COLUMNS = REQUIRED + CM_COLUMNS + OPTIONAL
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


@dataclass
class BatchRow:
    index: int
    raw: dict
    job: Job | None = None
    error: str | None = None
    status: str = "in attesa"  # "in attesa" | "ok" | "errore" | "saltata"
    output: Path | None = None


def _norm_header(h) -> str:
    s = unicodedata.normalize("NFKD", str(h))
    s = "".join(c for c in s if not unicodedata.combining(c)).strip().lower()
    return re.sub(r"[\s\-]+", "_", s)


def _num(value, nome: str) -> float:
    s = str(value).strip().replace(",", ".")
    if not s:
        raise ArlocError(f"Manca il valore di «{nome}».")
    try:
        v = float(s)
    except ValueError:
        raise ArlocError(f"«{nome}» non è un numero valido: {value!r}.") from None
    if v <= 0:
        raise ArlocError(f"«{nome}» deve essere maggiore di zero.")
    return v


def _read_table(path: Path):
    import pandas as pd
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path, dtype=str, keep_default_na=False)
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    first = text.splitlines()[0] if text.strip() else ""
    sep = ";" if first.count(";") > first.count(",") else ","
    import io
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)


def read_batch(path, default_preset: OutputPreset) -> list[BatchRow]:
    path = Path(path)
    try:
        df = _read_table(path)
    except Exception as e:
        raise ArlocError(f"Impossibile leggere il file batch «{path.name}»: {e}") from None
    df.columns = [_norm_header(c) for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ArlocError("Nel file batch mancano le colonne: " + ", ".join(missing) + ".")
    base = path.parent
    rows: list[BatchRow] = []
    for i, rec in enumerate(df.to_dict("records")):
        raw = {k: ("" if v is None else str(v).strip()) for k, v in rec.items()}
        if not any(raw.values()):
            continue
        row = BatchRow(index=len(rows) + 1, raw=raw)
        try:
            row.job = _build_job(raw, base, default_preset)
        except ArlocError as e:
            row.error, row.status = str(e), "saltata"
        except Exception as e:
            row.error, row.status = f"Riga non valida: {e}", "saltata"
        rows.append(row)
    return rows


def _resolve(value: str, base: Path, nome: str) -> Path:
    if not value:
        raise ArlocError(f"Manca il valore di «{nome}».")
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = base / p
    if not p.is_file():
        raise ArlocError(f"File non trovato per «{nome}»: {value}")
    return p


def _build_job(raw: dict, base: Path, default_preset: OutputPreset) -> Job:
    from . import geometry, presets
    sfondo = _resolve(raw.get("sfondo", ""), base, "sfondo")
    mosaico = _resolve(raw.get("mosaico", ""), base, "mosaico")
    filled = [c for c in CM_COLUMNS if raw.get(c, "").strip()]
    misure = raw.get("misure", "").strip().lower()
    if misure and misure not in ("reali", "automatiche"):
        raise ArlocError(f"«misure» deve essere reali o automatiche: {raw.get('misure')!r}.")
    if not misure:
        if filled and len(filled) < len(CM_COLUMNS):
            mancano = ", ".join(c for c in CM_COLUMNS if c not in filled)
            raise ArlocError(f"Misure incomplete: compila anche {mancano}, oppure lascia vuote tutte e tre per le misure automatiche.")
        misure = "reali" if filled else "automatiche"
    lbg = lm = hm = 0.0
    if misure == "reali":
        lbg = _num(raw.get("larghezza_sfondo_cm", ""), "larghezza_sfondo_cm")
        lm = _num(raw.get("larghezza_mosaico_cm", ""), "larghezza_mosaico_cm")
        hm = _num(raw.get("altezza_mosaico_cm", ""), "altezza_mosaico_cm")
    area = geometry.parse_area(raw["area"]) if raw.get("area") else None
    preset = presets.parse_preset(raw["preset"]) if raw.get("preset") else default_preset
    nome = raw.get("nome_output") or f"{mosaico.stem}_{sfondo.stem}"
    nome = re.sub(r'[\\/:*?"<>|]+', "_", nome).strip() or f"{mosaico.stem}_{sfondo.stem}"
    scontorno = raw.get("scontorno", "").strip().lower() or "auto"
    if scontorno not in ("auto", "rettangolo", "forma"):
        raise ArlocError(f"«scontorno» deve essere auto, rettangolo o forma: {raw.get('scontorno')!r}.")
    ritocco = raw.get("ritocco_ai", "").strip().lower()
    if ritocco in ("", "no", "n", "0", "false"):
        ritocco_ai = False
    elif ritocco in ("sì", "si", "s", "yes", "y", "1", "true"):
        ritocco_ai = True
    else:
        raise ArlocError(f"«ritocco_ai» deve essere sì o no (o vuoto): {raw.get('ritocco_ai')!r}.")
    return Job(sfondo=sfondo, mosaico=mosaico, larghezza_sfondo_cm=lbg, larghezza_mosaico_cm=lm,
               altezza_mosaico_cm=hm, area=area, istruzioni=raw.get("istruzioni", ""),
               preset=preset, nome_output=nome, scontorno=scontorno, misure=misure, ritocco_ai=ritocco_ai)


def run_batch(rows, out_dir, progress=None, should_stop=None, use_claude=True) -> Path:
    from . import presets
    from .pipeline import render
    from .settings import load_settings
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    total = len(rows)
    used: set[str] = set()
    for n, row in enumerate(rows, 1):
        if row.job is None:
            row.status = "saltata"
        elif should_stop and should_stop():
            row.status, row.error = "saltata", "Interrotta dall'utente."
        else:
            try:
                job, result, warns = render(row.job, settings, use_claude=use_claude)
                name, k = job.nome_output, 2
                while name.lower() in used:
                    name, k = f"{job.nome_output}_{k}", k + 1
                used.add(name.lower())
                row.output = Path(presets.export(result, job.preset, out_dir / name))
                row.status = "ok"
                row.error = " ".join(warns + list(result.warnings)) or None
            except Exception as e:
                row.status, row.error = "errore", str(e) or type(e).__name__
        if progress:
            try:
                progress(n, total, row)
            except Exception:
                pass
    return _write_report(rows, out_dir)


def _write_report(rows, out_dir: Path) -> Path:
    import pandas as pd
    recs = []
    for r in rows:
        d = dict(r.raw)
        d["stato"] = r.status
        d["errore"] = r.error or ""
        d["file_generato"] = str(r.output) if r.output else ""
        recs.append(d)
    cols = list(rows[0].raw.keys()) if rows else COLUMNS
    df = pd.DataFrame(recs, columns=cols + ["stato", "errore", "file_generato"])
    path = out_dir / f"report_{datetime.now():%Y%m%d_%H%M}.csv"
    df.to_csv(path, index=False, sep=";", encoding="utf-8-sig")
    return path


def write_template(path) -> Path:
    """Scrive il modello batch (.csv o .xlsx, in base all'estensione) copiandolo da templates/."""
    path = Path(path)
    src = TEMPLATES_DIR / ("modello_batch.xlsx" if path.suffix.lower() == ".xlsx" else "modello_batch.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copyfile(src, path)
    else:
        _generate_template(path)
    return path


_EXAMPLE_ROWS = [
    ["../examples/sfondi/MARMO 1.jpg", "../examples/mosaici/M21.png", "120", "30", "20", "",
     "ombra morbida verso destra", "shopify", "M21_marmo1", "", "", ""],
    ["../examples/sfondi/CERAMICA 1.jpg", "../examples/mosaici/P41.jpg", "100", "25,5", "25", "",
     "", "etsy", "", "", "", ""],
    ["../examples/sfondi/VETRO 1.jpg", "../examples/mosaici/RIFERIMENTO_vetro_S108.jpg", "", "", "",
     "557,267;1037,267;1037,867;557,867", "", "shopify", "", "", "", ""],
]


def _generate_template(path: Path) -> None:
    if path.suffix.lower() == ".xlsx":
        import pandas as pd
        pd.DataFrame(_EXAMPLE_ROWS, columns=COLUMNS).to_excel(path, index=False)
    else:
        lines = [";".join(COLUMNS)] + [";".join(r) for r in _EXAMPLE_ROWS]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def register_batch(subparsers) -> None:
    p = subparsers.add_parser("batch", help="Elabora un file batch CSV/XLSX")
    p.add_argument("file", help="File CSV o XLSX")
    p.add_argument("--out", required=True, help="Cartella di output")
    p.add_argument("--preset", default="shopify", help='Preset predefinito: shopify, etsy, "custom 1600x1200 png"')
    p.add_argument("--no-claude", action="store_true", help="Ignora le istruzioni in testo libero")
    p.set_defaults(func=_cli_batch)


def _cli_batch(args) -> int:
    from . import presets
    try:
        rows = read_batch(args.file, presets.parse_preset(args.preset))
    except ArlocError as e:
        print(f"Errore: {e}")
        return 2
    for r in rows:
        if r.error:
            print(f"Riga {r.index}: saltata - {r.error}")

    def prog(i, total, row):
        print(f"[{i}/{total}] riga {row.index}: {row.status}" + (f" - {row.error}" if row.error else ""))

    report = run_batch(rows, args.out, progress=prog, use_claude=not args.no_claude)
    print(f"Report: {report}")
    return 0 if all(r.status == "ok" for r in rows) else 1
