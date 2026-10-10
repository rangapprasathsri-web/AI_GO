# Competitiveness Gap Report: Purpose-Fit Verification, Benchmarks & Safety Net

Audit completed on: 2026-10-10  
Baseline Test Suite: **146 passed, 0 failed** in 6.21s.  
Demo Baseline: All 7 steps in Section 11 reproduce cleanly (`make demo`).

---

## 1. Audit Table Across Sections 1 to 9

| Section | Requirement | Status | File Paths | Description of Changes Needed |
| :--- | :--- | :--- | :--- | :--- |
| **1. Judging Criteria** | Two+ tiers, visible resource estimate for every generation (including failed), adaptive engine, trade-off display | **Done** | `backend/engine/`, `backend/api/`, `frontend/index.html` | Core rightsizing, resource estimation, and trade-off displays already functional. |
| | Fit-for-purpose evidence for coloring sheet vs poster | **Missing** | `backend/engine/purpose_fit.py`, `frontend/index.html` | Add automated image-based purpose-fit evaluation and UI indicators. |
| **2. Purpose-Fit Check (P0)** | Automated Pillow/numpy checks on image file (dimensions, line coverage, saturation, background, sharpness proxy) | **Missing** | `backend/engine/purpose_fit.py`, `backend/domains/image_resource_optimizer.yaml` | Create `PurposeFitChecker` evaluating format, dimensions, lightness, saturation, line coverage, Laplacian sharpness; thresholds in config. |
| | Verdict "Fit for purpose: Yes / Partly / No" with failed checks list | **Missing** | `backend/engine/purpose_fit.py`, `backend/api/main.py`, `frontend/index.html` | Return `fit_verdict` and `failed_checks` in `/generate` and `/recommend` and display badge beside savings. |
| | Savings claimed only for fit-for-purpose results | **Missing** | `backend/engine/resource.py`, `backend/api/main.py` | Add `savings_eligible` check: if `fit_verdict == 'no'`, avoid attributing positive savings to unusable outputs. |
| | "Good enough?" Yes/No feedback control on each result | **Missing** | `backend/storage/sqlite_storage.py`, `backend/api/main.py`, `frontend/index.html` | Add user feedback endpoint `POST /feedback` storing rating; "No" suggests next tier up without auto-escalating. |
| | Mock image adapter generates pass/fail synthetic test patterns | **Partly done** | `backend/adapters/mock_image.py` | Ensure mock generator can produce clean line art (passes coloring) or low-res/solid assets (fails print/coloring) for testing. |
| **3. Multi-Prompt Benchmark (P0)** | 20+ prompts in `benchmarks/prompts.json` across 5 purposes | **Missing** | `benchmarks/prompts.json` | Create 20 standard prompts (6 coloring, 4 education, 4 presentation, 3 social, 3 print) with disclaimer. |
| | Multi-policy comparison: `always_maximum` vs `adaptive` (vs `cascade`) | **Missing** | `backend/benchmarks/runner.py`, `cli.py` | Benchmark runner actually executing Maximum baseline for real (not counterfactual proxy), computing fit rate and savings. |
| | Benchmark reports (JSON, CSV, Markdown in `reports/`) | **Missing** | `reports/benchmark_summary.json`, `reports/benchmark_summary.csv`, `reports/benchmark_summary.md` | Standardized reporting with totals, units per fit result, fit pass rate, latency, and origin breakdown. |
| | Benchmark screen in UI (table, chart, origin badges, image pairs) | **Missing** | `frontend/index.html` | Add dedicated Benchmark view with policy comparison metrics and downloadable report links. |
| **4. Measurement Levels** | Automated detection of Level 0 (Simulated), Level 1 (Hosted), Level 2 (Local + Counters) | **Missing** | `backend/engine/measurement.py`, `backend/api/main.py`, `frontend/index.html` | Hardware & credentials inspector reporting active measurement level in UI footer, health endpoint, and reports. |
| **5. Cascade Policy (P1)** | "Try cheapest, verify fit, escalate only if needed" policy | **Missing** | `backend/engine/cascade.py`, `backend/benchmarks/runner.py` | Policy that attempts recommended tier, evaluates fit, and escalates to next tier if unfit and within budget. |
| **6. UI Additions** | Fit badge, "Good enough?" buttons, Benchmark screen, coloring vs poster closing view | **Missing** | `frontend/index.html` | Add Fit badge, user feedback widget, benchmark tab, and side-by-side demo comparison modal/card. |
| **7. Safety Net & Assets** | Replay cache for offline demo reliability | **Missing** | `backend/storage/replay_cache.py`, `data/replay_cache.json` | Snapshot of recorded runs loadable offline with visible "Replay of earlier run" honesty label. |
| | Presentation assets in `docs/presentation/` | **Missing** | `docs/presentation/` | Architecture diagram, results table, limitations slide, 3-min script, judge Q&A sheet. |
| **8. Required Tests** | Purpose-fit checks, fit verdict aggregation, savings conditional on fit, benchmark runner, cascade, config threshold flip | **Missing** | `backend/tests/test_purpose_fit.py`, `backend/tests/test_benchmark.py` | Comprehensive test suite covering all section 8 requirements. |

---

## 2. Implementation Order

1. **Tier P0**:
   - `backend/engine/purpose_fit.py`: Automated image-based checks (Pillow, numpy).
   - Config thresholds in `backend/domains/image_resource_optimizer.yaml`.
   - Update `MockImageAdapter` to produce purpose-specific synthetic visual patterns.
   - Update `POST /generate` and `backend/engine/resource.py` to condition savings on fit.
   - User feedback control ("Good enough? Yes/No") and API endpoint `POST /feedback`.
   - `backend/engine/measurement.py`: Environment detection (Level 0 / 1 / 2).
   - `benchmarks/prompts.json` and `backend/benchmarks/runner.py`.
   - Benchmark exports: JSON, CSV, Markdown in `reports/`.
   - UI additions in `frontend/index.html`: Fit badge, feedback widget, Benchmark screen.
   - Tests: `test_purpose_fit.py` and `test_benchmark.py`.
   - Git Checkpoint P0.
2. **Tier P1**:
   - `backend/engine/cascade.py`: Cascade escalation policy with full attempt accounting.
   - Benchmark inclusion of cascade policy.
   - `backend/storage/replay_cache.py` with offline fallback.
   - Presentation assets under `docs/presentation/`.
   - UI coloring sheet vs poster comparison view.
   - Git Checkpoint P1.
