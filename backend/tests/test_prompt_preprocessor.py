"""Tests for PromptPreprocessor and /api/prompt/preprocess endpoint."""
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.adapters.prompt_preprocessor import PromptPreprocessor

client = TestClient(app)


def test_preprocess_endpoint_success():
    res = client.post(
        "/api/prompt/preprocess",
        json={"prompt": "Cute puppy playing with yarn", "purpose": "coloring_sheet"}
    )
    assert res.status_code == 200
    data = res.json()
    assert "recommended_model" in data
    assert "recommended_tier" in data
    assert "explanation" in data
    assert "revised_prompt" in data
    assert isinstance(data.get("improvements"), list)
    assert len(data["improvements"]) > 0


def test_preprocess_empty_prompt_validation():
    res = client.post("/api/prompt/preprocess", json={"prompt": "   "})
    assert res.status_code == 400
    assert "Prompt cannot be empty" in res.json().get("detail", "")


def test_preprocess_offline_rule_fallback():
    p = PromptPreprocessor(primary_key="", fallback_key="", fallback_key_2="")
    res = p.preprocess("Lion for children to color", purpose="coloring_sheet")
    assert res["recommended_tier"] == "economy"
    assert "gemini-2.5-flash-image" in res["recommended_model"]
    assert "coloring" in res["revised_prompt"].lower()
    assert res["provider_used"] == "rule_based_fallback"

    res_poster = p.preprocess("Galaxy fine art print", purpose="professional_print_artwork")
    assert res_poster["recommended_tier"] == "maximum"
    assert "gemini-3-pro-image" in res_poster["recommended_model"]


def test_preprocess_failover_to_fallback():
    mock_fail = MagicMock(status_code=429, text="Rate limit exceeded")
    mock_ok = MagicMock(
        status_code=200,
        json=lambda: {
            "choices": [{
                "message": {
                    "content": '{"recommended_model": "gemini-2.5-flash-image", "recommended_tier": "economy", "model_display_name": "Gemini 2.5 Flash", "explanation": "Right-sized line art", "revised_prompt": "Clean outline art of tiger", "improvements": ["Outline contours"]}'
                }
            }]
        }
    )

    with patch("httpx.post", side_effect=[mock_fail, mock_ok]):
        p = PromptPreprocessor(primary_key="k1", fallback_key="k2", fallback_key_2="")
        res = p.preprocess("Tiger line art")
        assert res["provider_used"] == "groq (fallback_1)"
        assert res["recommended_tier"] == "economy"


def test_prompt_pii_sanitization():
    p = PromptPreprocessor(primary_key="", fallback_key="", fallback_key_2="")
    raw = "Poster of student: Jane Doe with email student@school.edu and phone 555-123-4567"
    res = p.preprocess(raw, purpose="professional_print_artwork")
    assert "student@school.edu" not in res["original_prompt"]
    assert "555-123-4567" not in res["original_prompt"]
    assert "[REDACTED_EMAIL]" in res["original_prompt"]
    assert "[REDACTED_PHONE]" in res["original_prompt"]
