# Build Report: Adaptive AI Image Resource Optimizer

**Date**: 2026-10-10  
**Status**: All P0 and P1 requirements complete and verified.  
**Test Suite**: 124 passed, 0 failed (100% pass rate).  
**Demo Script**: All 7 steps in Section 11 reproduce cleanly (`make demo`).

---

## 1. What Works

### A. Core Decision Engine & Tier Selection
- **Purpose Floors**: Mapped across all 6 official purposes: `coloring_sheet` (Economy), `educational_illustration` (Economy, suggested Standard), `presentation_graphic` (Standard), `social_media_artwork` (Economy, suggested Standard), `professional_print_artwork` (Maximum), `custom` (asks required inputs; defaults to conservative Standard on uncertainty, never Maximum).
- **Dynamic Floor Raising**:
  - Automatically raises to Standard if print use is flagged or if large print sizes (`A1`, `A0`, `POSTER`, `BANNER`) are specified.
  - Automatically raises based on target resolution (e.g. $\ge 1500$ px raises to Maximum) or required detail (`high` raises to Standard, `maximum` raises to Maximum).
- **Plain-Language Explanations**: Observable factors cited directly (e.g. `deciding_factor: large print size (A1)`), detailing why the tier was chosen.
- **Override Safeguards**:
  - Overriding below the purpose floor prompts an explicit warning dialog and requires explicit confirmation (logged with audit warning).
  - Overriding above hard budget (`per_request_units_max: 120.0`) is strictly blocked.
- **Config-Only Updates**: Changing a purpose's floor (e.g. raising Coloring Sheet to Standard) updates the system recommendation immediately with zero code changes.

### B. Resource Estimation & Counterfactual Savings Math
- **Formula Proxy**: Provider-independent module calculating relative compute units via:
  $$\text{Units} = \text{round}(\text{steps} \times \text{megapixels} \times \text{model\_factor}, 2)$$
- **Transparent Math**:
  - Economy (768×768, 20 steps): **11.80 units** (~90.0% savings vs Maximum).
  - Standard (1024×1024, 30 steps): **31.46 units** (~73.3% savings vs Maximum).
  - Maximum (1536×1536, 50 steps): **117.96 units** (0.0% baseline).
- **Guards**:
  - If baseline is missing, zero, or negative, returns `status: "unavailable"` with reason; never crashes and never returns default 0% or 100%.
  - If selected tier costs more than Maximum, returns honest negative savings without clamping to zero.
- **Energy / Carbon Policy**: Strict adherence to Section 6.5. When `energy_model.enabled` is false, `energy_wh` and `carbon_co2_g` return `null` (never zero or fabricated numbers).

### C. Mock Generation Adapter & Demo Assets
- **Honesty Watermarks**: Synthetic images generated via Pillow carry a prominent `DEMO PLACEHOLDER - NOT REAL MODEL OUTPUT` top banner and bottom watermark with tier name, resolution, and step count.
- **Distinct Output Resolution**: Economy outputs at 768×768, Standard at 1024×1024, Maximum at 1536×1536.
- **Asset Attribution**: Metadata flags `is_placeholder: true`, `placeholder_label: "DEMO PLACEHOLDER: illustrative placeholder asset, not real model output"`.

### D. REST API & Persistence
- `POST /recommend`: Evaluates prompt, purpose, detail, print flags, budget; returns recommended tier, explanation, deciding factor, estimates, alternatives.
- `POST /generate`: Validates override and budget, executes generation, computes savings, saves record to SQLite.
- `GET /history` & `GET /history/{id}`: Returns run log with filter support.
- `GET /history/export.csv`: One-click CSV export of generation records.
- `GET /summary`: Cumulative savings across successful generations with data origin breakdown and running total string.
- `GET /config` & `PUT /config`: Sanitized configuration retrieval (no secrets) and hot-reloading with validation and rollback.
- `GET /health`: Health status and domain verification.

