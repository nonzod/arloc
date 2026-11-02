import sys
import types
from pathlib import Path

import pytest

from arloc.core import batch
from arloc.core.models import ArlocError, ComposeParams, OutputPreset, Quad

DEFAULT = OutputPreset("shopify", 2048, 2048, "jpg", 90)


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    """Stub minimi di geometry/presets: il test non dipende dagli altri moduli."""
    def parse_area(text):
        pts = [tuple(float(v) for v in p.split(",")) for p in text.split(";")]
        if len(pts) != 4:
            raise ArlocError("Area non valida.")
        return Quad(pts)

    def parse_preset(text):
        return OutputPreset(text.split()[0], 1000, 1000)

    monkeypatch.setitem(sys.modules, "arloc.core.geometry", types.SimpleNamespace(parse_area=parse_area))
    monkeypatch.setitem(sys.modules, "arloc.core.presets", types.SimpleNamespace(parse_preset=parse_preset))
    core = sys.modules["arloc.core"]
    monkeypatch.setattr(core, "geometry", sys.modules["arloc.core.geometry"], raising=False)
    monkeypatch.setattr(core, "presets", sys.modules["arloc.core.presets"], raising=False)


def make_files(tmp_path):
    (tmp_path / "sfondi").mkdir()
    (tmp_path / "mosaici").mkdir()
    (tmp_path / "sfondi" / "MARMO 1.jpg").write_bytes(b"x")
    (tmp_path / "mosaici" / "M30.jpg").write_bytes(b"x")


def test_csv_semicolon_decimals_relative_area(tmp_path):
    make_files(tmp_path)
    f = tmp_path / "b.csv"
    f.write_text(
        "Sfondo;Mosaico;Larghezza Sfondo CM;larghezza_mosaico_cm;Altezza_Mosaico_cm;Area;Istruzioni;Preset;Nome_Output\n"
        "sfondi/MARMO 1.jpg;mosaici/M30.jpg;120;30,5;20,25;"
        "812,540;1310,540;1310,880;812,880;ombra a sinistra;etsy;\n",
        encoding="utf-8")
    # l'area con ; senza virgolette rompe le colonne: usa le virgolette come farebbe Excel
    f.write_text(
        "Sfondo;Mosaico;Larghezza Sfondo CM;larghezza_mosaico_cm;Altezza_Mosaico_cm;Area;Istruzioni;Preset;Nome_Output\n"
        'sfondi/MARMO 1.jpg;mosaici/M30.jpg;120;30,5;20,25;"812,540;1310,540;1310,880;812,880";ombra a sinistra;etsy;\n',
        encoding="utf-8")
    rows = batch.read_batch(f, DEFAULT)
    assert len(rows) == 1 and rows[0].error is None
    j = rows[0].job
    assert j.sfondo == tmp_path / "sfondi" / "MARMO 1.jpg"
    assert j.larghezza_mosaico_cm == 30.5 and j.altezza_mosaico_cm == 20.25
    assert j.area is not None and j.area.points[0] == (812.0, 540.0)
    assert j.preset.nome == "etsy"
    assert j.nome_output == "M30_MARMO 1"
    assert j.istruzioni == "ombra a sinistra"


def test_csv_comma_separator_and_default_preset(tmp_path):
    make_files(tmp_path)
    f = tmp_path / "b.csv"
    f.write_text("sfondo,mosaico,larghezza_sfondo_cm,larghezza_mosaico_cm,altezza_mosaico_cm\n"
                 "sfondi/MARMO 1.jpg,mosaici/M30.jpg,120,30,20\n", encoding="utf-8")
    rows = batch.read_batch(f, DEFAULT)
    assert rows[0].job.preset is DEFAULT and rows[0].job.area is None


def test_invalid_row_is_flagged_not_fatal(tmp_path):
    make_files(tmp_path)
    f = tmp_path / "b.csv"
    f.write_text("sfondo;mosaico;larghezza_sfondo_cm;larghezza_mosaico_cm;altezza_mosaico_cm\n"
                 "sfondi/MARMO 1.jpg;mosaici/M30.jpg;120;30;20\n"
                 "sfondi/nonesiste.jpg;mosaici/M30.jpg;120;30;20\n"
                 "sfondi/MARMO 1.jpg;mosaici/M30.jpg;abc;30;20\n", encoding="utf-8")
    rows = batch.read_batch(f, DEFAULT)
    assert [r.status for r in rows] == ["in attesa", "saltata", "saltata"]
    assert "non trovato" in rows[1].error and "numero" in rows[2].error


