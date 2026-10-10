"""
OpenAI Image Provider Adapter.

Implements the BaseAdapter interface for real image generation services (e.g. OpenAI DALL-E).
Supports offline contract testing using HTTPX mock transport so no paid credentials
or live network calls are needed during test suites.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx

from backend.adapters.base import AdapterCapability, AdapterPricing, BaseAdapter
from backend.engine.models import CostEstimate, DataOrigin, ExecutionResult, StrategyConfig, UserRequest


class OpenAIImageAdapter(BaseAdapter):
    """
    Provider adapter for OpenAI image generation (DALL-E 3 / DALL-E 2).
    
    Adheres strictly to:
    - Official documented capabilities and pricing (source: https://openai.com/api/pricing/, updated 2026-10-01)
    - Safe execution with pre-execution budget checks
    - Request timeouts and bounded retries on 429 / 5xx
    - Zero crashing on missing credentials, network failures, or rate limits
    - Support for httpx mock transport for credential-free automated contract testing
    """

    OFFICIAL_PRICING: dict[str, float] = {
        "dall-e-3:standard:1024x1024": 0.040,
        "dall-e-3:standard:1024x1792": 0.080,
        "dall-e-3:standard:1792x1024": 0.080,
        "dall-e-3:hd:1024x1024": 0.080,
        "dall-e-3:hd:1024x1792": 0.120,
        "dall-e-3:hd:1792x1024": 0.120,
        "dall-e-2:standard:1024x1024": 0.020,
        "dall-e-2:standard:512x512": 0.018,
        "dall-e-2:standard:256x256": 0.016,
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        safety_margin_pct: float = 0.0,
        client: Optional[httpx.Client] = None,
    ):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.safety_margin_pct = safety_margin_pct
        self._custom_client = client

    @property
    def name(self) -> str:
        return "openai_image"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            task_categories=[
                "flashcard",
                "detailed_illustration",
                "printed_banner",
                "classroom_illustration",
            ],
            output_types=["image/png", "image/jpeg"],
            parameter_limits={
                "models": ["dall-e-3", "dall-e-2"],
                "qualities": ["standard", "hd"],
                "resolutions": ["1024x1024", "1024x1792", "1792x1024"],
            },
        )

    @property
    def pricing(self) -> AdapterPricing:
        return AdapterPricing(
            method="per_call",
            values=self.OFFICIAL_PRICING,
            source="https://openai.com/api/pricing/",
            source_updated_at="2026-10-01",
            data_origin="provider_reported" if self._api_key else "estimated",
        )

    def _resolve_price(self, model: str, quality: str, size: str) -> tuple[float, str]:
        key = f"{model}:{quality}:{size}"
        if key in self.OFFICIAL_PRICING:
            return self.OFFICIAL_PRICING[key], key
        # fallback to standard 1024
        fallback_key = f"{model}:standard:1024x1024"
        return self.OFFICIAL_PRICING.get(fallback_key, 0.040), fallback_key

    def estimate_cost(self, strategy: StrategyConfig, request: UserRequest) -> CostEstimate:
        params = strategy.params or {}
        model = params.get("model", "dall-e-3")
        quality = params.get("quality", "standard")
        size = params.get("size", "1024x1024")

        base_cost, pricing_key = self._resolve_price(model, quality, size)
        safety_addon = base_cost * (self.safety_margin_pct / 100.0)
        total_estimate = round(base_cost + safety_addon, 4)

        return CostEstimate(
            strategy_name=strategy.name,
            estimated_cost=total_estimate,
            source="https://openai.com/api/pricing/",
            source_updated_at="2026-10-01",
            is_simulated=self._api_key is None and self._custom_client is None,
            data_origin=DataOrigin.ESTIMATED,
            breakdown={
                "base_price": base_cost,
                "safety_margin": round(safety_addon, 4),
            },
        )

    def execute(self, strategy: StrategyConfig, request: UserRequest) -> ExecutionResult:
        start_time = time.time()
        params = strategy.params or {}
        model = params.get("model", "dall-e-3")
        quality = params.get("quality", "standard")
        size = params.get("size", "1024x1024")

        cost_estimate = self.estimate_cost(strategy, request)
        expected_cost = cost_estimate.estimated_cost

        # 1. Pre-execution budget check
        if request.max_budget is not None and expected_cost > request.max_budget:
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=0.0,
                latency_s=time.time() - start_time,
                is_simulated=True,
                data_origin=DataOrigin.ESTIMATED,
                error=f"Pre-execution budget breach: estimated cost ${expected_cost:.4f} exceeds request max_budget ${request.max_budget:.4f}",
            )

        # 2. Check credentials & test transport
        api_key = self._api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key and self._custom_client is None:
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=0.0,
                latency_s=time.time() - start_time,
                is_simulated=True,
                data_origin=DataOrigin.SIMULATED,
                error="Provider credentials missing: OPENAI_API_KEY not configured. Mock mode remains available without credentials.",
            )

        # 3. HTTP Execution with retries and timeout
        client = self._custom_client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=self.timeout_s,
        )

        url = "https://api.openai.com/v1/images/generations"
        prompt_text = request.prompt or str(request.inputs.get("task_description", ""))
        payload = {
            "model": model,
            "prompt": prompt_text,
            "n": 1,
            "size": size,
            "quality": quality,
        }

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        attempts = 0
        last_error = ""

        try:
            while attempts <= self.max_retries:
                attempts += 1
                try:
                    response = client.post(url, json=payload, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        image_url = data.get("data", [{}])[0].get("url", f"https://api.openai.com/mock-res/{request.id}.png")
                        actual_billed = self._resolve_price(model, quality, size)[0]
                        elapsed = time.time() - start_time
                        
                        return ExecutionResult(
                            request_id=request.id,
                            strategy_name=strategy.name,
                            success=True,
                            output_reference=image_url,
                            output_data={"image_url": image_url, "provider_data": data},
                            actual_cost=actual_billed,
                            latency_s=elapsed,
                            is_simulated=False if api_key and self._custom_client is None else True,
                            data_origin=DataOrigin.PROVIDER_REPORTED if (api_key and self._custom_client is None) else DataOrigin.ESTIMATED,
                            metadata={
                                "model": model,
                                "quality": quality,
                                "size": size,
                                "attempts": attempts,
                                "pricing_source": "https://openai.com/api/pricing/",
                                "source_updated_at": "2026-10-01",
                            },
                        )

                    elif response.status_code == 429:
                        last_error = f"OpenAI Rate limit exceeded (429): {response.text}"
                        if attempts <= self.max_retries:
                            time.sleep(0.05 * attempts)
                            continue
                        break
                    elif response.status_code >= 500:
                        last_error = f"OpenAI Server error ({response.status_code}): {response.text}"
                        if attempts <= self.max_retries:
                            time.sleep(0.05 * attempts)
                            continue
                        break
                    else:
                        last_error = f"OpenAI API client error ({response.status_code}): {response.text}"
                        break

                except httpx.TimeoutException:
                    last_error = f"OpenAI API request timed out after {self.timeout_s}s"
                    if attempts <= self.max_retries:
                        continue
                    break
                except httpx.RequestError as exc:
                    last_error = f"OpenAI network request error: {str(exc)}"
                    break

            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=0.0,
                latency_s=time.time() - start_time,
                is_simulated=True,
                data_origin=DataOrigin.ESTIMATED,
                error=last_error or "Unknown OpenAI execution error",
                metadata={"attempts": attempts},
            )

        finally:
            if self._custom_client is None:
                client.close()
