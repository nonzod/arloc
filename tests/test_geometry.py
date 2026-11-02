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


def test_auto_mosaic_size_preserves_ratio_and_fills_area():
    from arloc.core.geometry import auto_mosaic_size, plane_size
    from arloc.core.models import Quad
    area = Quad([(100, 100), (500, 100), (500, 500), (100, 500)])        # quadrata 400x400
    mosaic = Quad([(0, 0), (300, 0), (300, 200), (0, 200)])               # 3:2
    mw, mh, ppc = auto_mosaic_size(area, mosaic, 0.9)
    assert mw == pytest.approx(400 * 0.9)
    assert mw / mh == pytest.approx(1.5)
    assert ppc == pytest.approx(mh / 30)


def test_compose_automatic_without_measures():
    import numpy as np
    from arloc.core import compose as cm
    from arloc.core.models import ArlocError, ComposeParams, Job, Quad
    import cv2, tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    bg = np.full((600, 800, 3), 200, np.uint8)
    mo = np.random.default_rng(1).integers(0, 255, (200, 300, 3), dtype=np.uint8)
    cv2.imwrite(str(d / "b.png"), bg)
    cv2.imwrite(str(d / "m.png"), mo)
    area = Quad([(200, 100), (600, 100), (600, 500), (200, 500)])
    q = Quad([(0, 0), (300, 0), (300, 200), (0, 200)])
    job = Job(sfondo=d / "b.png", mosaico=d / "m.png", area=area, mosaico_quad=q,
              scontorno="rettangolo", misure="automatiche", params=ComposeParams(riempimento=0.9))
    res = cm.compose(job)
    pts = res.mosaic_quad.as_array()
    assert np.linalg.norm(pts[1] - pts[0]) == pytest.approx(360, abs=0.5)
    assert np.linalg.norm(pts[3] - pts[0]) == pytest.approx(240, abs=0.5)
    assert not res.warnings
    job.misure = "reali"
    with pytest.raises(ArlocError, match="automatiche"):
        cm.compose(job)
