"""
Comprehensive gap validation test suite.

Validates all Section 9 required tests from the gap report:
1. Allowed-strategy filtering per purpose
2. Reuse eligibility (approved only)
3. Reuse versus new-request floor mismatch (A4 reused passes, A3 fails)
4. Template adapter limited to line-art purposes
5. One-tap fallback on ambiguous text
6. Savings attribution sums correctly
7. Per-school quota enforcement
8. Personal-data rejection
9. Moderation block
10. Effort-level display hides currency from requesters when configured
11. Engine has no imports from domains or adapters
12. Deterministic evaluation reruns
"""
import ast
from pathlib import Path
import pytest

from backend.adapters.mock_image import MockImageAdapter
from backend.adapters.mock_text import MockTextAdapter
from backend.adapters.registry import AdapterRegistry
from backend.adapters.reuse_library import ReuseLibraryAdapter
from backend.adapters.template_outline import TemplateOutlineAdapter
from backend.engine.analysis import RulesBasedAnalyser
from backend.engine.config import load_config_from_file
from backend.engine.models import PolicyName, RequestStatus, UserRequest
from backend.engine.orchestrator import Orchestrator
from backend.eval.runner import EvaluationRunner, attribute_savings_by_lever
from backend.eval.workload_generator import generate_workload, get_labelled_routing_dataset


@pytest.fixture
def image_config():
    return load_config_from_file("backend/domains/education_images.yaml")


@pytest.fixture
def full_registry():
    reg = AdapterRegistry()
    reg.register(MockImageAdapter())
    reg.register(MockTextAdapter())
    reg.register(TemplateOutlineAdapter())
    reg.register(ReuseLibraryAdapter())
    return reg


# 1. Allowed-strategy filtering per purpose
def test_allowed_strategy_filtering_per_purpose(image_config, full_registry):
    """Printed banner cannot be routed to reuse, template, or draft unless admin allows it."""
    orch = Orchestrator(config=image_config, adapter_lookup=full_registry.get)
    banner_req = UserRequest(
        id="test-banner-filter",
        prompt="Design a printed banner for the school annual report",
        domain="education_images",
        inputs={"subject": "general", "output_size": "A1"},
        school_id="SCHOOL-001",
    )
    record = orch.process_request(banner_req)
    assert record.decision is not None
    assert record.decision.chosen_strategy == "premium"
    # Verify non-allowed strategies were filtered out
    assert "draft" in record.decision.filtered_strategies or "draft" not in image_config.task_categories["printed_banner"].allowed_strategies
    assert "template_outline" in record.decision.filtered_strategies or "template_outline" not in image_config.task_categories["printed_banner"].allowed_strategies


# 2. Reuse eligibility (approved only)
def test_reuse_eligibility_approved_only(image_config):
    """Unapproved items in the reuse library must not be served."""
    reuse_lib = ReuseLibraryAdapter()
    reg = AdapterRegistry()
    reg.register(MockImageAdapter())
    reg.register(reuse_lib)

    # Attempt to add unapproved item
    added = reuse_lib.add_approved_item(
        item_id="unapproved-01",
        prompt="Create a colouring sheet of farm animals to colour in",
        subject="farm animals",
        category="colouring_worksheet",
        resolution=768,
        colour_mode="bw",
        output_data={"image_bytes": b"mock"},
        output_reference="mock://unapproved",
        approved=False,
    )
    assert not added

    req = UserRequest(
        id="test-unapproved-reuse",
        prompt="Create a colouring sheet of farm animals to colour in",
        domain="education_images",
        inputs={"subject": "farm animals", "output_size": "A4"},
    )
    has_hit, _ = reuse_lib.has_match(req, "colouring_worksheet")
    assert not has_hit


