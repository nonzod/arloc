import numpy as np
import pytest

from arloc.core.geometry import order_quad, parse_area, placement_quad, px_per_cm
from arloc.core.models import ArlocError, ComposeParams, Quad


def test_order_quad_any_order():
    q = order_quad([(10, 10), (0, 10), (10, 0), (0, 0)])
    assert q.points == [(0, 0), (10, 0), (10, 10), (0, 10)]


def test_parse_area():
    q = parse_area("100,50; 10,50; 10,5; 100,5")
    assert q.points[0] == (10, 5) and q.points[2] == (100, 50)
    for bad in ("1,2;3,4", "a,b;1,2;3,4;5,6", ""):
        with pytest.raises(ArlocError):
            parse_area(bad)


def test_px_per_cm():
    assert px_per_cm(1200, 100) == 12
    with pytest.raises(ArlocError):
        px_per_cm(1200, 0)


def test_placement_identical_area():
    area = Quad([(100, 100), (400, 100), (400, 300), (100, 300)])
    q = placement_quad(area, 300, 200, ComposeParams(), 10)
    assert np.allclose(q.as_array(), area.as_array(), atol=0.01)
    q = placement_quad(area, 100, 100, ComposeParams(offset_x_cm=5), 10)  # +50 px a destra
    assert np.allclose(q.as_array().mean(axis=0), [300, 200], atol=0.01)
