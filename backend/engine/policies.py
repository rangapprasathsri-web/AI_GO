"""
Decision policies for the engine.

Each policy implements the same interface: given a list of candidate strategies
and context, return them ranked with explanations.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.engine.models import (
    DomainConfig,
    PolicyName,
    QualityFloor,
    StrategyConfig,
    UserRequest,
)


class PolicyInterface(ABC):
    """Abstract interface for a decision policy."""

    @abstractmethod
    def rank_strategies(
        self,
        candidates: list[StrategyConfig],
        quality_floor: QualityFloor,
        request: UserRequest,
        config: DomainConfig,
    ) -> list[tuple[StrategyConfig, str]]:
        """
        Rank candidate strategies.
        Returns list of (strategy, reason) tuples, best first.
        """
        ...


class BaselineAlwaysMaxPolicy(PolicyInterface):
    """Always picks the most expensive strategy. Used as comparison baseline."""

    def rank_strategies(
        self,
        candidates: list[StrategyConfig],
        quality_floor: QualityFloor,
        request: UserRequest,
        config: DomainConfig,
    ) -> list[tuple[StrategyConfig, str]]:
        sorted_candidates = sorted(
            candidates,
            key=lambda s: (-s.price_per_call, -s.latency_s, s.name),
        )
        return [
            (s, "Baseline policy: always use highest tier")
            for s in sorted_candidates
        ]


class RuleBasedPolicy(PolicyInterface):
    """Maps category default_tier_hint to a strategy tier."""

    def rank_strategies(
        self,
        candidates: list[StrategyConfig],
        quality_floor: QualityFloor,
        request: UserRequest,
        config: DomainConfig,
    ) -> list[tuple[StrategyConfig, str]]:
        # Get the category's default tier hint
        category_name = request.inputs.get("_category", "")
        category = config.task_categories.get(category_name)
        tier_hint = category.default_tier_hint if category else None

        # Map tier hints to strategy ordering preferences
        tier_order = {"low": 0, "medium": 1, "high": 2}

        if tier_hint and tier_hint in tier_order:
            target_level = tier_order[tier_hint]
            # Sort strategies by distance from target tier level
            strategy_tiers = _assign_tier_levels(candidates)
            sorted_candidates = sorted(
                candidates,
                key=lambda s: (
                    abs(strategy_tiers.get(s.name, 1) - target_level),
                    s.price_per_call,
                    s.latency_s,
                    s.name,
                ),
            )
        else:
            # No hint: sort by price ascending (cheapest first)
            sorted_candidates = sorted(
                candidates,
                key=lambda s: (s.price_per_call, s.latency_s, s.name),
            )

        return [
            (s, f"Rule-based: tier hint '{tier_hint or 'none'}' for category '{category_name}'")
            for s in sorted_candidates
        ]


class CheapestMeetingQualityPolicy(PolicyInterface):
    """Picks the cheapest strategy that meets the quality floor."""

    def rank_strategies(
        self,
        candidates: list[StrategyConfig],
        quality_floor: QualityFloor,
        request: UserRequest,
        config: DomainConfig,
    ) -> list[tuple[StrategyConfig, str]]:
        # Deterministic tie-break: lower cost, then lower latency, then name
        sorted_candidates = sorted(
            candidates,
            key=lambda s: (s.price_per_call, s.latency_s, s.name),
        )
        return [
            (s, f"Cheapest meeting quality: ${s.price_per_call:.2f} (estimated, simulated)")
            for s in sorted_candidates
        ]


class WeightedPolicy(PolicyInterface):
    """Configurable weights for cost, quality, and latency."""

    def rank_strategies(
        self,
        candidates: list[StrategyConfig],
        quality_floor: QualityFloor,
        request: UserRequest,
        config: DomainConfig,
    ) -> list[tuple[StrategyConfig, str]]:
        weights = config.policy.weights or {"cost": 0.5, "quality": 0.3, "latency": 0.2}

        # Normalise weights
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        # Find ranges for normalisation
        costs = [s.price_per_call for s in candidates]
        latencies = [s.latency_s for s in candidates]

        cost_range = max(costs) - min(costs) if len(costs) > 1 else 1.0
        latency_range = max(latencies) - min(latencies) if len(latencies) > 1 else 1.0

        def score(s: StrategyConfig) -> float:
            # Lower cost is better (invert)
            cost_score = 1.0 - ((s.price_per_call - min(costs)) / cost_range if cost_range > 0 else 0)
            # Higher quality proxy (resolution) is better
            resolution = s.params.get("resolution", s.params.get("max_tokens", 1000))
            quality_score = resolution / max(sp.params.get("resolution", sp.params.get("max_tokens", 1000)) for sp in candidates) if candidates else 0.5
            # Lower latency is better (invert)
            lat_score = 1.0 - ((s.latency_s - min(latencies)) / latency_range if latency_range > 0 else 0)

            return (
                weights.get("cost", 0.33) * cost_score
                + weights.get("quality", 0.33) * quality_score
                + weights.get("latency", 0.33) * lat_score
            )

        scored = [(s, score(s)) for s in candidates]
        # Deterministic tie-break
        scored.sort(key=lambda x: (-x[1], x[0].price_per_call, x[0].latency_s, x[0].name))

        return [
            (s, f"Weighted score: {sc:.3f} (cost={weights.get('cost', 0):.2f}, quality={weights.get('quality', 0):.2f}, latency={weights.get('latency', 0):.2f})")
            for s, sc in scored
        ]


class UserSelectedPolicy(PolicyInterface):
    """User picks; engine still enforces hard constraints."""

    def rank_strategies(
        self,
        candidates: list[StrategyConfig],
        quality_floor: QualityFloor,
        request: UserRequest,
        config: DomainConfig,
    ) -> list[tuple[StrategyConfig, str]]:
        preferred = request.preferred_strategy
        result = []
        for s in candidates:
            if s.name == preferred:
                result.insert(0, (s, f"User selected: '{preferred}'"))
            else:
                result.append((s, f"Alternative to user's selection of '{preferred}'"))

        if not result:
            # Fallback: sort by price
            sorted_candidates = sorted(
                candidates,
                key=lambda s: (s.price_per_call, s.latency_s, s.name),
            )
            result = [
                (s, "User's preferred strategy not available; alternatives listed")
                for s in sorted_candidates
            ]

        return result


class ManualReviewPolicy(PolicyInterface):
    """Flags for manual review when no strategy passes or analysis is uncertain."""

    def rank_strategies(
        self,
        candidates: list[StrategyConfig],
        quality_floor: QualityFloor,
        request: UserRequest,
        config: DomainConfig,
    ) -> list[tuple[StrategyConfig, str]]:
        sorted_candidates = sorted(
            candidates,
            key=lambda s: (s.price_per_call, s.latency_s, s.name),
        )
        return [
            (s, "Requires manual review before execution")
            for s in sorted_candidates
        ]


def _assign_tier_levels(strategies: list[StrategyConfig]) -> dict[str, int]:
    """Assign tier levels (0=low, 1=mid, 2=high) based on price ordering."""
    sorted_by_price = sorted(strategies, key=lambda s: s.price_per_call)
    n = len(sorted_by_price)
    tiers = {}
    for i, s in enumerate(sorted_by_price):
        if n <= 1:
            tiers[s.name] = 1
        elif n == 2:
            tiers[s.name] = 0 if i == 0 else 2
        else:
            tiers[s.name] = round(i / (n - 1) * 2)
    return tiers


# Policy registry
POLICY_REGISTRY: dict[PolicyName, type[PolicyInterface]] = {
    PolicyName.BASELINE_ALWAYS_MAX: BaselineAlwaysMaxPolicy,
    PolicyName.RULE_BASED: RuleBasedPolicy,
    PolicyName.CHEAPEST_MEETING_QUALITY: CheapestMeetingQualityPolicy,
    PolicyName.WEIGHTED: WeightedPolicy,
    PolicyName.USER_SELECTED: UserSelectedPolicy,
    PolicyName.MANUAL_REVIEW: ManualReviewPolicy,
}


def get_policy(name: PolicyName) -> PolicyInterface:
    """Get a policy instance by name."""
    cls = POLICY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown policy: {name}")
    return cls()
