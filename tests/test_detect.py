import cv2
import numpy as np

from arloc.core.detect import find_green_area, find_mosaic_corners


def _bg():
    rng = np.random.default_rng(1)
    return rng.integers(80, 140, (400, 600, 3)).astype(np.uint8)


def test_green_rect():
    img = _bg()
    cv2.rectangle(img, (200, 100), (400, 300), (0, 255, 0), -1)
    quad, mask = find_green_area(img)
    xs = sorted(p[0] for p in quad.points)
    assert abs(xs[0] - 200) < 4 and abs(xs[-1] - 400) < 4
    assert quad.points[0][0] < quad.points[1][0] and quad.points[0][1] < quad.points[3][1]
    assert mask[200, 300] == 255 and mask[10, 10] == 0


def test_green_rotated_and_none():
    img = _bg()
    pts = np.array([[150, 120], [420, 90], [450, 300], [180, 330]], np.int32)
    cv2.fillPoly(img, [pts], (0, 255, 0))
    quad, _ = find_green_area(img)
    for got, exp in zip(quad.points, pts):
        assert np.hypot(got[0] - exp[0], got[1] - exp[1]) < 5
    assert find_green_area(_bg()) is None


def test_mosaic_corners_exclude_flat_border():
    img = np.full((600, 800, 3), 240, np.uint8)
    rng = np.random.default_rng(2)
    img[100:500, 150:650] = rng.integers(0, 255, (400, 500, 3))  # zona "granulosa"
    q = find_mosaic_corners(img).as_array()
    assert q[:, 0].min() > 120 and q[:, 0].max() < 680
    assert q[:, 1].min() > 70 and q[:, 1].max() < 530
