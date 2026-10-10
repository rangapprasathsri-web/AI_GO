"""
Mock text summarisation adapter.

Deterministic mock for the text summarisation domain (P1).
Simulates small, medium, and large model tiers.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from backend.adapters.base import AdapterCapability, AdapterPricing, BaseAdapter
from backend.engine.models import CostEstimate, ExecutionResult, StrategyConfig, UserRequest


class MockTextAdapter(BaseAdapter):
    """
    Mock text summarisation provider with three model tiers.
    Generates deterministic text output based on request ID.
    """

    def __init__(self, fail_request_ids: set[str] | None = None):
        self._fail_request_ids = fail_request_ids or set()

    @property
    def name(self) -> str:
        return "mock_text"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            task_categories=[
                "brief_summary",
                "detailed_summary",
                "executive_report",
            ],
            output_types=["text/plain"],
            parameter_limits={
                "max_tokens": {"min": 50, "max": 4000},
                "model_tier": {"options": ["small", "medium", "large"]},
            },
        )

    @property
    def pricing(self) -> AdapterPricing:
        return AdapterPricing(
            method="per_call",
            values={
                "small_model": 0.005,
                "medium_model": 0.02,
                "large_model": 0.08,
            },
            source="placeholder",
        )

    def estimate_cost(self, strategy: StrategyConfig, request: UserRequest) -> CostEstimate:
        return CostEstimate(
            strategy_name=strategy.name,
            estimated_cost=strategy.price_per_call,
            source="placeholder",
            is_simulated=True,
            breakdown={"base_price": strategy.price_per_call},
        )

    def execute(self, strategy: StrategyConfig, request: UserRequest) -> ExecutionResult:
        start_time = time.time()

        if request.id in self._fail_request_ids:
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=strategy.price_per_call,
                latency_s=0.1,
                is_simulated=True,
                error="Simulated provider error: model unavailable",
            )

        try:
            max_tokens = strategy.params.get("max_tokens", 100)
            model_tier = strategy.params.get("model_tier", "small")

            # Generate deterministic text
            seed = int(hashlib.md5(request.id.encode()).hexdigest()[:8], 16)
            text = self._generate_text(
                max_tokens=max_tokens,
                model_tier=model_tier,
                seed=seed,
                prompt=request.prompt,
            )

            simulated_latency = strategy.latency_s

            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=True,
                output_reference=f"mock://text/{request.id}",
                output_data={"text": text},
                actual_cost=strategy.price_per_call,
                latency_s=simulated_latency,
                is_simulated=True,
                metadata={
                    "model_tier": model_tier,
                    "max_tokens": max_tokens,
                    "actual_words": len(text.split()),
                    "simulated_latency_s": simulated_latency,
                },
            )

        except Exception as e:
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=strategy.price_per_call,
                latency_s=time.time() - start_time,
                is_simulated=True,
                error=f"Mock text adapter error: {str(e)}",
            )

    def _generate_text(
        self,
        max_tokens: int,
        model_tier: str,
        seed: int,
        prompt: str,
    ) -> str:
        """Generate deterministic mock text output."""
        # Word pool for summary generation
        words = [
            "the", "analysis", "shows", "that", "key", "findings", "indicate",
            "a", "significant", "trend", "in", "data", "performance", "metrics",
            "demonstrate", "improvement", "across", "several", "categories",
            "based", "on", "this", "evaluation", "we", "recommend", "further",
            "investigation", "into", "the", "primary", "factors", "driving",
            "these", "results", "which", "suggest", "an", "opportunity", "for",
            "optimization", "and", "enhanced", "efficiency", "throughout",
            "the", "organization", "including", "various", "departments",
            "stakeholders", "have", "noted", "considerable", "progress",
            "in", "implementing", "recommended", "strategies", "the", "overall",
            "impact", "has", "been", "positive", "with", "measurable", "outcomes",
        ]

        # Generate word count based on tier
        tier_multiplier = {"small": 0.3, "medium": 0.6, "large": 1.0}
        multiplier = tier_multiplier.get(model_tier, 0.5)
        target_words = max(10, int(max_tokens * multiplier * 0.75))

        # Use seed for determinism
        import random
        rng = random.Random(seed)
        text_words = []
        for i in range(target_words):
            text_words.append(words[rng.randint(0, len(words) - 1)])

        # Add some structure
        text = " ".join(text_words)

        # Capitalise first word and add period at end
        if text:
            text = text[0].upper() + text[1:]
            if not text.endswith("."):
                text += "."

        return text