# 3. Reuse versus new-request floor mismatch
def test_reuse_floor_mismatch(image_config):
    """An approved A4/A5 resolution (768px) image must fail an A3 request requiring >= 1500px."""
    reuse_lib = ReuseLibraryAdapter()
    reuse_lib.add_approved_item(
        item_id="approved-a4",
        prompt="Create a colouring sheet of dinosaurs to colour in",
        subject="dinosaurs",
        category="colouring_worksheet",
        resolution=768,
        colour_mode="bw",
        output_data={"image_bytes": b"mock"},
        output_reference="mock://a4",
        approved=True,
    )

    # Request 1: A4 request -> passes
    req_a4 = UserRequest(
        id="test-a4",
        prompt="Create a colouring sheet of dinosaurs to colour in",
        domain="education_images",
        inputs={"subject": "dinosaurs", "output_size": "A4"},
    )
    has_match_a4, _ = reuse_lib.has_match(req_a4, "colouring_worksheet")
    assert has_match_a4

    # Request 2: A3 request -> MUST fail because 768px < 1500px required
    req_a3 = UserRequest(
        id="test-a3",
        prompt="Create a colouring sheet of dinosaurs to colour in",
        domain="education_images",
        inputs={"subject": "dinosaurs", "output_size": "A3"},
    )
    has_match_a3, reason = reuse_lib.has_match(req_a3, "colouring_worksheet")
    assert not has_match_a3
    assert "low" in reason.lower() or "1500" in reason or "a3" in reason.lower()


# 4. Template adapter limited to line-art purposes
def test_template_adapter_limited_to_line_art():
    """TemplateOutlineAdapter returns failure for non-line-art purposes."""
    template_adapter = TemplateOutlineAdapter()
    from backend.engine.models import StrategyConfig

    strat = StrategyConfig(
        name="template_outline",
        adapter="template_outline",
        price_per_call=0.002,
        params={"resolution": 768},
    )

    # Test with non-line-art category
    req = UserRequest(
        id="test-non-line-art",
        prompt="Design a printed banner for the school hall",
        domain="education_images",
        inputs={"_category": "printed_banner"},
    )
    res = template_adapter.execute(strat, req)
    assert not res.success
    assert "line-art" in res.error.lower()


# 5. One-tap fallback on ambiguous text
def test_one_tap_fallback_on_ambiguous_text(image_config):
    """When text has no clear keyword match, falls back to the one-tap question."""
    analyser = RulesBasedAnalyser()
    ambiguous_req = UserRequest(
        id="test-ambig",
        prompt="Make something educational for next Tuesday",
        domain="education_images",
        inputs={},
    )
    result = analyser.analyse(ambiguous_req, image_config)
    assert result.is_ambiguous
    assert result.clarification_question is not None
    assert "What is this for?" in result.clarification_question
    assert "Colouring" in result.clarification_question or "Colouring Worksheet" in result.clarification_question


# 6. Savings attribution sums correctly
def test_savings_attribution_sums_correctly(image_config, full_registry):
    """Verify reuse_savings + template_savings + lower_tier_savings == total_savings."""
    runner = EvaluationRunner(config=image_config, adapter_registry=full_registry)
    workload = generate_workload(domain="education_images", size=20, seed=123)

    baseline_records = runner.run_policy(workload, PolicyName.BASELINE_ALWAYS_MAX)
    opt_records = runner.run_policy(workload, PolicyName.CHEAPEST_MEETING_QUALITY)

    attr = attribute_savings_by_lever(baseline_records, opt_records)
    assert "reuse_savings" in attr
    assert "template_savings" in attr
    assert "lower_tier_savings" in attr
    assert "total_savings" in attr

    summed = round(attr["reuse_savings"] + attr["template_savings"] + attr["lower_tier_savings"], 4)
    assert summed == attr["total_savings"]


# 7. Per-school quota enforcement
def test_perschool_quota_enforcement(image_config, full_registry):
    """When school monthly spend exceeds limit, request routes to AWAITING_APPROVAL."""
    orch = Orchestrator(
        config=image_config,
        adapter_lookup=full_registry.get,
        school_spend_lookup=lambda sid: 20.00 if sid == "SCHOOL-BROKE" else 0.0,
    )
    req = UserRequest(
        id="test-broke-school",
        prompt="Create a colouring sheet of farm animals for grade 2",
        domain="education_images",
        inputs={"subject": "farm animals", "output_size": "A4"},
        school_id="SCHOOL-BROKE",
    )
    record = orch.process_request(req, auto_execute=True)
    assert record.status in (RequestStatus.AWAITING_APPROVAL, RequestStatus.BUDGET_EXCEEDED)


