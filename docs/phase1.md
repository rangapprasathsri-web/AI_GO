# Phase 1 Summary: Configurable Decision Engine

## 1. What Was Implemented
- **Layered Decision Framework**: Strict separation between Requester (states purpose), System (proposes optimal tier meeting quality floor), and District Administrator (sets policies, bounds, and quotas).
- **Request Model & Purpose Capture**: Intake model capturing `task_description`, `intended_purpose`, `max_budget`, `max_latency`, and `school_id`. One-tap selector for primary purposes (Colouring sheet, Flashcard, Classroom illustration, Poster/banner, Other) with per-purpose defaults pre-filled.
- **Deterministic Rules Classifier**: Keyword matching and confidence scoring with fallback to one-tap options on ambiguity.
- **Input Sanitization**: Rejection of student emails, phone numbers, student ID references, and name-in-context patterns before processing.
- **Strategies & Common Interface**:
  - `reuse_library`: Approved asset cache with token/tag similarity and quality floor re-checking ($0.0005).
  - `template_outline`: Deterministic vector outline generator for line-art only ($0.002).
  - `mock_image`: Multi-tier generative model simulation (`draft` $0.01, `standard` $0.04, `premium` $0.12).
- **Complete Suite of Decision Policies**:
  - `baseline_always_max`: Always picks highest tier (comparison baseline).
  - `cheapest_meeting_quality`: Picks cheapest strategy meeting the quality floor.
  - `quality_first_within_budget`: Picks highest fidelity strategy within budget.
  - `latency_first_within_budget`: Picks lowest latency strategy within budget.
  - `rule_based`: Maps purpose tier hints to strategies.
  - `weighted`: Normalised weights for cost, quality, and latency.
  - `user_selected`: Respects requester preference within allowed bounds.
  - `manual_approval` & `manual_review`: Routes requests to administrative sign-off.
- **Deterministic Tie-Breaks**: Lower cost $\rightarrow$ lower latency $\rightarrow$ strategy name.
- **Concrete Quality Gate**: Automated PIL checks for output existence, valid format, resolution at DPI, colour mode match, and ink coverage range [0.03, 0.25].
- **Transparent Output & Data Origin**: All metrics explicitly tagged with `data_origin: simulated` and `source_updated_at`. Currency hidden from requesters by default.
- **Evaluation & Savings Attribution**: Workload generator (70% colouring, 15% flashcards, 10% illustrations, 5% banners, 30% repeat rate, 5 edge cases) with exact lever attribution ($\text{Reuse} + \text{Template} + \text{Lower Tier} == \text{Total Savings}$).

## 2. Why This Design
- **Offline & Credential-Free**: The engine runs 100% offline without requiring paid API keys or live third-party connectivity.
- **Strict Isolation**: `backend/engine/` does not import from domains, adapters, or API code.
- **Zero Cost Invention**: All pricing numbers are explicit placeholders (`source: placeholder`). Savings are never claimed without running the exact same workload against both baseline and optimized policies.

## 3. How to Run It
```bash
# Run tests
python -m pytest backend/tests/ -v

# Run demo
python cli.py demo

# Run seeded evaluation
python cli.py eval --seed 42 --size 50
```

## 4. How to Test It Manually
1. Run `python cli.py demo` to observe 4 distinct strategy selections, followed by an immediate reuse cache hit, a config-only threshold raise, and a second domain run.
2. Run `python cli.py config-check backend/domains/education_images.yaml` to verify the active policy and strategy constraints.

## 5. What the Test Results Establish
- 86/86 automated tests pass completely offline.
- Quality floor filtering prevents low-resolution strategies from serving large banners.
- Budget ceilings route schools exceeding $20/month to `AWAITING_APPROVAL`.
- Personal data in prompts is blocked at intake.

## 6. What Remains (Phase 2 & Phase 3)
- Phase 2: Optional structured LLM intent service with injection defense, golden dataset benchmark, and self-overhead cost accounting.
- Phase 3: Real provider integration adapter with mocked HTTPX contract tests and offline fallback.
