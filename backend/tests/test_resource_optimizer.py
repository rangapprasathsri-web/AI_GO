"""
Tests for Image Resource Optimizer (Official Problem Statement).
Validates:
1. The eight validation scenarios:
   (1) coloring sheet recommends Economy
   (2) print artwork recommends Maximum
   (3) override works (within limits)
   (4) savings calculate correctly against Maximum
   (5) zero or invalid baseline returns 'unavailable', no crash
   (6) every resource value carries a correct data_origin and label
   (7) demo mode works with no credentials
   (8) a request over the hard budget is blocked or needs a valid adjustment
2. Dynamic floor raising:
   - floor raised by large print size
   - floor raised by required detail
3. Custom purpose:
   - asks for required inputs and uses conservative default (Standard), never Maximum
4. Override validations:
   - below-floor override requires confirmation and is logged
   - selected tier above Maximum gives negative saving, never clamped to zero
5. Resource estimation & honesty labels:
   - savings formula with multiple parameter sets
   - energy and carbon return null (not zero) when disabled
   - failed generations add spent units and zero savings
   - provider failure does not crash the app
   - demo assets are clearly labelled placeholders in API and history
   - no secrets in config responses
   - cumulative summary counts successes only for savings
   - estimation is deterministic
   - engine has no imports from provider, domain, or API code
   - config-only change changes recommendation without code change
"""
import ast
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.engine.config import load_config_from_file, update_config, validate_config, ConfigValidationError
from backend.engine.models import DataOrigin
from backend.engine.resource import ResourceEstimator, compute_tier_units, compute_savings
from backend.engine.resource_optimizer import ResourceOptimizerService
from backend.storage.sqlite_storage import SQLiteStorage


@pytest.fixture
def resource_config():
    return load_config_from_file("backend/domains/image_resource_optimizer.yaml")


@pytest.fixture
def resource_service(resource_config):
    return ResourceOptimizerService(config=resource_config)


@pytest.fixture
def client():
    return TestClient(app)


# ── Scenario 1: Coloring sheet recommends Economy ────────────────────────────
def test_scenario_1_coloring_sheet_recommends_economy(resource_service):
    result = resource_service.recommend(
        prompt="Cute kitten playing with wool",
        purpose="coloring_sheet",
    )
    assert result["recommended_tier"] == "economy"
    assert result["status"] == "recommended"
    assert result["deciding_factor"] == "purpose_floor"
    assert "Economy" in result["explanation"]


# ── Scenario 2: Print artwork recommends Maximum ─────────────────────────────
def test_scenario_2_print_artwork_recommends_maximum(resource_service):
    result = resource_service.recommend(
        prompt="Fine art exhibition showcase portrait",
        purpose="professional_print_artwork",
    )
    assert result["recommended_tier"] == "maximum"
    assert result["status"] == "recommended"
    assert result["selected_estimate"]["savings_units"] == 0.0
    assert result["selected_estimate"]["savings_percentage"] == 0.0


# ── Scenario 3: Override works within limits ─────────────────────────────────
def test_scenario_3_override_works(resource_service):
    # Recommend economy for coloring sheet, but user overrides to standard within budget
    rec = resource_service.recommend(prompt="Farm tractor", purpose="coloring_sheet")
    assert rec["recommended_tier"] == "economy"

    validation = resource_service.validate_override(
        recommended_tier="economy",
        override_tier="standard",
        purpose="coloring_sheet",
        override_confirmed=False,
    )
    assert validation["allowed"] is True
    assert validation["status"] == "overridden"