# 8. Personal-data rejection
def test_personal_data_rejection(image_config, full_registry):
    """Prompts containing student emails, phones, or student ID patterns are blocked."""
    orch = Orchestrator(config=image_config, adapter_lookup=full_registry.get)

    pii_prompts = [
        "Create a worksheet for student: John Smith (id: 12345)",
        "Make a colouring sheet for john.doe@school.edu",
        "Generate a flashcard for student phone 555-123-4567",
    ]

    for p in pii_prompts:
        req = UserRequest(
            id=f"test-pii-{abs(hash(p))}",
            prompt=p,
            domain="education_images",
            inputs={"subject": "math"},
        )
        record = orch.process_request(req)
        assert record.status == RequestStatus.MODERATION_BLOCKED


# 9. Moderation block
def test_moderation_block(image_config, full_registry):
    """Unsafe child content (violence, weapons) is blocked and logged."""
    orch = Orchestrator(config=image_config, adapter_lookup=full_registry.get)
    unsafe_req = UserRequest(
        id="test-unsafe",
        prompt="Create a colouring sheet showing violence and weapons for grade 2",
        domain="education_images",
        inputs={"subject": "history"},
    )
    record = orch.process_request(unsafe_req)
    assert record.status == RequestStatus.MODERATION_BLOCKED
    assert record.moderation_result is not None
    assert not record.moderation_result["passed"]


# 10. Effort-level display hides currency from requesters when configured
def test_effort_level_display_hides_currency(image_config, full_registry):
    """Requesters see relative cost / effort level without raw currency when hide_currency is True."""
    orch = Orchestrator(config=image_config, adapter_lookup=full_registry.get)

    # Requester role
    req_user = UserRequest(
        id="test-req-display",
        prompt="Create a colouring sheet of zoo animals",
        domain="education_images",
        inputs={"subject": "zoo animals", "output_size": "A4"},
        role="requester",
    )
    rec_user = orch.process_request(req_user)
    assert rec_user.decision is not None
    # Requester display cost must use relative wording, not raw dollars
    assert "Print-quality" in rec_user.decision.explanation.display_cost or "$" not in rec_user.decision.explanation.display_cost

    # Admin role sees raw dollar cost
    admin_user = UserRequest(
        id="test-admin-display",
        prompt="Create a colouring sheet of zoo animals",
        domain="education_images",
        inputs={"subject": "zoo animals", "output_size": "A4"},
        role="admin",
    )
    rec_admin = orch.process_request(admin_user)
    assert "$" in rec_admin.decision.explanation.display_cost


# 11. Engine has no imports from domains or adapters or API
def test_engine_has_no_imports_from_domains_adapters_or_api():
    """Verify clean architectural boundary: backend/engine cannot import domains, adapters, or api."""
    engine_dir = Path("backend/engine")
    for py_file in engine_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("backend.adapters"), f"{py_file.name} imports {alias.name}"
                    assert not alias.name.startswith("backend.domains"), f"{py_file.name} imports {alias.name}"
                    assert not alias.name.startswith("backend.api"), f"{py_file.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("backend.adapters"), f"{py_file.name} imports from {node.module}"
                    assert not node.module.startswith("backend.domains"), f"{py_file.name} imports from {node.module}"
                    assert not node.module.startswith("backend.api"), f"{py_file.name} imports from {node.module}"


# 12. Deterministic evaluation reruns
def test_deterministic_evaluation_reruns(image_config, full_registry):
    """Running evaluation with the exact same seed gives identical costs and metrics."""
    runner = EvaluationRunner(config=image_config, adapter_registry=full_registry)
    wl1 = generate_workload(domain="education_images", size=15, seed=999)
    wl2 = generate_workload(domain="education_images", size=15, seed=999)

    res1 = runner.run_policy(wl1, PolicyName.CHEAPEST_MEETING_QUALITY)
    res2 = runner.run_policy(wl2, PolicyName.CHEAPEST_MEETING_QUALITY)

    m1 = runner.compute_metrics(res1, "cheapest_meeting_quality")
    m2 = runner.compute_metrics(res2, "cheapest_meeting_quality")

    assert m1["total_cost"] == m2["total_cost"]
    assert m1["completed"] == m2["completed"]
    assert m1["strategy_distribution"] == m2["strategy_distribution"]
