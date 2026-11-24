import json
import types

import pytest

from arloc.core import ai, instructions, settings
from arloc.core.models import ComposeParams


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(settings, "get_api_key", lambda: "sk-test")
    monkeypatch.setattr(settings, "_config_path", lambda: tmp_path / "none.json")


def fake(monkeypatch, text, stop="end_turn", counter=None):
    class C:
        class messages:
            @staticmethod
            def create(**kw):
                assert "temperature" not in kw and "tool_choice" not in kw
                assert kw["output_config"]["format"]["type"] == "json_schema"
                if counter is not None:
                    counter.append(kw)
                return types.SimpleNamespace(stop_reason=stop, content=[types.SimpleNamespace(type="text", text=text)])
    monkeypatch.setattr(ai, "_anthropic_client", lambda key=None: C)


def test_parse_ok_clamp_and_cache(monkeypatch):
    calls = []
    fake(monkeypatch, json.dumps({"ombra_direzione_gradi": 180, "grana": 7}), counter=calls)
    p, w = instructions.parse_instructions("Ombra a  sinistra", ComposeParams())
    assert w is None and p.ombra_direzione_gradi == 180 and p.grana == 1.0
    p, w = instructions.parse_instructions("ombra a sinistra", ComposeParams())
    assert len(calls) == 1 and p.ombra_direzione_gradi == 180


def test_refusal_and_bad_json(monkeypatch):
    fake(monkeypatch, "", stop="refusal")
    p, w = instructions.parse_instructions("x", ComposeParams())
    assert p == ComposeParams() and w
    fake(monkeypatch, "non json")
    p, w = instructions.parse_instructions("y", ComposeParams())
    assert w


def test_no_key_and_empty(monkeypatch):
    monkeypatch.setattr(settings, "get_api_key", lambda: None)
    p, w = instructions.parse_instructions("z", ComposeParams())
    assert w and "mancante" in w
    assert instructions.parse_instructions("  ", ComposeParams()) == (ComposeParams(), None)


def test_suggest_light(monkeypatch):
    import numpy as np
    fake(monkeypatch, json.dumps({"ombra_direzione_gradi": 200, "ombra_morbidezza": 0.3, "ombra_opacita": 0.6}))
    d, w = instructions.suggest_light(np.full((50, 80, 3), 128, np.uint8))
    assert w is None and d["ombra_direzione_gradi"] == 200


def test_schema():
    s = instructions.params_schema()
    assert set(s["properties"]) == set(ComposeParams.RANGES) and s["additionalProperties"] is False
    assert "required" not in s


# ---------- OpenRouter ----------

class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._d = status, data

    def json(self):
        if self._d is None:
            raise ValueError("no json")
        return self._d


def _ok(text):
    return _Resp(200, {"choices": [{"message": {"content": text}}]})


@pytest.fixture
def orr(monkeypatch):
    monkeypatch.setattr(settings, "get_openrouter_key", lambda: "or-test")
    monkeypatch.setattr(settings, "get_api_key", lambda: None)
    st = settings.Settings(provider="openrouter")
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    return st


def fake_post(monkeypatch, responses, calls=None):
    it = iter(responses)

    def post(url, headers=None, json=None, timeout=None):
        assert url.endswith("/chat/completions") and headers["Authorization"] == "Bearer or-test"
        assert headers["X-Title"] == "Arloc"
        if calls is not None:
            calls.append(json)
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(ai._http, "post", post)


def test_openrouter_ok_and_cache(monkeypatch, orr):
    calls = []
    fake_post(monkeypatch, [_ok('{"ombra_direzione_gradi": 90}')], calls)
    p, w = instructions.parse_instructions("ombra in basso", ComposeParams())
    assert w is None and p.ombra_direzione_gradi == 90
    assert calls[0]["model"] == "anthropic/claude-haiku-5.5"
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    p, w = instructions.parse_instructions("ombra in basso", ComposeParams())
    assert len(calls) == 1 and p.ombra_direzione_gradi == 90


