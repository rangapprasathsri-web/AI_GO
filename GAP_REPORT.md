# Gap Report: Official Problem Statement Adaptation

## 0. Executive Summary & Audit Baseline
- **Audit Date**: October 2026
- **Baseline Git Checkpoint**: `57b5a37`
- **Baseline Test Suite Status**: **104 passed, 0 failed** across all test suites.
- **Problem Statement**:
  > "AI image generation uses the same computing power regardless of what the image is for, and the energy cost is invisible to the user. Build a generation system that matches computational effort to the purpose of the image and shows the user what was saved by not generating at maximum quality."
- **Strategy**: Adapt the existing domain-agnostic architecture. Preserve passing tests and core abstractions while refocusing the intake, estimation, API, and UI on **compute resource units** and **counterfactual savings vs Maximum tier**.

---

## 1. What We Will Leave Alone
1. **Core Policy Interface & Engine Architecture**:
   - `backend/engine/policies.py`: Policy protocol, ranking mechanics, and constraint filters remain intact.
   - `backend/engine/orchestrator.py`: Orchestration pipeline structure (Validate $\rightarrow$ Load Policy $\rightarrow$ Analyze $\rightarrow$ Filter $\rightarrow$ Rank $\rightarrow$ Explain $\rightarrow$ Execute $\rightarrow$ Quality Gate) remains the core backbone.
   - Engine isolation boundary: `backend/engine/` will continue to have zero imports from adapters, domains, or API code.
2. **Automated Quality Gate**:
   - `backend/engine/quality_gate.py`: PIL proxy checks (existence, format, DPI resolution, colour mode) remain active and available.
3. **Storage Abstraction**:
   - `backend/storage/sqlite_storage.py`: Repository pattern, SQLite tables, config versioning, and migration structure remain.
4. **Existing Tested Domains & Adapters**:
   - `backend/domains/education_images.yaml` and `backend/domains/text_summarization.yaml` remain in the repository so existing baseline tests remain 100% green.
   - `backend/adapters/openai_image.py`: Real provider adapter with HTTPX mock transport contract tests remains intact for P1 integration.

---

## 2. What We Will Change and Add (by Scope Tier)

### Tier P0: Core Resource Optimizer (Credential-Free Demo)

| Component | Target File | Action / Changes |
| :--- | :--- | :--- |
| **New Domain Config** | `backend/domains/image_resource_optimizer.yaml` | Create domain config defining formula `steps * megapixels * model_factor`, 3 tiers (`economy`, `standard`, `maximum`), 6 purposes (`coloring_sheet`, `educational_illustration`, `presentation_graphic`, `social_media_artwork`, `professional_print_artwork`, `custom`), policy `lowest_suitable_tier`, unit budgets (`per_request_units_max: 120`, `session_units_max: 2000`), and disabled energy model. |
| **Config Validation** | `backend/engine/config.py` | Add validation: reject unknown `min_tier`, non-positive tier params, negative budgets, unknown policies, enabled energy model without source. Warn if Maximum is not highest-unit tier. |
| **Resource Estimation Module** | `backend/engine/cost.py` | Add `ResourceEstimator`: computes units via formula, counterfactual savings vs Maximum tier ($\text{Savings} = \text{Max} - \text{Selected}$, $\text{Pct} = \text{Savings} / \text{Max} \times 100$). Handles invalid/zero baselines with `"unavailable"`. Unclamped negative savings if override > Maximum. Energy/carbon return `null` when disabled. |
| **Tier Selection & Floor Raising** | `backend/engine/orchestrator.py`, `backend/engine/analysis.py` | Lowest suitable tier logic: recommends purpose floor, dynamically raised by large print size, required detail, or print use flag. Plain-language explanation cites exact deciding factor. Custom purpose requests inputs, defaults to `standard` on uncertainty (never Maximum). |
| **Override & Budget Flow** | `backend/engine/orchestrator.py`, `backend/api/main.py` | Allow overrides within unit budget. Below-floor overrides require explicit confirmation ("may be too low for print") and log risk. Budget breaches blocked cleanly. |
| **Placeholder Mock Image Adapter** | `backend/adapters/mock_image.py` | Ensure synthetic images have visible `"DEMO PLACEHOLDER"` watermark, resolution varying per tier (768, 1024, 1536). Metadata explicitly tagged with `is_placeholder: true`. |
| **API Endpoints** | `backend/api/main.py` | Implement official contract: `POST /recommend`, `POST /generate`, `GET /history`, `GET /history/{id}`, `GET /summary` (cumulative savings, successes-only count, data_origin split), `GET /config`, `PUT /config` (with rollback), `GET /health`. |
| **SQLite History & Summary** | `backend/storage/sqlite_storage.py` | Store per-generation units, maximum baseline units, counterfactual savings, data_origin, override status. Cumulative summary counts successes only; failures add spent units, zero savings. |
| **UI Rebuild** | `frontend/index.html` | Centrepiece resource comparison panel: selected units vs Maximum, savings in units & %, running total widget, purpose selector with dynamic print/custom fields, quality selector, visible placeholder previews, CSV export. |
| **Testing Suite** | `backend/tests/test_resource_optimizer.py` | 8 validation scenarios + edge cases (floors, raised floors, custom defaults, negative savings on over-max, invalid baselines, energy null, budget blocks, config validation). |
| **CLI Demo** | `cli.py`, `scripts/run_all.sh` | Update demo to follow Section 11: Coloring sheet (Economy) $\rightarrow$ large print size raises to Standard $\rightarrow$ Professional artwork (Maximum, 0 savings) $\rightarrow$ Below-floor override warning $\rightarrow$ Over-budget blocked $\rightarrow$ Running total $\rightarrow$ Config edit. |

### Tier P1: Enhancements
- Side-by-side Selected vs Maximum tier preview in UI (labeled as illustrative placeholders in demo mode).
- Real provider adapter integration mappings for DALL-E 3 / DALL-E 2 with documented parameters.
- History filters (by purpose, tier, override) and CSV download export.
- Pre-execution prompt moderation hook.

### Tier P2: Optional Extras (Deferred/Scoped Out)
- School showback & multi-school dollar quotas (removed from P0 to focus on resource units).
- Evaluation Lab UI & Postgres (removed from scope).
- Live energy calibration runs (energy model remains disabled with `null` output).
