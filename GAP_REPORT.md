# Gap Report: Phased Upgrade Audit & Extension Plan

## 0. Baseline Inspection & Audit Results
- **Inspection Date**: October 2026
- **Git Checkpoint**: Initialized git repository; checkpoint commit `cfece61` created.
- **Test Suite Execution**: 83 tests collected — **83 passed, 0 failed** in 5.42s.
- **Demo Execution**: `python cli.py demo` ran successfully across all 4 demo scenarios (4 strategies, reuse library hit, live config change, 2nd domain).
- **Core Engine Isolation**: Fully verified — `backend/engine/` contains zero imports from `domains/`, `adapters/`, or `api/`.

---

## Detailed Gap Analysis (Sections 1 to 29)

| Section | Requirement | Status | File Location | Notes / Contradictions in Existing Code |
|---|---|---|---|---|
| **1. Role & Objective** | Layered decision architecture: Requester states purpose, System proposes effort level, Admin sets bounds, Requester overrides within bounds | **Done** | `backend/engine/orchestrator.py`, `backend/domains/education_images.yaml`, `README.md` | Domain-agnostic engine. Boundaries strictly encoded. |
| **2. Non-Negotiable Rules** | `data_origin` (`simulated`, `estimated`, `provider_reported`, `billing_confirmed`) on every metric; never mix origins in one total without showing split | **Partly done** | `backend/engine/models.py`, `backend/engine/cost.py`, `backend/eval/runner.py` | Currently uses `is_simulated: bool` and `source: "placeholder"`. Need explicit `data_origin` field on models and reports. |
| 2 | Engine isolation test | **Done** | `backend/tests/test_gaps.py::test_engine_has_no_imports_from_domains_adapters_or_api` | AST import scanner enforces engine isolation. |
| 2 | Secrets on server; untrusted LLM input validation; mock mode usable without credentials | **Done** | `backend/api/main.py`, `backend/engine/moderation.py` | Mock mode runs offline with zero paid API keys or network. |
| **3. Scope Tiers** | P0 (Phase 1 engine + fallback), P1 (LLM intent, full UI, roles, quotas, config studio), P2 (real provider adapter, eval lab) | **Partly done** | Architecture | Phase 1 is solid (P0). Phase 2 LLM service and Phase 3 provider adapter need completion. |
| **4. Stack** | Python 3, FastAPI, Pydantic, HTTPX, SQLite, Pytest, Docker/Makefile compatible | **Done** | `Makefile`, `backend/`, `requirements.txt` | Stack matches specification. |
| **5. Request Model & Intake** | Validated request model (`task_description`, `intended_purpose`, `max_budget`, `max_latency`, `school_id`, etc.) | **Partly done** | `backend/engine/models.py` | `UserRequest` has `prompt`, `inputs`, `school_id`, `role`, `preferred_strategy`. Needs explicit budget/latency fields mapped from inputs. |
| 5 | One-tap intake & per-purpose defaults (Colouring sheet, Flashcard, Illustration, Banner, Other) | **Done** | `backend/domains/education_images.yaml`, `backend/engine/analysis.py`, `frontend/index.html` | First question "What is this for?". Defaults pre-filled automatically. |
| 5 | Deterministic rules classifier & PII rejection in input | **Done** | `backend/engine/analysis.py`, `backend/engine/moderation.py` | Rejects emails, phones, student IDs, and student names in context. |
| **6. Strategy Interface & Strategies** | Common strategy interface with levers (`reuse`, `colour_mode`, `resolution`, `steps`, `variations`) | **Done** | `backend/adapters/base.py`, `backend/engine/models.py` | All strategies declare `levers`. |
| 6 | `reuse_library` adapter (token/tag similarity, quality floor re-check, PII safe, zero cost) | **Done** | `backend/adapters/reuse_library.py` | Token similarity, checks current quality floor (A4 passes, A3 fails). |
| 6 | `template_outline` adapter (deterministic B&W vector outline, zero AI call) | **Done** | `backend/adapters/template_outline.py` | Generates deterministic outlines for line art only. |
| 6 | Allowed strategies per task category in config | **Done** | `backend/domains/education_images.yaml`, `backend/engine/orchestrator.py` | Banners cannot route to template or reuse unless allowed. |
| **7. Decision Logic & Policies** | Policies: `baseline_always_max`, `rule_based`, `cheapest_meeting_quality`, `weighted`, `user_selected`, `manual_review` | **Done** | `backend/engine/policies.py` | Implemented and passing tests. |
| 7 | Additional policies: `quality_first_within_budget`, `latency_first_within_budget`, `manual_approval` | **Missing** | `backend/engine/policies.py`, `backend/engine/models.py` | Need to add `QualityFirstWithinBudgetPolicy`, `LatencyFirstWithinBudgetPolicy`, and `ManualApprovalPolicy`. |
| 7 | Deterministic tie-breaks, hard constraints never overridden by weights, retry/budget limits | **Done** | `backend/engine/orchestrator.py`, `backend/engine/cost.py` | Lower cost $\rightarrow$ lower latency $\rightarrow$ name tie-break. No automatic escalation beyond config limits. |
| **8. Quality Gate (Concrete)** | Automated checks (exists, format, resolution at DPI, colour mode, ink coverage [0.03, 0.25]) | **Done** | `backend/engine/quality_gate.py`, `backend/adapters/mock_image.py` | PIL-based real automated checks. Synthetic images pass or fail. |
| 8 | Proxy disclaimer & optional 1 to 5 human rating stored | **Done** | `backend/engine/quality_gate.py`, `backend/storage/sqlite_storage.py` | Disclaimer displayed in UI and reports; `/api/rating` stores human score. |
| **9. Requester Transparency** | Named effort levels (Reuse, Quick, Standard, Print-quality), currency hidden by default, relative cost | **Done** | `backend/engine/cost.py`, `backend/engine/models.py`, `frontend/index.html` | Requester sees relative cost ("about 1/15 of Print-quality"). Admin sees simulated dollar amounts. |
| 9 | Side-by-side decision preview with real mock outputs, upgrade/downgrade with reason | **Done** | `backend/api/main.py`, `frontend/index.html` | `/api/preview` returns recommended vs next tier up with mock previews. |
| **10. Evaluation & Comparison** | Baseline vs optimized on same seeded workload; savings attribution by lever summing to total | **Done** | `backend/eval/runner.py`, `backend/eval/workload_generator.py` | `attribute_savings_by_lever()` guarantees `reuse + template + lower_tier == total_savings`. |
| 10 | 5 difficult cases + 30+ labelled routing dataset (8+ ambiguous) | **Done** | `backend/eval/workload_generator.py` | Workload generator includes 5 edge cases and 32 labelled requests. |
| **11. Phase 1 Acceptance** | Engine runs with no credentials, policies change by config, reproducible baseline vs optimized | **Done** | Phase 1 complete | 83/83 tests passing offline. |
| **12. Optional LLM Intent Service** | Independent service behind adapter interface; rules first; count optimizer's own cost and latency | **Missing** | `backend/adapters/llm/`, `backend/engine/analysis.py` | Need LLM intent analyzer, caching, and cost tracking. |
| 12 | PII stripped before sending to LLM; untrusted text prompt injection defense | **Missing** | `backend/adapters/llm/` | Sanitization hook and injection resistance tests needed. |
| **13. Structured Output Contract** | Strict Pydantic model (`task_type`, `intended_use`, `quality_requirement`, `constraints`, `missing_information`, `reasoning_summary`) | **Missing** | `backend/engine/models.py` | Strict validation of LLM output. |
| **14. LLM Adapter & Uncertainty** | Adapter supporting environment keys, timeouts, retries, mock responses; golden set rules vs rules+LLM accuracy | **Missing** | `backend/adapters/llm/`, `backend/eval/runner.py` | Evaluate rules-only vs rules-plus-LLM accuracy with overhead cost. |
| **15. Approval Workflow** | Preview before execution; edit or confirm; admin config for purposes requiring approval | **Partly done** | `backend/api/main.py`, `frontend/index.html` | Preview exists; need interactive approval flow for configured purposes. |
| **16. Phase 2 Acceptance** | Structured output validated, engine independent of LLM, injection attempt handled, golden set report | **Missing** | Tests & docs | Need Phase 2 unit tests and `docs/phase2.md`. |
| **17. Provider Adapters** | Provider adapter implementing BaseAdapter with operations, pricing method, usage metadata | **Partly done** | `backend/adapters/` | Mock image and text adapters exist; need a real provider adapter (e.g. OpenAI/HTTPX-based with contract mocks). |
| **18. Cost Estimation** | Pre-execution cost estimation with pricing source, last-updated date, and data_origin | **Partly done** | `backend/engine/cost.py` | Need explicit last-updated date and data_origin tracking. |
| **19. Safe Execution** | Timeouts, bounded retries, rate-limits, aggregate school budgets, cancellation, safety margins | **Partly done** | `backend/engine/orchestrator.py` | Retry limits and school budgets enforced; add explicit safety margin on uncertain pricing. |
| **20. Real-World Evaluation** | Expenditure, completion, quality satisfaction, latency distribution, split by `data_origin` | **Partly done** | `backend/eval/runner.py` | Update evaluation reports to explicitly segment by `data_origin`. |
| **21. Phase 3 Acceptance** | Real provider adapter with mock contract tests, credentials error handling, offline mode | **Missing** | Tests & docs | Need Phase 3 contract tests and `docs/phase3.md`. |
| **22. Configuration, Audit & Governance** | Versioned config with rollback to last valid version; decision audit log with config version used | **Partly done** | `backend/storage/sqlite_storage.py`, `backend/engine/config.py` | Storage tracks config versions; need explicit rollback endpoint and decision audit log query. |
| **23. Roles, Quotas, Showback, Safety** | Requester vs Admin; per-school monthly cap ($20), 80% alerts, showback table; post-execution output moderation | **Partly done** | `backend/api/main.py`, `backend/engine/moderation.py` | Prompt moderation exists; need post-execution output moderation hook. |
| **24. Frontend** | Request Workspace, Preview, Results, Analytics (data_origin split), History, Config Studio with Rollback, Strategy Comparison, Eval Lab | **Partly done** | `frontend/index.html` | Modern glassmorphism UI exists; extend with data_origin badges, History view, and config rollback. |
| **25. Required Tests** | All 25+ test categories in section 25 | **Partly done** | `backend/tests/` | 83 tests passing; add tests for LLM intent adapter, injection, data_origin split, new policies, provider contract. |
| **26. Workflow & Notes** | Learning notes: `docs/phase1.md`, `docs/phase2.md`, `docs/phase3.md` | **Missing** | `docs/` | Need to write all 3 phase documentation summaries. |
| **27. Demo to Leave Working** | 5 demo items: 4 seed requests, reuse hit, config edit, 2nd domain, evaluation with lever savings and data_origin split | **Partly done** | `cli.py` | Update `cli.py demo` to include data_origin split and lever savings summary. |
| **28. Final Deliverables** | `.env.example`, install/launch commands, MAPPING.md template, API docs | **Partly done** | Root directory | Need `.env.example` and MAPPING.md template. |
| **29. New Statement Mapping** | MAPPING.md template for when official problem statement arrives | **Missing** | `MAPPING.md` | Create template file. |