def test_openrouter_fallback_without_response_format(monkeypatch, orr):
    calls = []
    fake_post(monkeypatch, [_Resp(400, {"error": {"message": "unsupported"}}),
                            _ok('Ecco:\n```json\n{"grana": 0.4}\n```')], calls)
    p, w = instructions.parse_instructions("grana", ComposeParams())
    assert w is None and p.grana == 0.4
    assert "response_format" in calls[0] and "response_format" not in calls[1]


def test_openrouter_errors(monkeypatch, orr):
    fake_post(monkeypatch, [_Resp(401, {"error": {"message": "bad"}})])
    p, w = instructions.parse_instructions("a", ComposeParams())
    assert p == ComposeParams() and "non valida" in w
    fake_post(monkeypatch, [_Resp(402, {"error": {"message": "credits"}})])
    p, w = instructions.parse_instructions("b", ComposeParams())
    assert "Credito" in w
    fake_post(monkeypatch, [ai.httpx.ReadTimeout("t")])
    p, w = instructions.parse_instructions("c", ComposeParams())
    assert "tempo scaduto" in w


def test_openrouter_no_key_and_light(monkeypatch, orr):
    import numpy as np
    calls = []
    fake_post(monkeypatch, [_ok(json.dumps({"ombra_direzione_gradi": 10, "ombra_morbidezza": 0.2,
                                            "ombra_opacita": 0.5}))], calls)
    d, w = instructions.suggest_light(np.full((50, 80, 3), 128, np.uint8))
    assert w is None and d["ombra_direzione_gradi"] == 10
    part = calls[0]["messages"][1]["content"][0]
    assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    monkeypatch.setattr(settings, "get_openrouter_key", lambda: None)
    p, w = instructions.parse_instructions("zzz", ComposeParams())
    assert "OpenRouter" in w


def test_openrouter_verify(monkeypatch, orr):
    monkeypatch.setattr(ai._http, "get", lambda url, headers=None, timeout=None: _Resp(401, {}))
    assert instructions.verify_api_key("k")[0] is False
    monkeypatch.setattr(ai._http, "get", lambda url, headers=None, timeout=None: _Resp(200, {}))
    assert instructions.verify_api_key("k")[0] is True


def test_settings_backcompat(tmp_path, monkeypatch):
    f = tmp_path / "s.json"
    f.write_text('{"output_dir": "x"}')
    monkeypatch.setattr(settings, "_config_path", lambda: f)
    s = settings.load_settings()
    assert s.provider == "anthropic" and s.openrouter_model_light == "anthropic/claude-sonnet-5.5"


def test_openrouter_skips_schema_when_model_lacks_it(monkeypatch, orr):
    monkeypatch.setattr(ai, "_MODELS_CACHE", {"anthropic/claude-haiku-5.5": {"supported_parameters": ["max_tokens"]}})
    calls = []
    fake_post(monkeypatch, [_ok('{"grana": 0.2}')], calls)
    p, w = instructions.parse_instructions("un po' di grana", ComposeParams())
    assert w is None and p.grana == 0.2
    assert len(calls) == 1 and "response_format" not in calls[0]


def test_error_messages_per_context():
    o, a = ai.provider_for("openrouter"), ai.provider_for("anthropic")
    e = ai.AIError("not_found", "x/y")
    assert ai.message(e, o, "instructions").endswith("Uso i parametri attuali.") and "«x/y»" in ai.message(e, o, "light")
    assert ai.message(ai.AIError("credit"), o, "retouch").startswith("Ritocco AI non eseguito: credito OpenRouter")
    assert ai.message(ai.AIError("timeout"), o, "retouch") == "Ritocco AI non eseguito: OpenRouter non risponde (tempo scaduto)."
    assert "Anthropic" in ai.message(ai.AIError("not_found", "m"), a, "instructions")
    assert ai.message(ai.httpx.ConnectTimeout("t"), o, "light").startswith("OpenRouter non risponde")


def test_anthropic_typed_errors():
    import anthropic
    req = ai.httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    a = ai.provider_for("anthropic")
    err = anthropic.RateLimitError("r", response=ai.httpx.Response(429, request=req), body=None)
    assert a.to_error(err).kind == "rate"
    assert a.to_error(anthropic.APITimeoutError(request=req)).kind == "timeout"
    assert a.to_error(RuntimeError("x")).kind == "other"
