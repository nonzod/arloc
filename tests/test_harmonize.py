import base64
import types

import cv2
import numpy as np
import pytest

from arloc.core import harmonize, instructions, settings
from arloc.core.models import ComposeResult, Quad


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._d = status, data

    def json(self):
        if self._d is None:
            raise ValueError("no json")
        return self._d


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(settings, "get_openrouter_key", lambda: "or-test")
    st = settings.Settings(provider="openrouter")
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    monkeypatch.setattr(instructions, "_MODELS_CACHE", None)


def scene():
    rng = np.random.default_rng(1)
    base = cv2.GaussianBlur(rng.integers(60, 200, (240, 320, 3), dtype=np.uint8), (0, 0), 3)
    img = base.copy()
    mask = np.zeros((240, 320), np.uint8)
    mask[70:170, 100:220] = 255
    tiles = rng.integers(0, 255, (100, 120, 3), dtype=np.uint8)   # "tessere" molto nitide
    img[70:170, 100:220] = tiles
    return ComposeResult(image=img, center=(160, 120), mosaic_quad=Quad([(100, 70), (220, 70), (220, 170), (100, 170)]),
                         mosaic_mask=mask)


def reply(img):
    ok, buf = cv2.imencode(".png", img)
    url = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()
    return _Resp(200, {"choices": [{"message": {"content": "", "images": [{"type": "image_url", "image_url": {"url": url}}]}}]})


def post_returns(monkeypatch, resp, calls=None):
    def post(url, headers=None, json=None, timeout=None):
        if calls is not None:
            calls.append(json)
        return resp
    monkeypatch.setattr(instructions.httpx, "post", post)


def test_mosaic_untouched_outside_changed(monkeypatch):
    r = scene()
    ai = r.image.copy()
    ai[:, :] = np.clip(ai.astype(int) * 0.85, 0, 255).astype(np.uint8)   # luce cambiata ovunque
    ai[100:112, 100:220] = 0                                              # tessere "rovinate" dall'AI
    calls = []
    post_returns(monkeypatch, reply(ai), calls)
    out, warn = harmonize.harmonize(r, r.mosaic_mask)
    assert warn is None
    assert calls[0]["modalities"] == ["image", "text"]
    inner = cv2.erode(r.mosaic_mask, np.ones((17, 17), np.uint8)) > 0
    diff = np.abs(out.astype(int) - r.image.astype(int))[inner]
    assert diff.max() <= 0.1 * 255 + 1            # solo la correzione di luminosità (max 10%)
    # le tessere rovinate dall'AI non compaiono
    assert out[100:112, 120:200].mean() > 60
    outside = cv2.dilate(r.mosaic_mask, np.ones((15, 15), np.uint8)) == 0
    assert np.abs(out.astype(int) - r.image.astype(int))[outside].mean() > 5


def test_unchanged_mosaic_is_identical(monkeypatch):
    r = scene()
    ai = r.image.copy()
    ai[mask_out(r)] = (ai[mask_out(r)] * 0.8).astype(np.uint8)
    post_returns(monkeypatch, reply(ai))
    out, warn = harmonize.harmonize(r, r.mosaic_mask)
    inner = cv2.erode(r.mosaic_mask, np.ones((15, 15), np.uint8)) > 0
    assert warn is None and np.array_equal(out[inner], r.image[inner])


def mask_out(r):
    return r.mosaic_mask == 0


def test_shifted_discarded(monkeypatch):
    r = scene()
    ai = np.roll(r.image, 30, axis=1)
    post_returns(monkeypatch, reply(ai))
    out, warn = harmonize.harmonize(r, r.mosaic_mask)
    assert np.array_equal(out, r.image) and "spostato" in warn


def test_no_image_and_errors(monkeypatch):
    r = scene()
    post_returns(monkeypatch, _Resp(200, {"choices": [{"message": {"content": "no"}}]}))
    out, warn = harmonize.harmonize(r, r.mosaic_mask)
    assert np.array_equal(out, r.image) and "nessuna immagine" in warn
    post_returns(monkeypatch, _Resp(402, {"error": {"message": "credits"}}))
    out, warn = harmonize.harmonize(r, r.mosaic_mask)
    assert np.array_equal(out, r.image) and "credito" in warn
    monkeypatch.setattr(instructions.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(instructions.httpx.ReadTimeout("t")))
    out, warn = harmonize.harmonize(r, r.mosaic_mask)
    assert "tempo scaduto" in warn