def test_missing_column(tmp_path):
    f = tmp_path / "b.csv"
    f.write_text("sfondo\na\n", encoding="utf-8")
    with pytest.raises(ArlocError):
        batch.read_batch(f, DEFAULT)


def test_xlsx_and_template(tmp_path):
    make_files(tmp_path)
    x = tmp_path / "t.xlsx"
    batch.write_template(x)
    assert x.exists()
    import pandas as pd
    assert list(pd.read_excel(x).columns) == batch.COLUMNS


def test_run_batch_report_and_failure_isolation(tmp_path, monkeypatch):
    make_files(tmp_path)
    f = tmp_path / "b.csv"
    f.write_text("sfondo;mosaico;larghezza_sfondo_cm;larghezza_mosaico_cm;altezza_mosaico_cm;istruzioni\n"
                 "sfondi/MARMO 1.jpg;mosaici/M30.jpg;120;30;20;ombra a sinistra\n"
                 "sfondi/MARMO 1.jpg;mosaici/M30.jpg;120;31;20;\n", encoding="utf-8")
    rows = batch.read_batch(f, DEFAULT)
    calls = []

    def fake_compose(job):
        calls.append(job)
        if job.larghezza_mosaico_cm == 31:
            raise ArlocError("boom")
        return types.SimpleNamespace(warnings=[])

    def fake_export(result, preset, path):
        p = Path(str(path) + ".jpg")
        p.write_bytes(b"x")
        return p

    monkeypatch.setitem(sys.modules, "arloc.core.compose", types.SimpleNamespace(compose=fake_compose))
    monkeypatch.setattr(sys.modules["arloc.core"], "compose", sys.modules["arloc.core.compose"], raising=False)
    monkeypatch.setattr(sys.modules["arloc.core.presets"], "export", fake_export, raising=False)
    monkeypatch.setattr("arloc.core.instructions.parse_instructions",
                        lambda t, c, s=None: (c.updated(ombra_direzione_gradi=180), None))
    report = batch.run_batch(rows, tmp_path / "out")
    assert report.name.startswith("report_") and report.suffix == ".csv"
    assert [r.status for r in rows] == ["ok", "errore"]
    assert calls[0].params.ombra_direzione_gradi == 180
    txt = report.read_text(encoding="utf-8-sig")
    assert "stato;errore;file_generato" in txt.splitlines()[0] and "boom" in txt


def test_misure_automatiche_se_colonne_vuote_e_parziali(tmp_path):
    make_files(tmp_path)
    f = tmp_path / "m.csv"
    f.write_text(
        "sfondo;mosaico;larghezza_sfondo_cm;larghezza_mosaico_cm;altezza_mosaico_cm;misure\n"
        "sfondi/MARMO 1.jpg;mosaici/M30.jpg;;;;\n"
        "sfondi/MARMO 1.jpg;mosaici/M30.jpg;120;30;20;\n"
        "sfondi/MARMO 1.jpg;mosaici/M30.jpg;120;;20;\n"
        "sfondi/MARMO 1.jpg;mosaici/M30.jpg;120;30;20;automatiche\n"
        "sfondi/MARMO 1.jpg;mosaici/M30.jpg;;;;reali\n", encoding="utf-8")
    rows = batch.read_batch(f, DEFAULT)
    assert rows[0].job.misure == "automatiche" and rows[0].job.larghezza_sfondo_cm == 0
    assert rows[1].job.misure == "reali" and rows[1].job.larghezza_mosaico_cm == 30
    assert rows[2].job is None and "larghezza_mosaico_cm" in rows[2].error
    assert rows[3].job.misure == "automatiche"
    assert rows[4].job is None and "larghezza_sfondo_cm" in rows[4].error


def test_ritocco_ai_column(tmp_path):
    from arloc.core import batch
    for n in ("a.jpg", "b.jpg"):
        (tmp_path / n).write_bytes(b"x")
    f = tmp_path / "b.csv"
    f.write_text("sfondo;mosaico;ritocco_ai\na.jpg;b.jpg;sì\na.jpg;b.jpg;\na.jpg;b.jpg;no\na.jpg;b.jpg;forse\n", encoding="utf-8")
    rows = batch.read_batch(f, DEFAULT)
    assert [r.job.ritocco_ai if r.job else None for r in rows] == [True, False, False, None]
    assert "ritocco_ai" in rows[3].error
