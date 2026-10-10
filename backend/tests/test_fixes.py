"""Tests verifying security fixes, bug fixes, and route aliases."""
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from backend.api.main import app, ACTIVE_IMAGE_ADAPTER
from backend.adapters.live_image_adapter import LiveImageAdapter
from backend.engine.models import StrategyConfig, UserRequest

client = TestClient(app)


def test_export_csv_route_returns_csv():
    client.post("/api/generate", json={"prompt": "tree", "purpose": "coloring_sheet", "confirmed_tier": "economy"})
    res = client.get("/api/history/export")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]


def test_admin_requires_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    assert client.put("/api/config", json={"updates": {}, "author": "a"}).status_code == 401
    assert client.put("/api/config?role=admin", json={"updates": {}, "author": "a"}).status_code == 401
    assert client.post("/api/config/rollback", json={"author": "a"}).status_code == 401
    h = {"X-Admin-Token": "secret"}
    assert client.put("/api/config", json={"updates": {}, "author": "a"}, headers=h).status_code == 200
    assert client.post("/api/config/rollback", json={"author": "a"}, headers=h).status_code == 200


def test_gemini_key_not_in_url():
    adapter = LiveImageAdapter(gemini_api_key="gem-secret-key-xyz")
    strat = StrategyConfig(name="economy", adapter="mock_image", price_per_call=0.01)
    b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    mock = MagicMock(status_code=200, json=lambda: {"candidates": [{"content": {"parts": [{"inlineData": {"data": b64}}]}}]})
    with patch("httpx.post", return_value=mock) as mock_post:
        adapter.execute(strat, UserRequest(prompt="tiger", domain="d", inputs={}))
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        assert "key=" not in url
        assert kwargs["headers"].get("x-goog-api-key") == "gem-secret-key-xyz"


def test_cors_not_wildcard():
    res = client.options("/api/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in res.headers


def test_error_response_has_no_secret():
    key = "secret_test_gemini_key_999"
    adapter = LiveImageAdapter(gemini_api_key=key, enable_live_diffusion=False)
    strat = StrategyConfig(name="economy", adapter="mock_image", price_per_call=0.01)
    with patch("httpx.post", side_effect=Exception(f"Error {key}")), patch("time.sleep"):
        res = adapter.execute(strat, UserRequest(prompt="x", domain="d", inputs={}))
        assert key not in str(res.metadata) and key not in (res.error or "")
    with patch.object(ACTIVE_IMAGE_ADAPTER, "execute", side_effect=RuntimeError(f"crash {key}")):
        c = TestClient(app, raise_server_exceptions=False)
        assert key not in c.post("/api/generate", json={"prompt": "c", "purpose": "coloring_sheet", "confirmed_tier": "economy"}).text


def test_legacy_paths_match_api_paths():
    r1 = client.get("/health")
    r2 = client.get("/api/health")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()