def test_provider_and_key(monkeypatch):
    r = scene()
    out, warn = harmonize.harmonize(r, None, settings.Settings(provider="anthropic"))
    assert "OpenRouter" in warn and np.array_equal(out, r.image)
    monkeypatch.setattr(settings, "get_openrouter_key", lambda: None)
    out, warn = harmonize.harmonize(r, None)
    assert "chiave" in warn


def test_cache_on_disk(monkeypatch):
    r = scene()
    ai = r.image.copy()
    ai[mask_out(r)] = (ai[mask_out(r)] * 0.9).astype(np.uint8)
    calls = []
    post_returns(monkeypatch, reply(ai), calls)
    harmonize.harmonize(r, r.mosaic_mask)
    harmonize.harmonize(r, r.mosaic_mask)
    assert len(calls) == 1


# ---------- check_models ----------

def entry(i, o, params=("structured_outputs",)):
    return {"architecture": {"input_modalities": i, "output_modalities": o}, "supported_parameters": list(params)}


MODELS = {
    "qwen/qwen3-vl-8b-instruct": entry(["text", "image"], ["text"]),
    "qwen/qwen3-vl-235b-a22b-instruct": entry(["text", "image"], ["text"]),
    "qwen/qwen3.6-plus": entry(["text", "image"], ["text"]),
    "qwen/qwen-image-edit": entry(["text", "image"], ["image"]),
    "anthropic/claude-haiku-5.5": entry(["text", "image"], ["text"]),
    "anthropic/claude-sonnet-5.5": entry(["text", "image"], ["text"]),
    "old/plain": entry(["text", "image"], ["text"], ()),
    "google/gemini-3.1-flash-image": entry(["text", "image"], ["text", "image"]),
}


def mock_models(monkeypatch, models=MODELS):
    calls = []

    def get(url, headers=None, timeout=None):
        calls.append(url)
        return _Resp(200, {"data": [dict(v, id=k) for k, v in models.items()]})
    monkeypatch.setattr(instructions.httpx, "get", get)
    return calls


def test_check_models_missing_wrongrole_ok(monkeypatch):
    calls = mock_models(monkeypatch)
    st = settings.Settings(provider="openrouter", openrouter_model_instructions="old/plain",
                           openrouter_model_light="qwen/qwen-image-2.1-turbo",
                           openrouter_model_retouch="google/gemini-3.1-flash-image")
    res = instructions.check_models(st)
    d = {r[0]: r for r in res}
    assert d["light"][1] == "error" and "non esiste" in d["light"][2] and "qwen/qwen3-vl" in d["light"][2]
    assert d["instructions"][1] == "warn" and "meno affidabile" in d["instructions"][2]
    assert d["retouch"][1] == "ok"
    st.openrouter_model_instructions = "qwen/qwen-image-edit"
    st.openrouter_model_light = "qwen/qwen3-vl-8b-instruct"
    st.openrouter_model_retouch = "anthropic/claude-haiku-5.5"
    d = {r[0]: r for r in instructions.check_models(st)}
    assert d["instructions"][1] == "error" and "genera immagini" in d["instructions"][2]
    assert d["light"][1] == "ok"
    assert d["retouch"][1] == "error"
    assert len(calls) == 1   # elenco in cache


def test_check_models_never_raises(monkeypatch):
    monkeypatch.setattr(instructions.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    res = instructions.check_models(settings.Settings(provider="openrouter"))
    assert all(r[1] == "warn" for r in res)


def test_check_models_anthropic(monkeypatch):
    class NotFoundError(Exception):
        pass

    class C:
        class models:
            @staticmethod
            def retrieve(m):
                if m == "claude-x":
                    raise NotFoundError("nf")
    monkeypatch.setattr("anthropic.Anthropic", lambda **k: C)
    st = settings.Settings(model_instructions="claude-x", model_light="claude-ok")
    d = {r[0]: r for r in instructions.check_models(st, key="sk")}
    assert d["instructions"][1] == "error" and "non esiste" in d["instructions"][2]
    assert d["light"][1] == "ok"


def test_use_time_message_names_model(monkeypatch):
    monkeypatch.setattr(settings, "get_api_key", lambda: None)
    st = settings.Settings(provider="openrouter", openrouter_model_instructions="qwen/qwen-image-2.1-turbo")
    monkeypatch.setattr(instructions.httpx, "post",
                        lambda *a, **k: _Resp(404, {"error": {"message": "No endpoints found for qwen/qwen-image-2.1-turbo"}}))
    from arloc.core.models import ComposeParams
    p, w = instructions.parse_instructions("ombra", ComposeParams(), st)
    assert "qwen/qwen-image-2.1-turbo" in w and "non esiste" in w