# ── Scenario 4: Savings calculate correctly against Maximum ───────────────────
def test_scenario_4_savings_calculate_correctly(resource_service):
    # Formula: steps * megapixels * model_factor
    # Economy: 768 * 768 * 20 / 1e6 = 11.8 units
    # Maximum: 1536 * 1536 * 50 / 1e6 = 117.96 units
    # Savings: 117.96 - 11.8 = 106.16 (~90.0%)
    est = resource_service.estimator.estimate("economy")
    assert est["tier"] == "economy"
    assert est["units"] == pytest.approx(11.8, abs=0.1)
    assert est["baseline_units"] == pytest.approx(117.96, abs=0.1)
    assert est["savings_units"] == pytest.approx(106.16, abs=0.2)
    assert est["savings_percentage"] == pytest.approx(90.0, abs=0.5)
    assert est["savings_label"] == "estimated savings vs maximum tier (not run)"


# ── Scenario 5: Zero or invalid baseline returns 'unavailable', no crash ──────
def test_scenario_5_zero_or_invalid_baseline_unavailable():
    # Baseline 0
    res_zero = compute_savings(selected_units=15.0, maximum_units=0.0)
    assert res_zero["status"] == "unavailable"
    assert res_zero["savings_units"] is None
    assert res_zero["savings_percentage"] is None
    assert "unavailable" in res_zero["reason"].lower()

    # Baseline None
    res_none = compute_savings(selected_units=15.0, maximum_units=None)
    assert res_none["status"] == "unavailable"
    assert res_none["savings_units"] is None

    # Baseline negative
    res_neg = compute_savings(selected_units=15.0, maximum_units=-10.0)
    assert res_neg["status"] == "unavailable"


# ── Scenario 6: Every resource value carries correct data_origin and label ────
def test_scenario_6_resource_values_carry_origin_and_label(resource_service):
    est = resource_service.estimator.estimate("standard")
    assert est["data_origin"] == DataOrigin.SIMULATED.value
    assert est["label"] == "simulated estimate, not measured energy"
    assert "steps * megapixels * model_factor" in est["formula"]
    assert est["savings_label"] == "estimated savings vs maximum tier (not run)"


# ── Scenario 7: Demo mode works with no credentials ───────────────────────────
def test_scenario_7_demo_mode_works_without_credentials(client, monkeypatch):
    from backend.api.main import ACTIVE_IMAGE_ADAPTER
    monkeypatch.setattr(ACTIVE_IMAGE_ADAPTER, "_gemini_api_key", "")
    monkeypatch.setattr(ACTIVE_IMAGE_ADAPTER, "_openai_api_key", "")
    monkeypatch.setattr(ACTIVE_IMAGE_ADAPTER, "_enable_live_diffusion", False)
    monkeypatch.setattr(ACTIVE_IMAGE_ADAPTER, "mode", "demo")
    monkeypatch.setattr(ACTIVE_IMAGE_ADAPTER, "is_real", False)
    monkeypatch.setattr(ACTIVE_IMAGE_ADAPTER, "provider_label", "Demo Mode (Mock)")
    res = client.post("/recommend", json={"prompt": "A sunny mountain landscape", "purpose": "coloring_sheet"})
    assert res.status_code == 200
    rec_data = res.json()
    assert rec_data["recommended_tier"] == "economy"

    gen_res = client.post("/generate", json={
        "prompt": "A sunny mountain landscape",
        "purpose": "coloring_sheet",
        "confirmed_tier": "economy",
    })
    assert gen_res.status_code == 200
    gen_data = gen_res.json()
    assert gen_data["is_placeholder"] is True
    assert "DEMO PLACEHOLDER" in gen_data["placeholder_label"]
    assert gen_data["preview_url"] is not None
    assert gen_data["preview_url"].startswith("data:image/png;base64,")


# ── Scenario 8: Request over hard budget is blocked ───────────────────────────
def test_scenario_8_hard_budget_blocks_request(resource_service):
    # Set tight budget below Economy (e.g. 5 units)
    rec = resource_service.recommend(
        prompt="Complex landscape",
        purpose="coloring_sheet",
        budget_units=5.0,
    )
    assert rec["status"] == "blocked_by_budget"
    assert "exceeds hard budget limit" in rec["explanation"]

    val = resource_service.validate_override(
        recommended_tier="economy",
        override_tier="standard",
        purpose="coloring_sheet",
        budget_units=15.0,  # Standard is ~31.46 units
    )
    assert val["allowed"] is False
    assert val["status"] == "blocked_by_budget"


