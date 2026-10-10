"""
Provider-independent resource estimation module.

Calculates compute units, counterfactual savings vs Maximum tier,
and energy/carbon models under strict honesty rules.
"""
from __future__ import annotations

from typing import Any, Optional

from backend.engine.models import DataOrigin


def compute_tier_units(width: int, height: int, steps: int, model_factor: float = 1.0) -> float:
    """
    First-order relative compute proxy:
    units = steps * megapixels * model_factor
    megapixels = (width * height) / 1,000,000
    """
    if width <= 0 or height <= 0 or steps <= 0:
        return 0.0
    megapixels = (width * height) / 1_000_000.0
    return round(steps * megapixels * model_factor, 2)


def compute_savings(
    selected_units: float,
    maximum_units: Optional[float],
    fit_verdict: Optional[str] = None,
) -> dict[str, Any]:
    """
    Counterfactual savings calculation vs Maximum tier:
    savings_units = maximum_tier_units - selected_tier_units
    savings_percentage = savings_units / maximum_tier_units * 100

    Guards:
    - If fit_verdict == 'no', savings are marked ineligible (0.0 units, 0.0%). No savings claimed on unfit results.
    - If maximum_tier_units is zero, missing or invalid, returns 'unavailable' with reason. Never crashes.
    - If selected_tier costs more than Maximum, returns negative numbers honestly (never clamped to zero).
    """
    if fit_verdict == "no":
        return {
            "savings_units": 0.0,
            "savings_percentage": 0.0,
            "status": "ineligible_unfit",
            "reason": "No savings claimed: output failed purpose-fit verification criteria.",
            "is_negative": False,
            "savings_eligible": False,
        }

    if maximum_units is None or maximum_units <= 0:
        return {
            "savings_units": None,
            "savings_percentage": None,
            "status": "unavailable",
            "reason": "Maximum tier units baseline is unavailable (missing, zero, or invalid)",
            "savings_eligible": False,
        }

    savings_units = round(maximum_units - selected_units, 2)
    savings_percentage = round((savings_units / maximum_units) * 100.0, 1)

    return {
        "savings_units": savings_units,
        "savings_percentage": savings_percentage,
        "status": "available",
        "reason": None if savings_units >= 0 else "Selected tier exceeds baseline Maximum tier (negative savings)",
        "is_negative": savings_units < 0,
        "savings_eligible": True,
    }


class ResourceEstimator:
    """
    Provider-independent resource estimator.
    
    Operates strictly on documented tier parameters and configuration.
    """

    def __init__(self, tiers_config: dict[str, Any], energy_model_config: Optional[dict[str, Any]] = None):
        self.tiers = tiers_config or {}
        self.energy_model = energy_model_config or {"enabled": False, "source": None}

    def get_tier_params(self, tier_name: str) -> dict[str, Any]:
        tier = self.tiers.get(tier_name.lower(), {})
        params = dict(tier.get("params", {}))
        params["model_factor"] = tier.get("model_factor", 1.0)
        return params

    def calculate_units_for_tier(self, tier_name: str) -> float:
        params = self.get_tier_params(tier_name)
        width = params.get("width", 1024)
        height = params.get("height", 1024)
        steps = params.get("steps", 30)
        model_factor = params.get("model_factor", 1.0)
        return compute_tier_units(width, height, steps, model_factor)

    def estimate(
        self,
        tier_name: str,
        data_origin: DataOrigin = DataOrigin.SIMULATED,
    ) -> dict[str, Any]:
        """
        Produce a complete resource estimate for a tier vs the Maximum tier.
        """
        selected_units = self.calculate_units_for_tier(tier_name)
        max_units = self.calculate_units_for_tier("maximum") if "maximum" in self.tiers else None

        savings = compute_savings(selected_units, max_units)

        # Energy & Carbon calculations (Strict Rule: null when disabled)
        energy_wh = None
        carbon_co2_g = None
        energy_label = "not estimated (model disabled)"

        if self.energy_model.get("enabled"):
            source = self.energy_model.get("source")
            wh_factor = self.energy_model.get("wh_per_unit")
            if source and wh_factor:
                energy_wh = round(selected_units * wh_factor, 3)
                # Average carbon factor: ~0.4g CO2/Wh
                carbon_co2_g = round(energy_wh * 0.4, 3)
                energy_label = f"modelled estimate from {source}"
            else:
                energy_label = "not estimated: energy model enabled but missing valid source or conversion factor"

        params = self.get_tier_params(tier_name)

        return {
            "tier": tier_name.lower(),
            "display": self.tiers.get(tier_name.lower(), {}).get("display", tier_name.title()),
            "parameters": {
                "width": params.get("width"),
                "height": params.get("height"),
                "steps": params.get("steps"),
                "model_factor": params.get("model_factor", 1.0),
            },
            "units": selected_units,
            "maximum_units": max_units,
            "baseline_units": max_units,
            "savings_units": savings["savings_units"],
            "savings_percentage": savings["savings_percentage"],
            "savings_status": savings["status"],
            "savings_reason": savings.get("reason"),
            "savings_label": "estimated savings vs maximum tier (not run)",
            "counterfactual_label": "estimated savings vs maximum tier (not run)",
            "label": "simulated estimate, not measured energy",
            "formula": "steps * megapixels * model_factor",
            "data_origin": data_origin.value if hasattr(data_origin, "value") else str(data_origin),
            "energy_wh": energy_wh,
            "carbon_co2_g": carbon_co2_g,
            "energy_label": energy_label,
            "assumptions": [
                "Compute units are a relative proxy: steps * (width*height/10^6) * model_factor",
                "Actual GPU energy varies by hardware, batching, and kernel architecture",
                "Maximum tier baseline was not run; savings represent estimated avoided effort",
            ],
        }