### E. Frontend UI
- Full web interface at `http://localhost:8000` with Outfit and JetBrains Mono typography, dark mode glassmorphism, responsive grid, and accessible controls.
- Running Total widget: *"You have saved about X units across N images (estimated, not measured)"*.
- Interactive quality tier selector with `[★ RECOMMENDED]` pre-selection.
- Centerpiece Resource Comparison panel with Selected Effort, Maximum Baseline, Avoided Savings, and Side-by-side placeholder preview.
- Below-floor confirmation checkbox modal and hard budget error notices.

---

## 2. Test Verification Summary

Ran `make test` (`python -m pytest backend/tests/ -v`):
- **Total Tests Passed**: **124**
- **Failed**: **0**
- **Validation Scenarios (Section 10)**:
  1. `test_scenario_1_coloring_sheet_recommends_economy`: PASSED
  2. `test_scenario_2_print_artwork_recommends_maximum`: PASSED
  3. `test_scenario_3_override_works`: PASSED
  4. `test_scenario_4_savings_calculate_correctly`: PASSED
  5. `test_scenario_5_zero_or_invalid_baseline_unavailable`: PASSED
  6. `test_scenario_6_resource_values_carry_origin_and_label`: PASSED
  7. `test_scenario_7_demo_mode_works_without_credentials`: PASSED
  8. `test_scenario_8_hard_budget_blocks_request`: PASSED
- **Additional Edge Cases**:
  - `test_floor_raised_by_large_print_size`: PASSED
  - `test_floor_raised_by_required_detail`: PASSED
  - `test_custom_purpose_asks_inputs_defaults_to_standard`: PASSED
  - `test_below_floor_override_needs_confirmation`: PASSED
  - `test_tier_above_maximum_gives_negative_savings`: PASSED
  - `test_energy_model_returns_null_when_disabled`: PASSED
  - `test_config_validation_rejects_bad_configs`: PASSED
  - `test_cumulative_summary_counts_successes_only`: PASSED
  - `test_estimation_is_deterministic`: PASSED
  - `test_config_only_change_changes_recommendation`: PASSED
  - `test_engine_has_no_provider_or_api_imports`: PASSED (AST verified)
  - `test_no_secrets_in_config_response`: PASSED

---

## 3. Real vs. Estimated vs. Simulated Accounting

| Component | Classification | Description / Origin Label |
| :--- | :--- | :--- |
| **Tier Selection & Policies** | **REAL** | Python decision engine evaluating floors, detail, resolution, and budget limits. |
| **Override Validation** | **REAL** | Logic enforcing below-floor confirmations and hard budget blocks. |
| **SQLite Persistence** | **REAL** | SQLite database (`data/optimizer.db`) storing generations, config versions, and summaries. |
| **Configuration Engine** | **REAL** | Pydantic schema validation, version history tracking, and rollback. |
| **FastAPI Endpoints** | **REAL** | Asynchronous HTTP endpoints with request validation and error handling. |
| **Avoided Compute Savings** | **ESTIMATED** | Counterfactual savings vs Maximum tier baseline. The Maximum tier was **not run**; labelled `"estimated savings vs maximum tier (not run)"`. |
| **Compute Units** | **SIMULATED** | Relative proxy formula (`steps * megapixels * model_factor`). Labelled `"simulated estimate, not measured energy"`. |
| **Mock Generation Assets** | **SIMULATED** | Synthetic PIL-drawn images with visible `DEMO PLACEHOLDER` stamps. Differ in resolution (768×768 vs 1024×1024 vs 1536×1536). |
| **Physical Energy & Carbon** | **NULL** | Explicitly returns `null` (not zero) when energy model is disabled. No electrical energy claimed. |

---

## 4. Known Limitations

1. **Physical Watt-Hours Uncalibrated**: Physical energy numbers return `null` by design until a certified, peer-reviewed energy model for specific GPU hardware and batch configurations is supplied.
2. **First-Order Proxy**: Relative compute units model linear scaling with steps and megapixels. Non-linear cross-attention memory bandwidth and batching overheads are not modeled in this first-order proxy.
3. **Third-Party Live Providers**: In the absence of live provider API credentials, the system executes in demo mode using synthetic placeholder assets. Real provider adapters activate when valid API keys are configured.
