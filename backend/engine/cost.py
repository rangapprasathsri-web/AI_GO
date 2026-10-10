"""
Cost estimation and recording module.

Keeps estimated and actual costs strictly separate.
All costs are labelled with source and simulated status.
"""
from __future__ import annotations

from backend.engine.models import (
    CostEstimate,
    CostRecord,
    DataOrigin,
    DomainConfig,
    ExecutionResult,
    StrategyConfig,
    UserRequest,
)


def estimate_cost(
    strategy: StrategyConfig,
    request: UserRequest,
    config: DomainConfig,
) -> CostEstimate:
    """
    Estimate cost before execution.
    Uses the strategy's configured price_per_call.
    """
    return CostEstimate(
        strategy_name=strategy.name,
        estimated_cost=strategy.price_per_call,
        source=strategy.source,
        source_updated_at="2026-10-01",
        is_simulated=True,
        data_origin=DataOrigin.SIMULATED,
        breakdown={
            "base_price": strategy.price_per_call,
        },
    )


def record_cost(
    strategy: StrategyConfig,
    estimate: CostEstimate,
    execution: ExecutionResult,
    attempts: int = 1,
) -> CostRecord:
    """
    Record actual cost after execution.
    Includes cost of retries and failed attempts.
    """
    # Actual cost = price per call * number of attempts
    actual_cost = strategy.price_per_call * attempts
    origin = getattr(execution, "data_origin", DataOrigin.SIMULATED)

    return CostRecord(
        strategy_name=strategy.name,
        estimated_cost=estimate.estimated_cost,
        actual_cost=actual_cost,
        source=strategy.source,
        source_updated_at="2026-10-01",
        is_simulated=origin == DataOrigin.SIMULATED,
        data_origin=origin,
        attempts=attempts,
        includes_retries=attempts > 1,
        breakdown={
            "base_price": strategy.price_per_call,
            "attempts": attempts,
            "total": actual_cost,
        },
    )


def check_request_budget(
    estimated_cost: float,
    config: DomainConfig,
) -> tuple[bool, str]:
    """Check if a request's estimated cost is within the per-request budget."""
    max_cost = config.policy.budgets.per_request_max
    if estimated_cost > max_cost:
        return False, (
            f"Estimated cost ${estimated_cost:.2f} exceeds per-request maximum "
            f"of ${max_cost:.2f} (simulated)"
        )
    return True, ""


def check_school_budget(
    school_id: str,
    new_cost: float,
    current_spend: float,
    config: DomainConfig,
) -> tuple[bool, float, str]:
    """
    Check if a school's budget allows this request.
    Returns (allowed, remaining_budget, message).
    """
    monthly_max = config.policy.budgets.per_school_monthly
    remaining = monthly_max - current_spend
    new_total = current_spend + new_cost

    if new_total > monthly_max:
        return False, remaining, (
            f"School {school_id} budget: ${current_spend:.2f} of ${monthly_max:.2f} used. "
            f"This request (${new_cost:.2f}) would exceed the limit. (simulated)"
        )

    # Alert if over 80% of budget
    alert_msg = ""
    usage_pct = new_total / monthly_max * 100 if monthly_max > 0 else 100
    if usage_pct >= 80:
        alert_msg = (
            f"Budget alert: School {school_id} at {usage_pct:.0f}% of monthly budget "
            f"(${new_total:.2f} of ${monthly_max:.2f}) (simulated)"
        )

    return True, remaining - new_cost, alert_msg


def format_cost_comparison(
    chosen_cost: float,
    premium_cost: float,
    category: str,
    hide_currency: bool = False,
    effort_level_name: str = "Print-quality",
) -> str:
    """Format a cost comparison for requester transparency."""
    if premium_cost <= 0:
        return "No premium option available for comparison."

    ratio = premium_cost / chosen_cost if chosen_cost > 0 else float("inf")

    if ratio <= 1.1:
        if hide_currency:
            return f"This is already the highest tier ({effort_level_name})."
        return (
            f"This is already the highest tier. "
            f"Estimated cost: ${chosen_cost:.2f} (simulated)"
        )

    if hide_currency:
        return f"About 1/{ratio:.0f} of {effort_level_name}."

    return (
        f"Estimated cost: ${chosen_cost:.2f} — "
        f"about 1/{ratio:.0f} of Premium (${premium_cost:.2f}). "
        f"All costs are estimated and simulated."
    )
