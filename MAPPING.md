# Problem Statement Mapping Specification (MAPPING.md)

## 0. Official Problem Statement
> "AI image generation uses the same computing power regardless of what the image is for, and the energy cost is invisible to the user. Build a generation system that matches computational effort to the purpose of the image and shows the user what was saved by not generating at maximum quality."

---

## 1. Baseline Verification & Pre-Change Inspection
- **Baseline Test Suite Count**: **104 tests collected — 104 passed, 0 failed** in 6.43s.
- **Git State**: Clean branch `master`, latest commit `57b5a37`.
- **Demo State**: `python cli.py demo` verified and working across 5 demonstration parts.

---

## 2. Contradictions with Earlier Prompts

| Aspect | Earlier Prompts (v1 - v4) | Official Statement (v5) | Architectural Adaptation |
| :--- | :--- | :--- | :--- |
| **Requester Transparency** | Hid currency from requesters by default (`hide_currency_from_requester: true`); requesters saw only relative cost labels. | **Reversed**: The cost of effort must be explicitly visible to the person asking. The requester sees compute units and savings. | Show compute resource units, baseline units, and % savings directly to the requester. Currency is optional and only shown when documented rates exist. |
| **Core Measurement Unit** | Currency ($ USD) as primary metric; school monthly dollar budgets ($20.00). | **Compute Resource Units** (`formula: steps * megapixels * model_factor`) as primary metric. Budgets in units (`per_request_units_max`, `session_units_max`). | Introduce `ResourceEstimator` computing units, counterfactual savings vs Maximum tier, and resource unit budget caps. |
| **Counterfactual Savings** | Savings computed across batch workloads against baseline policy. | **Per-Request Counterfactual Savings**: Shows the user what was saved by not generating at Maximum tier for *this specific prompt*. | Compute counterfactual: $\text{Savings} = \text{Maximum Units} - \text{Selected Units}$. Labeled as "estimated savings vs maximum tier (not run)". |
| **Purposes & Tiers** | 4 seed education categories (`colouring_worksheet`, `flashcard`, `detailed_illustration`, `printed_banner`). | 6 standardized purposes (`coloring_sheet`, `educational_illustration`, `presentation_graphic`, `social_media_artwork`, `professional_print_artwork`, `custom`) mapping to 3 tiers (`Economy`, `Standard`, `Maximum`). | Add `image_resource_optimizer.yaml` domain configuration. |
| **District Education Overhead** | Heavy district school quotas, multi-school showback reports, role toggling. | Removed from primary scope (P0). Primary focus is the individual requester's effort transparency, savings, and running total. | Streamline UI & API around the resource optimizer workflow; preserve domain agnosticism. |
| **Energy & Carbon Claims** | Ambiguous simulated energy mentions. | **Strict Prohibition**: Energy in Wh and CO2 must return `null` (not zero) unless an explicit energy model with a published, defensible source is configured. | Energy model disabled by default (`energy_model.enabled = false`); displays "not estimated (model disabled)". |

---

## 3. Comprehensive Mapping Table (Sections 4 to 9)

| Requirement | Likely Existing Component | Verdict | Target Module / Action |
| :--- | :--- | :--- | :--- |
| **Domain Config `image_resource_optimizer`** | `backend/domains/` | **Config only** | Create `backend/domains/image_resource_optimizer.yaml` with units formula, 3 tiers (`economy`, `standard`, `maximum`), 6 purposes, unit budgets, and energy model schema. |
| **Config Validation for Units & Energy** | `backend/engine/config.py` | **New capability** | Validate non-positive parameters, missing tier references, unit budgets, and reject enabled energy model without cited source. Warn if Maximum is not highest unit tier. |
| **Purpose Selector & Floor Mapping** | `backend/engine/analysis.py`, `backend/engine/orchestrator.py` | **Done / Config only** | Map the 6 purposes (`coloring_sheet` $\rightarrow$ economy, `professional_print_artwork` $\rightarrow$ maximum, etc.). |
| **Dynamic Floor Raising** | `backend/engine/orchestrator.py`, `backend/engine/policies.py` | **New capability** | Raise floor if large print size, required detail, or print use flag is provided. Plain-language explanation cites the exact deciding factor. |
| **Custom Purpose with Fallback** | `backend/engine/analysis.py`, `backend/engine/orchestrator.py` | **New capability** | For `custom`, require `required_detail`, `target_resolution`, `print_use`. On uncertainty, default to `on_uncertain: standard` (never silently default to Maximum). |
| **User Override with Risk Logging** | `backend/engine/orchestrator.py`, `backend/api/main.py` | **New capability** | Allow override in either direction within hard budget; overriding below floor requires explicit confirmation ("may be too low for print") and is logged. |
| **Resource Estimation Module** | `backend/engine/cost.py` | **New capability** | Implement `ResourceEstimator`: computes units via `steps * megapixels * model_factor`. Provider-independent. Outputs data_origin, assumptions, and formula. |
| **Counterfactual Savings Math** | `backend/engine/cost.py` | **New capability** | $\text{Savings} = \text{Maximum} - \text{Selected}$; handle zero/invalid Maximum gracefully (return `"unavailable"`, no crash). Negative savings shown honestly if override > Maximum. |
| **Energy & Carbon Null Model** | `backend/engine/cost.py` | **New capability** | Return `null` for Wh and CO2 when disabled; label as modelled estimate from source when enabled. |
| **Mock Provider with Placeholder Marks** | `backend/adapters/mock_image.py` | **New capability** | Generate synthetic PIL images with visible `"DEMO PLACEHOLDER"` watermark, resolution varying per tier (768, 1024, 1536). Never describe as real model output. |
| **Real Provider Adapter (OpenAI DALL-E)** | `backend/adapters/openai_image.py` | **Done / Extend** | Map tiers to documented DALL-E controls (standard 1024x1024, hd 1024x1024, hd 1792x1024). Keep offline mock transport contract tests. |
| **API Endpoints** | `backend/api/main.py` | **New capability** | Implement `POST /recommend`, `POST /generate`, `GET /history`, `GET /history/{id}`, `GET /summary`, `GET /config`, `PUT /config`, `GET /health`. |
| **SQLite History & Cumulative Summary** | `backend/storage/sqlite_storage.py` | **Extend** | Track per-generation units, baseline units, savings, data_origin, override flag/reason. Cumulative summary counts successes only; failed adds spent units, 0 savings. |
| **UI: Resource Comparison Centrepiece** | `frontend/index.html` | **New capability** | Rebuild UI around the resource comparison panel: selected units vs Maximum, savings in units and %, running total, purpose selector with dynamic print/custom fields. |
| **Side-by-Side Preview (Selected vs Max)** | `frontend/index.html`, `backend/api/main.py` | **New capability (P1)** | Display selected vs Maximum preview side-by-side with placeholder labels in demo mode. |
| **Reuse Library & Vector Template Outline** | `backend/adapters/reuse_library.py`, `template_outline.py` | **Remove from P0** | Keep in codebase as optional P2 strategies; default P0 routes to tier generation. |
| **Roles, Quotas, School Showback** | `backend/api/main.py` | **Remove from P0** | Remove school budget caps from P0 in favor of session/per-request resource unit budgets. |
| **Evaluation Lab UI & Postgres** | `frontend/`, `backend/storage/` | **Remove from scope** | Out of scope for this hackathon tier. SQLite and direct evaluation API suffice. |