---

## Plan of Action (Phased Implementation)

### Phase 1 Hardening:
1. Add missing policies: `QualityFirstWithinBudgetPolicy`, `LatencyFirstWithinBudgetPolicy`, and `ManualApprovalPolicy` in `backend/engine/policies.py`.
2. Add explicit `DataOrigin` enum (`simulated`, `estimated`, `provider_reported`, `billing_confirmed`) in `backend/engine/models.py`.
3. Add post-execution output moderation hook in `backend/engine/moderation.py` and invoke it in `orchestrator.py`.
4. Create `docs/phase1.md`.
5. Run tests and make git commit checkpoint.

### Phase 2: Intent Analysis & Structured LLM Output
1. Define strict Pydantic structured output models (`LLMIntentAnalysis`, `ExtractedConstraints`, `DecisionFactor`) in `backend/engine/models.py`.
2. Create `LLMAdapter` interface and `MockLLMAdapter` in `backend/adapters/llm.py` supporting timeout, bounded retries, rate limits, and injection resistance.
3. Integrate rules-first intent service: call LLM only when rules classifier is uncertain or policy demands semantic analysis; cache results; count LLM cost and latency in request total.
4. Add golden set evaluation reporting rules-only vs rules-plus-LLM accuracy and LLM cost.
5. Create Phase 2 tests (`test_llm_intent.py`) covering malformed output, timeout, provider failure, wrong classification, injection attempts, and overhead accounting.
6. Create `docs/phase2.md`.
7. Make git commit checkpoint.

### Phase 3: Real Provider Adapter & Cost Estimation
1. Create `OpenAIImageAdapter` in `backend/adapters/openai_image.py` with mock HTTPX transport for zero-cost offline testing, rate-limit and error handling, and `data_origin` tagging.
2. Add safety margin configuration on uncertain pricing.
3. Update evaluation report to output data_origin split explicitly.
4. Add Phase 3 contract tests.
5. Create `docs/phase3.md`.
6. Make git commit checkpoint.

### Cross-Phase UI & Deliverables Polish
1. Extend `frontend/index.html` with data_origin badges, Request History tab, Config Rollback button, and Strategy Comparison table.
2. Create `.env.example` and `MAPPING.md`.
3. Update `cli.py demo` with the 5th demo requirement (eval with data_origin split).
4. Run full test suite, record exact counts in `BUILD_REPORT.md` and `GAP_REPORT.md`.