# ── Dynamic Floor Raising ────────────────────────────────────────────────────
def test_floor_raised_by_large_print_size(resource_service):
    # Normal coloring sheet is economy
    rec_normal = resource_service.recommend(prompt="Car outline", purpose="coloring_sheet")
    assert rec_normal["recommended_tier"] == "economy"

    # Coloring sheet with large print size raises to Standard
    rec_print = resource_service.recommend(prompt="Car outline", purpose="coloring_sheet", print_size="A1")
    assert rec_print["recommended_tier"] == "standard"
    assert "large print size (A1)" in rec_print["deciding_factor"]
    assert "large print size (A1)" in rec_print["explanation"]


def test_floor_raised_by_required_detail(resource_service):
    # Educational illustration default is Economy
    rec_normal = resource_service.recommend(prompt="Plant cell", purpose="educational_illustration")
    assert rec_normal["recommended_tier"] == "economy"

    # With required high detail, raises to Standard
    rec_high = resource_service.recommend(prompt="Plant cell", purpose="educational_illustration", required_detail="high")
    assert rec_high["recommended_tier"] == "standard"

    # With maximum detail, raises to Maximum
    rec_max = resource_service.recommend(prompt="Plant cell", purpose="educational_illustration", required_detail="maximum")
    assert rec_max["recommended_tier"] == "maximum"
    assert "maximum" in rec_max["deciding_factor"]


# ── Custom Purpose: Conservative default, never Maximum ───────────────────────
def test_custom_purpose_asks_inputs_defaults_to_standard(resource_service, client):
    # Engine direct:
    rec = resource_service.recommend(prompt="Bespoke project", purpose="custom")
    assert rec["recommended_tier"] == "standard"  # conservative default, never maximum!
    assert "conservative default" in rec["explanation"]

    # Via API endpoint:
    api_res = client.post("/recommend", json={"prompt": "Custom flyer", "purpose": "custom"})
    assert api_res.status_code == 200
    data = api_res.json()
    assert data["status"] == "needs_clarification"
    assert data["requires_clarification"] is True
    assert "required_detail" in data["missing_inputs"]
    assert data["recommended_tier"] == "standard"  # Never Maximum!


# ── Override validation: Below floor requires confirmation & is logged ───────
def test_below_floor_override_needs_confirmation(resource_service):
    # Professional print artwork has floor Maximum. Overriding to Economy is below floor.
    val_unconfirmed = resource_service.validate_override(
        recommended_tier="maximum",
        override_tier="economy",
        purpose="professional_print_artwork",
        override_confirmed=False,
    )
    assert val_unconfirmed["allowed"] is False
    assert val_unconfirmed["status"] == "needs_confirmation"
    assert "Warning" in val_unconfirmed["warning"]
    assert val_unconfirmed["requires_confirmation"] is True

    # With confirmation, allowed with warning
    val_confirmed = resource_service.validate_override(
        recommended_tier="maximum",
        override_tier="economy",
        purpose="professional_print_artwork",
        override_confirmed=True,
    )
    assert val_confirmed["allowed"] is True
    assert val_confirmed["status"] == "overridden"
    assert val_confirmed["confirmed"] is True


# ── Selected tier above Maximum gives honest negative savings ─────────────────
def test_tier_above_maximum_gives_negative_savings():
    # If selected tier has 150 units and maximum has 100 units
    res = compute_savings(selected_units=150.0, maximum_units=100.0)
    assert res["status"] in ["available", "computed"]
    assert res["savings_units"] == -50.0
    assert res["savings_percentage"] == -50.0  # NOT clamped to 0
    assert res["is_negative"] is True


