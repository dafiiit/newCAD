"""Several BuilderBot model profiles, switching between them, keys kept out of the settings file."""
import json
import logging

import httpx
from fastapi.testclient import TestClient

from newcad_engine.agent import adapters
from newcad_engine.api.app import create_app
from newcad_engine.config import Config
from newcad_engine.core import Engine

logging.getLogger("httpx").setLevel(logging.WARNING)
H = {"Authorization": "Bearer tok"}


def test_old_settings_become_first_profile(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"provider": "openai-compatible", "model": "gemma-4-e4b-it", "base_url": "http://127.0.0.1:1234/v1"}))
    eng = Engine(Config(home=tmp_path, token="tok", workers=1))
    st = eng.settings
    assert eng.cfg.settings_file == tmp_path / "settings.json"
    assert [p["name"] for p in st.data["profiles"]] == ["LM Studio"]
    assert st.active()["model"] == "gemma-4-e4b-it"


def test_profiles_switch_and_keys(tmp_path):
    eng = Engine(Config(home=tmp_path, token="tok", workers=1))
    with TestClient(create_app(eng)) as c:
        c.put("/api/settings", json={"provider": "openai-compatible", "model": "gemma", "base_url": "http://127.0.0.1:1234/v1"}, headers=H)
        first = c.get("/api/settings", headers=H).json()["active_profile"]
        s = c.post("/api/settings/profiles", json={"name": "Strata", "provider": "openai-compatible", "base_url": "http://100.64.0.1:8095/v1",
                                                   "model": "big", "activate": True}, headers=H).json()
        assert s["active_profile"] == "strata" and s["model"] == "big" and s["base_url"].endswith(":8095/v1")
        assert [p["id"] for p in s["profiles"]] == [first, "strata"]
        r = c.post("/api/settings/profiles/strata/key", json={"key": "sk-secret"}, headers=H).json()
        assert r["key_saved"] == "memory"  # keychain is off in tests
        assert next(p for p in r["profiles"] if p["id"] == "strata")["has_key"]
        assert eng.settings.keys()["openai-compatible"] == "sk-secret"
        # the key never reaches the settings file or the settings API
        assert "sk-secret" not in eng.cfg.settings_file.read_text()
        assert "sk-secret" not in json.dumps(c.get("/api/settings", headers=H).json())
        # editing the active model edits the active profile only
        c.put("/api/settings", json={"model": "bigger"}, headers=H)
        s = c.put("/api/settings", json={"active_profile": first}, headers=H).json()
        assert s["model"] == "gemma" and "openai-compatible" not in eng.settings.keys()
        assert next(p for p in s["profiles"] if p["id"] == "strata")["model"] == "bigger"
        assert c.put("/api/settings", json={"active_profile": "nope"}, headers=H).status_code >= 400
        # delete; the last one stays
        s = c.delete("/api/settings/profiles/strata", headers=H).json()
        assert [p["id"] for p in s["profiles"]] == [first]
        assert c.delete(f"/api/settings/profiles/{first}", headers=H).status_code == 400
    # survives a restart
    eng2 = Engine(Config(home=tmp_path, token="tok", workers=1))
    assert eng2.settings.active()["id"] == first and eng2.settings.data["model"] == "gemma"


def test_auth_header_styles():
    from newcad_engine.agent.adapters.anthropic_adapter import AnthropicConversation
    from newcad_engine.agent.adapters.openai_adapter import OpenAIConversation

    o = OpenAIConversation("s", [], "m", {"base_url": "http://x/v1", "api_key": "k", "auth": "x-api-key"})
    assert o.client.default_headers.get("x-api-key") == "k"
    a = AnthropicConversation("s", [], "m", {"base_url": "http://x", "api_key": "k", "auth": "bearer"})
    assert a.client.auth_token == "k"
    assert adapters.resolve({"provider": "anthropic", "base_url": "http://x"}, {"anthropic": "k"})["ready"]


def test_list_models(tmp_path, monkeypatch):
    eng = Engine(Config(home=tmp_path, token="tok", workers=1))
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization")
        if not seen["auth"]:
            return httpx.Response(401, json={"error": "missing key"})
        return httpx.Response(200, json={"data": [{"id": "qwen3-coder"}, {"id": "gemma"}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with TestClient(create_app(eng)) as c:
        c.post("/api/settings/profiles", json={"name": "Remote", "provider": "openai-compatible", "base_url": "http://nas:8095/v1"}, headers=H)
        assert "needs an API key" in c.get("/api/settings/profiles/remote/models", headers=H).json()["error"]
        c.post("/api/settings/profiles/remote/key", json={"key": "abc"}, headers=H)
        assert c.get("/api/settings/profiles/remote/models", headers=H).json()["models"] == ["qwen3-coder", "gemma"]
        assert seen["auth"] == "Bearer abc"
