"""Scontorno del mosaico: immagini sintetiche (tessere colorate con fughe chiare su fondo liscio)."""
import cv2
import numpy as np

from arloc.core.batch import read_batch
from arloc.core.cutout import cutout_mosaic, quad_coverage, quad_from_mask, use_shape
from arloc.core.models import OutputPreset


def _tiles(shape_mask: np.ndarray, seed=1) -> np.ndarray:
    """Fondo grigio chiaro liscio; dentro la forma tessere colorate separate da fughe chiare."""
    h, w = shape_mask.shape
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 235, np.uint8)
    step = 14
    for y in range(0, h, step):
        for x in range(0, w, step):
            col = rng.integers(40, 200, 3).tolist()
            cv2.rectangle(img, (x + 2, y + 2), (x + step - 2, y + step - 2), col, -1)
    out = np.full_like(img, 235)
    out[shape_mask > 0] = img[shape_mask > 0]
    return out


def test_round_mosaic_gives_round_mask_without_holes():
    m = np.zeros((600, 600), np.uint8)
    cv2.circle(m, (300, 300), 200, 255, -1)
    mask = cutout_mosaic(_tiles(m))
    assert mask.shape == m.shape and mask.dtype == np.uint8
    binary = mask > 127
    inter = (binary & (m > 0)).sum()
    union = (binary | (m > 0)).sum()
    assert inter / union > 0.93                      # circolare
    inside = cv2.erode(m, np.ones((41, 41), np.uint8)) > 0
    assert binary[inside].all()                      # nessun buco (le fughe chiare non sono buchi)
    assert binary[:60].sum() == 0 and binary[:, :60].sum() == 0   # fuori resta escluso


def test_auto_picks_shape_for_round_and_rectangle_for_rectangle():
    r = np.zeros((600, 600), np.uint8)
    cv2.circle(r, (300, 300), 200, 255, -1)
    img = _tiles(r)
    mask = cutout_mosaic(img)
    assert use_shape("auto", mask, quad_from_mask(mask), img)

    rect = np.zeros((600, 800), np.uint8)
    rect[100:500, 150:650] = 255
    img = _tiles(rect, seed=2)
    mask = cutout_mosaic(img)
    q = quad_from_mask(mask)
    assert quad_coverage(mask, q) > 0.92
    assert not use_shape("auto", mask, q, img)
    assert use_shape("forma", mask, q, img) and not use_shape("rettangolo", mask, q, img)


def test_png_alpha_is_used():
    alpha = np.zeros((300, 400), np.uint8)
    cv2.circle(alpha, (200, 150), 100, 255, -1)
    img = np.dstack([np.full((300, 400, 3), 128, np.uint8), alpha])
    mask = cutout_mosaic(img)
    assert mask[150, 200] > 250 and mask[5, 5] == 0
    assert use_shape("auto", mask, quad_from_mask(mask), img)


def test_batch_column_scontorno(tmp_path):
    for n in ("a.jpg", "b.jpg"):
        cv2.imwrite(str(tmp_path / n), np.zeros((20, 20, 3), np.uint8))
    (tmp_path / "t.csv").write_text(
        "sfondo;mosaico;larghezza_sfondo_cm;larghezza_mosaico_cm;altezza_mosaico_cm;scontorno\n"
        "a.jpg;b.jpg;100;30;20;\na.jpg;b.jpg;100;30;20;Forma\na.jpg;b.jpg;100;30;20;boh\n", encoding="utf-8")
    rows = read_batch(tmp_path / "t.csv", OutputPreset("shopify", 100, 100))
    assert rows[0].job.scontorno == "auto" and rows[1].job.scontorno == "forma"
    assert rows[2].job is None and "scontorno" in rows[2].error
