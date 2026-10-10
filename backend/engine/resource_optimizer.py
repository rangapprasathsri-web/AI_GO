"""
Resource Optimizer Engine Service.

Implements tier selection logic, dynamic floor raising, plain-language explanations,
override handling, and budget enforcement according to the official problem statement.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from backend.engine.config import DomainConfig
from backend.engine.models import DataOrigin
from backend.engine.resource import ResourceEstimator, compute_tier_units

logger = logging.getLogger("resource_optimizer")

TIER_ORDER = ["economy", "standard", "maximum"]


def _tier_rank(tier_name: str) -> int:
    try:
        return TIER_ORDER.index(tier_name.lower())
    except ValueError:
        return 0


class ResourceOptimizerService:
    """
    Tier selection and recommendation engine matching image purpose
    to computational effort while enforcing budgets and transparent math.
    """

    def __init__(self, config: DomainConfig):
        self.config = config
        self.tiers = config.tiers or {
            "economy": {"display": "Economy", "params": {"width": 768, "height": 768, "steps": 20}, "model_factor": 1.0},
            "standard": {"display": "Standard", "params": {"width": 1024, "height": 1024, "steps": 30}, "model_factor": 1.0},
            "maximum": {"display": "Maximum", "params": {"width": 1536, "height": 1536, "steps": 50}, "model_factor": 1.0},
        }
        self.purposes = config.purposes or {}
        self.energy_model = config.energy_model or {"enabled": False, "source": None}
        self.estimator = ResourceEstimator(self.tiers, self.energy_model)

    def recommend(
        self,
        prompt: str,
        purpose: str,
        print_use: bool = False,
        print_size: Optional[str] = None,
        required_detail: Optional[str] = None,
        target_resolution: Optional[int] = None,
        budget_units: Optional[float] = None,
        latency_max_s: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Recommend lowest suitable tier meeting requirements.
        """
        purpose_key = purpose.lower().replace(" ", "_") if purpose else "coloring_sheet"
        purpose_cfg = self.purposes.get(purpose_key, {})

        # 1. Base floor from purpose config
        base_floor = purpose_cfg.get("min_tier", "economy").lower()
        if base_floor not in self.tiers:
            base_floor = "economy"

        current_tier = base_floor
        deciding_factor = "purpose_floor"
        raised_reason = None

        # 2. Dynamic floor raising checks
        # A. Large print size or print use flag
        is_large_print = False
        if print_size:
            ps = print_size.strip().upper()
            if ps in ["A1", "A0", "BANNER", "POSTER", "BILLBOARD", "LARGE"]:
                is_large_print = True
                if _tier_rank(current_tier) < _tier_rank("standard"):
                    current_tier = "standard"
                    deciding_factor = f"large print size ({print_size})"
                    raised_reason = f"raised to Standard due to large print size ({print_size})"
            elif ps in ["A2", "A3"]:
                if _tier_rank(current_tier) < _tier_rank("standard"):
                    current_tier = "standard"
                    deciding_factor = f"print size ({print_size})"
                    raised_reason = f"raised to Standard due to print size ({print_size})"

        if print_use and not is_large_print:
            if _tier_rank(current_tier) < _tier_rank("standard"):
                current_tier = "standard"
                deciding_factor = "print_use"
                raised_reason = "raised to Standard due to print use flag"

        if target_resolution:
            if target_resolution >= 1500 and _tier_rank(current_tier) < _tier_rank("maximum"):
                current_tier = "maximum"
                deciding_factor = f"target resolution ({target_resolution}px)"
                raised_reason = f"raised to Maximum due to target resolution ({target_resolution}px)"
            elif target_resolution >= 1000 and _tier_rank(current_tier) < _tier_rank("standard"):
                current_tier = "standard"
                deciding_factor = f"target resolution ({target_resolution}px)"
                raised_reason = f"raised to Standard due to target resolution ({target_resolution}px)"

        # B. Required detail
        if required_detail:
            rd = required_detail.lower().strip()
            if rd in ["very_high", "maximum", "fine"] and _tier_rank(current_tier) < _tier_rank("maximum"):
                current_tier = "maximum"
                deciding_factor = f"required detail ({rd})"
                raised_reason = f"raised to Maximum due to {rd} detail requirement"
            elif rd in ["high"] and _tier_rank(current_tier) < _tier_rank("standard"):
                current_tier = "standard"
                deciding_factor = f"required detail ({rd})"
                raised_reason = f"raised to Standard due to high detail requirement"

        # C. Custom purpose uncertainty handling
        if purpose_key == "custom":
            has_explicit = bool(required_detail or target_resolution or print_use or print_size)
            if not has_explicit:
                uncertain_default = purpose_cfg.get("on_uncertain", "standard")
                current_tier = uncertain_default
                deciding_factor = "custom_uncertainty_default"
                raised_reason = f"conservative default ({uncertain_default.title()}) for unspecified custom requirements"

        # 3. Plain language explanation
        purpose_label = purpose_cfg.get("label", purpose.replace("_", " ").title())
        tier_display = self.tiers.get(current_tier, {}).get("display", current_tier.title())
        tier_params = self.tiers.get(current_tier, {}).get("params", {})
        param_desc = f"{tier_params.get('width', 1024)}x{tier_params.get('height', 1024)}, {tier_params.get('steps', 30)} steps"

        if raised_reason:
            explanation = f"{purpose_label} base floor was {raised_reason}."
        else:
            explanation = f"{purpose_label}: {tier_display} tier ({param_desc}) satisfies the quality floor with minimal compute."

        # 4. Budget check
        per_request_max = (
            budget_units
            if budget_units is not None
            else (self.config.policy.budgets.per_request_units_max or 120.0)
        )
        tier_units = self.estimator.calculate_units_for_tier(current_tier)

        status = "recommended"
        if tier_units > per_request_max:
            status = "blocked_by_budget"
            explanation = (
                f"Recommended tier ({tier_display}, {tier_units} units) exceeds hard budget limit of "
                f"{per_request_max} units. Please adjust requirements or request budget expansion."
            )

        # 5. Build estimates and alternatives
        selected_estimate = self.estimator.estimate(current_tier)

        alternatives = []
        for t_name in TIER_ORDER:
            if t_name in self.tiers:
                alt_est = self.estimator.estimate(t_name)
                alt_est["is_recommended"] = (t_name == current_tier)
                alt_est["is_below_floor"] = (_tier_rank(t_name) < _tier_rank(base_floor))
                alternatives.append(alt_est)

        return {
            "recommended_tier": current_tier,
            "status": status,
            "deciding_factor": deciding_factor,
            "explanation": explanation,
            "purpose": purpose_key,
            "purpose_label": purpose_label,
            "base_floor_tier": base_floor,
            "budget_units": per_request_max,
            "selected_estimate": selected_estimate,
            "alternatives": alternatives,
        }

    def validate_override(
        self,
        recommended_tier: str,
        override_tier: str,
        purpose: str,
        override_confirmed: bool = False,
        budget_units: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Validate a user override choice.
        Returns: { allowed: bool, status: str, warning: Optional[str] }
        """
        rec = recommended_tier.lower()
        ovr = override_tier.lower()

        if ovr not in self.tiers:
            return {"allowed": False, "status": "invalid_tier", "error": f"Unknown tier '{override_tier}'"}

        per_request_max = (
            budget_units
            if budget_units is not None
            else (self.config.policy.budgets.per_request_units_max or 120.0)
        )
        ovr_units = self.estimator.calculate_units_for_tier(ovr)

        # Hard budget check
        if ovr_units > per_request_max:
            return {
                "allowed": False,
                "status": "blocked_by_budget",
                "error": f"Override tier '{ovr.title()}' ({ovr_units} units) exceeds hard budget limit of {per_request_max} units.",
            }

        # Check if below purpose floor
        purpose_key = purpose.lower().replace(" ", "_")
        purpose_cfg = self.purposes.get(purpose_key, {})
        base_floor = purpose_cfg.get("min_tier", "economy").lower()

        if _tier_rank(ovr) < _tier_rank(base_floor):
            warning = f"Warning: {ovr.title()} is below the minimum recommended quality floor ({base_floor.title()}) for {purpose_cfg.get('label', purpose)}. Output may have insufficient detail or be unsuitable for print."
            if not override_confirmed:
                return {
                    "allowed": False,
                    "status": "needs_confirmation",
                    "warning": warning,
                    "requires_confirmation": True,
                }
            else:
                logger.warning("User confirmed below-floor override: purpose=%s, floor=%s, chosen=%s", purpose, base_floor, ovr)
                return {
                    "allowed": True,
                    "status": "overridden",
                    "warning": warning,
                    "confirmed": True,
                }

        return {
            "allowed": True,
            "status": "overridden" if ovr != rec else "recommended",
            "warning": None,
        }