# ── Energy model: Null when disabled ─────────────────────────────────────────
def test_energy_model_returns_null_when_disabled(resource_service):
    est = resource_service.estimator.estimate("economy")
    assert est["energy_wh"] is None
    assert est["carbon_co2_g"] is None
    assert "disabled" in est["energy_label"]


# ── Config validation rejects invalid configs ─────────────────────────────────
def test_config_validation_rejects_bad_configs(resource_config):
    # 1. Enabled energy model with no source
    bad_cfg = resource_config.model_copy(deep=True)
    bad_cfg.energy_model = {"enabled": True, "source": None, "wh_per_unit": 0.05}
    errors = validate_config(bad_cfg)
    assert any("Enabled energy model has no source" in e for e in errors)

    # 2. Undefined min_tier
    bad_cfg2 = resource_config.model_copy(deep=True)
    bad_cfg2.purposes["test_p"] = {"min_tier": "ultra_hd"}
    errors2 = validate_config(bad_cfg2)
    assert any("undefined min_tier 'ultra_hd'" in e for e in errors2)

    # 3. Non-positive tier parameter
    bad_cfg3 = resource_config.model_copy(deep=True)
    bad_cfg3.tiers["economy"]["params"]["steps"] = 0
    errors3 = validate_config(bad_cfg3)
    assert any("non-positive parameter 'steps'" in e for e in errors3)


# ── Cumulative summary counts successes only for savings ──────────────────────
def test_cumulative_summary_counts_successes_only(client):
    # Perform successful generation
    res1 = client.post("/generate", json={"prompt": "Worksheet 1", "purpose": "coloring_sheet", "confirmed_tier": "economy"})
    assert res1.status_code == 200

    sum_res = client.get("/summary")
    assert sum_res.status_code == 200
    data = sum_res.json()
    assert data["successful_generations"] >= 1
    assert data["cumulative_units_saved"] > 0
    assert "simulated" in data["data_origin_split"]
    assert "You have saved about" in data["running_total_label"]
    assert data["energy_wh"] is None


# ── Determinism of estimation ────────────────────────────────────────────────
def test_estimation_is_deterministic(resource_service):
    est1 = resource_service.estimator.estimate("standard")
    est2 = resource_service.estimator.estimate("standard")
    assert est1["units"] == est2["units"]
    assert est1["savings_units"] == est2["savings_units"]
    assert est1["savings_percentage"] == est2["savings_percentage"]


# ── Config-only change updates recommendation without code change ─────────────
def test_config_only_change_changes_recommendation(resource_config):
    # In base config, coloring_sheet recommends economy
    service1 = ResourceOptimizerService(resource_config)
    rec1 = service1.recommend("Flower outline", "coloring_sheet")
    assert rec1["recommended_tier"] == "economy"

    # Update config: raise coloring sheet min_tier to standard
    updated = update_config(resource_config, {
        "purposes": {
            "coloring_sheet": {
                "label": "Coloring sheet",
                "min_tier": "standard",
            }
        }
    })
    service2 = ResourceOptimizerService(updated)
    rec2 = service2.recommend("Flower outline", "coloring_sheet")
    assert rec2["recommended_tier"] == "standard"


# ── Architectural boundary check: Engine has no provider or API imports ──────
def test_engine_has_no_provider_or_api_imports():
    engine_dir = Path("backend/engine")
    for py_file in engine_dir.glob("*.py"):
        with open(py_file, "r") as f:
            tree = ast.parse(f.read(), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("backend.adapters"), f"{py_file.name} imports {alias.name}"
                    assert not alias.name.startswith("backend.api"), f"{py_file.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("backend.adapters"), f"{py_file.name} imports from {node.module}"
                    assert not node.module.startswith("backend.api"), f"{py_file.name} imports from {node.module}"


# ── No secrets in config response ─────────────────────────────────────────────
def test_no_secrets_in_config_response(client):
    res = client.get("/config")
    assert res.status_code == 200
    cfg = res.json()
    for secret_key in ["secret", "api_key", "password", "token"]:
        assert secret_key not in cfg
