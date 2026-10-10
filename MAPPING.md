# Problem Statement Mapping Specification (MAPPING.md)

This document maps requirements to architectural components of the Adaptive AI Request Optimizer platform. When a new official problem statement arrives, complete the mapping matrix below before changing code.

---

## 1. Domain & Scope Assessment

- **Target Problem Type**: Effort-selection, purpose-driven routing, and cost optimization.
- **Can it be solved by configuration alone?**: Yes, if the domain follows the task category $\rightarrow$ strategy $\rightarrow$ quality floor $\rightarrow$ policy pattern (e.g. image generation, text summarization, code generation).
- **Requires New Adapter?**: Only if connecting to genuinely new upstream API protocols (e.g. specialized speech-to-text, tabular generation, video).
- **Requires New Capability?**: Only if new constraints (e.g. geospatial locality, multi-tenant billing splits) are introduced.

---

## 2. Seed Scenario Mapping Matrix

| Requirement | Architectural Module | Change Type Required | Status |
| :--- | :--- | :--- | :--- |
| **Purpose Intake & One-Tap Selector** | `backend/engine/analysis.py`, `frontend/index.html` | Config + UI defaults | **Supported** |
| **PII & Student Data Sanitization** | `backend/engine/moderation.py`, `backend/adapters/llm_intent.py` | Built-in regex filters | **Supported** |
| **Library Asset Reuse ($0.0005)** | `backend/adapters/reuse_library.py` | Adapter | **Supported** |
| **Deterministic Outline Template ($0.002)**| `backend/adapters/template_outline.py` | Adapter | **Supported** |
| **Multi-Tier Generation ($0.01 - $0.12)** | `backend/adapters/mock_image.py`, `backend/adapters/openai_image.py` | Adapter | **Supported** |
| **Concrete Quality Gate Proxy Checks** | `backend/engine/quality_gate.py` | Domain config / PIL rules | **Supported** |
| **Policy Hierarchy & Cost Ranking** | `backend/engine/policies.py`, `backend/engine/orchestrator.py` | Engine / Config | **Supported** |
| **Monthly School Budget Caps ($20.00)** | `backend/engine/orchestrator.py`, `backend/storage/sqlite_storage.py` | Config & Storage | **Supported** |
| **Approval Gate Workflow** | `backend/engine/orchestrator.py`, `backend/api/main.py` | Engine Policy | **Supported** |
| **Structured LLM Intent Analysis** | `backend/adapters/llm_intent.py`, `backend/engine/analysis.py` | LLM Service Protocol | **Supported** |
| **Real Provider Interface & Mock Transport**| `backend/adapters/openai_image.py` | Adapter | **Supported** |
| **Data Origin Segregation (`data_origin`)**| `backend/engine/models.py`, `backend/eval/runner.py` | Models & Evaluator | **Supported** |
| **Lever Savings Attribution Invariant** | `backend/eval/runner.py` | Evaluation Runner | **Supported** |
| **Hot-Reload & Rollback Versioning** | `backend/engine/config.py`, `backend/storage/sqlite_storage.py` | Storage & Config | **Supported** |

---

## 3. Protocol for Adapting New Statements

When the official problem statement arrives:
1. **Analyze Requirements**: Categorize each item into:
   - Config only (YAML edit in `backend/domains/`)
   - New Adapter (Single file in `backend/adapters/` implementing `BaseAdapter`)
   - Engine Extension (New policy in `backend/engine/policies.py`)
2. **Verify Engine Invariant**: The engine package (`backend/engine/`) must NEVER import from adapters, domains, or API code.
3. **Register Test Suite**: Add contract and integration tests in `backend/tests/`.
4. **Run Benchmark**: Execute `make eval` to verify reproducible seed behavior.
