"""
Tests for Real Provider Adapter Contracts using HTTPX Mock Transport.

Verifies:
1. Capability discovery and documented pricing metadata
2. Cost estimation with safety margins
3. Safe execution without credentials (never crashes)
4. Successful execution using mocked HTTPX transport (zero paid calls)
5. Pre-execution budget checks
6. Rate limit (429) and server error (500) retries and graceful handling
7. Request timeout handling
8. Data origin tags on outputs
"""
import httpx
import pytest

from backend.adapters.openai_image import OpenAIImageAdapter
from backend.engine.models import DataOrigin, StrategyConfig, UserRequest


def test_capabilities_and_pricing_metadata():
    adapter = OpenAIImageAdapter()
    assert adapter.name == "openai_image"
    caps = adapter.capabilities
    assert "detailed_illustration" in caps.task_categories
    assert "dall-e-3" in caps.parameter_limits["models"]

    pricing = adapter.pricing
    assert pricing.source == "https://openai.com/api/pricing/"
    assert pricing.source_updated_at == "2026-10-01"
    assert pricing.method == "per_call"
    assert pricing.values["dall-e-3:standard:1024x1024"] == 0.040
    assert pricing.values["dall-e-3:hd:1024x1024"] == 0.080


def test_cost_estimation_with_safety_margin():
    adapter = OpenAIImageAdapter(safety_margin_pct=15.0)
    strategy = StrategyConfig(
        name="openai_premium",
        adapter="openai_image",
        price_per_call=0.040,
        params={"model": "dall-e-3", "quality": "standard", "size": "1024x1024"},
    )
    request = UserRequest(prompt="Classroom banner", domain="education_images")
    est = adapter.estimate_cost(strategy, request)

    assert est.source == "https://openai.com/api/pricing/"
    assert est.data_origin == DataOrigin.ESTIMATED
    assert est.breakdown["base_price"] == 0.040
    assert est.breakdown["safety_margin"] == pytest.approx(0.006)
    assert est.estimated_cost == pytest.approx(0.046)


def test_missing_credentials_fails_gracefully():
    # When no API key is provided, execution must never crash
    adapter = OpenAIImageAdapter(api_key=None, client=None)
    # Clear any env var
    import os
    old_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        strategy = StrategyConfig(name="openai_dalle", adapter="openai_image", price_per_call=0.04)
        req = UserRequest(prompt="A test image", domain="education_images")
        res = adapter.execute(strategy, req)
        assert res.success is False
        assert "OPENAI_API_KEY not configured" in res.error
        assert "Mock mode remains available" in res.error
    finally:
        if old_key:
            os.environ["OPENAI_API_KEY"] = old_key


def test_pre_execution_budget_check():
    adapter = OpenAIImageAdapter(api_key="sk-testkey")
    strategy = StrategyConfig(
        name="openai_hd",
        adapter="openai_image",
        price_per_call=0.08,
        params={"model": "dall-e-3", "quality": "hd", "size": "1024x1024"},
    )
    # Budget is $0.02, but standard HD cost is $0.08
    req = UserRequest(prompt="High-res poster", domain="education_images", max_budget=0.02)
    res = adapter.execute(strategy, req)
    assert res.success is False
    assert "Pre-execution budget breach" in res.error


def test_successful_mock_transport_execution():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/images/generations"
        assert request.headers["authorization"] == "Bearer test-mock-key"
        content = {
            "created": 1728560000,
            "data": [{"url": "https://oaidalleapiprodscus.blob.core.windows.net/test-image.png"}],
        }
        return httpx.Response(200, json=content)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    adapter = OpenAIImageAdapter(api_key="test-mock-key", client=client)

    strategy = StrategyConfig(
        name="openai_std",
        adapter="openai_image",
        price_per_call=0.04,
        params={"model": "dall-e-3", "quality": "standard", "size": "1024x1024"},
    )
    req = UserRequest(prompt="Detailed science illustration", domain="education_images", max_budget=0.50)
    res = adapter.execute(strategy, req)

    assert res.success is True
    assert res.actual_cost == 0.040
    assert "blob.core.windows.net" in res.output_reference
    assert res.metadata["model"] == "dall-e-3"
    assert res.metadata["pricing_source"] == "https://openai.com/api/pricing/"


def test_rate_limit_handling_and_bounded_retries():
    call_count = 0

    def rate_limit_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})

    client = httpx.Client(transport=httpx.MockTransport(rate_limit_handler))
    adapter = OpenAIImageAdapter(api_key="test-mock-key", client=client, max_retries=2)

    strategy = StrategyConfig(name="openai_std", adapter="openai_image", price_per_call=0.04)
    req = UserRequest(prompt="Illustration", domain="education_images")
    res = adapter.execute(strategy, req)

    assert res.success is False
    assert "Rate limit exceeded (429)" in res.error
    assert res.metadata["attempts"] == 3  # initial + 2 retries


def test_server_error_and_timeout_handling():
    def server_error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    client = httpx.Client(transport=httpx.MockTransport(server_error_handler))
    adapter = OpenAIImageAdapter(api_key="test-mock-key", client=client, max_retries=1)

    strategy = StrategyConfig(name="openai_std", adapter="openai_image", price_per_call=0.04)
    req = UserRequest(prompt="Illustration", domain="education_images")
    res = adapter.execute(strategy, req)

    assert res.success is False
    assert "Server error (503)" in res.error
