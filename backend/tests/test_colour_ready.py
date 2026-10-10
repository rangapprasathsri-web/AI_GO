"""
Tests for Feature 1: ColourReady (small draft then local upscale).

Validates:
1. Output size matches target DPI (both A4 portrait and landscape, configurable DPI).
2. Clean outline stays pure black and white (only 0 and 255 pixel values, outline preserved).
3. Non-line-art purposes skip execution deterministically with draft untouched.
4. Orchestrator integration when route is small_then_upscale adds measured pipeline time to unit totals.
5. Real-cost caveat and honesty labels ('Measured') are present everywhere.
6. Engine isolation: zero imports from domains, adapters, or api.
"""
import ast
import io
from pathlib import Path
import pytest
import numpy as np
from PIL import Image, ImageDraw

from backend.engine.colour_ready import (
    ColourReadyResult,
    calculate_target_dimensions,
    is_line_art_purpose,
    process_line_art,
)
from backend.engine.config import load_config_from_file
from backend.engine.models import (
    ExecutionResult,
    RequestRecord,
    RequestStatus,
    StrategyConfig,
    UserRequest,
)
from backend.engine.orchestrator import Orchestrator


def _create_outline_image(w: int = 80, h: int = 80) -> Image.Image:
    """Create a tiny test image with a black outline rectangle on white background."""
    img = Image.new("RGB", (w, h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Draw a 4px black border / outline
    draw.rectangle([10, 10, w - 10, h - 10], outline=(0, 0, 0), width=3)
    return img


# ── Test 1: Output size matches target DPI ──────────────────────────────────
def test_colour_ready_output_size_matches_target_dpi():
    """Verify that output dimensions scale deterministically with target DPI."""
    draft_portrait = _create_outline_image(60, 90)

    # A4 dimensions are 8.27" x 11.69"
    # At 300 DPI portrait:
    expected_w_300 = int(round(8.27 * 300))  # 2481
    expected_h_300 = int(round(11.69 * 300)) # 3507

    res_300 = process_line_art(draft_portrait, purpose="coloring_sheet", print_size="A4", dpi=300)
    assert res_300.skipped is False
    assert res_300.final_dimensions == (expected_w_300, expected_h_300)
    assert res_300.final_image.size == (expected_w_300, expected_h_300)

    # At 150 DPI portrait:
    expected_w_150 = int(round(8.27 * 150))  # 1241
    expected_h_150 = int(round(11.69 * 150)) # 1754

    res_150 = process_line_art(draft_portrait, purpose="coloring_sheet", print_size="A4", dpi=150)
    assert res_150.skipped is False
    assert res_150.final_dimensions == (expected_w_150, expected_h_150)
    assert res_150.final_image.size == (expected_w_150, expected_h_150)

    # Check landscape orientation: draft_w > draft_h
    draft_landscape = _create_outline_image(90, 60)
    res_landscape = process_line_art(draft_landscape, purpose="coloring_sheet", print_size="A4", dpi=300)
    assert res_landscape.final_dimensions == (expected_h_300, expected_w_300)

    # Check square print paper size
    res_square = process_line_art(draft_portrait, purpose="coloring_sheet", print_size="square", dpi=300)
    assert res_square.final_dimensions == (expected_w_300, expected_w_300)


# ── Test 2: Clean outline stays black and white ──────────────────────────────
def test_colour_ready_clean_outline_stays_black_and_white():
    """Verify that after the 6-step pipeline, an outline image is strictly {0, 255}."""
    draft = _create_outline_image(70, 70)
    res = process_line_art(draft, purpose="coloring_sheet", print_size="A4", dpi=100)

    assert res.skipped is False
    assert res.is_pure_black_and_white is True

    # Check pixel array values directly
    arr = np.array(res.final_image)
    unique_vals = set(np.unique(arr))
    assert unique_vals.issubset({0, 255})
    # Both black lines and white background must be present
    assert 0 in unique_vals
    assert 255 in unique_vals

    # Verify honesty labels and metadata
    assert res.time_label == "Measured"
    assert res.pipeline_time_s >= 0.0
    assert res.real_cost_caveat == "cost does not scale exactly with pixels"
    assert res.pixels_delivered > res.pixels_generated
    assert res.metadata["delivery_ratio"] > 1.0


# ── Test 3: Non-line-art purposes skip it ─────────────────────────────────────
def test_colour_ready_non_line_art_purposes_skip():
    """Verify non-line-art purposes skip ColourReady deterministically with draft untouched."""
    img = _create_outline_image(64, 64)

    non_line_purposes = [
        "educational_illustration",
        "presentation_graphic",
        "social_media_artwork",
        "professional_print_artwork",
        "custom",
    ]

    for p in non_line_purposes:
        res = process_line_art(img, purpose=p)
        assert res.skipped is True
        assert res.skip_reason is not None
        assert f"Purpose '{p}' is not line art" in res.skip_reason
        assert res.draft_dimensions == (64, 64)
        assert res.final_dimensions == (64, 64)
        assert res.pixels_delivered == res.pixels_generated
        assert res.pipeline_time_s == 0.0
        assert res.time_units_added == 0.0


# ── Test 4: Orchestrator integration on route small_then_upscale ─────────────
def test_colour_ready_orchestrator_integration():
    """Verify that when route is small_then_upscale, orchestrator runs ColourReady and adds units."""
    config = load_config_from_file("backend/domains/image_resource_optimizer.yaml")

    draft_img = _create_outline_image(64, 64)
    buf = io.BytesIO()
    draft_img.save(buf, format="PNG")
    draft_bytes = buf.getvalue()

    class MockAdapter:
        def execute(self, strategy, request):
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=True,
                output_data={"image": draft_img, "image_bytes": draft_bytes},
                metadata={"resolution": 768, "is_bw": True},
                latency_s=0.25,
                is_simulated=True,
            )

    orchestrator = Orchestrator(
        config=config,
        adapter_lookup=lambda name: MockAdapter(),
    )

    req = UserRequest(
        prompt="Cute butterfly coloring sheet",
        domain=config.domain,
        inputs={
            "_category": "coloring_sheet",
            "route": "small_then_upscale",
            "print_size": "A4",
            "dpi": 100,
        },
    )

    record = orchestrator.process_request(req)
    assert record.status == RequestStatus.COMPLETED
    assert record.execution is not None
    assert "colour_ready" in record.execution.metadata

    cr_meta = record.execution.metadata["colour_ready"]
    assert cr_meta["skipped"] is False
    assert cr_meta["pipeline_time_origin"] == "Measured"
    assert cr_meta["real_cost_caveat"] == "cost does not scale exactly with pixels"

    # Verify that local measured time units were added to the cost breakdown
    assert "colour_ready_units" in record.cost.breakdown
    assert record.cost.breakdown["colour_ready_units"] >= 0.0
    assert record.cost.breakdown["total"] == record.cost.actual_cost

    # Verify that final image is upscaled and draft is preserved
    assert record.execution.output_data["draft_image"] is not None
    assert record.execution.output_data["image"].size == tuple(cr_meta["final_dimensions"])


# ── Test 5: Orchestrator skips ColourReady for other routes ──────────────────
def test_colour_ready_orchestrator_skips_when_route_is_not_small_then_upscale():
    """Verify that orchestrator does not invoke ColourReady when route is not small_then_upscale."""
    config = load_config_from_file("backend/domains/image_resource_optimizer.yaml")

    test_img = _create_outline_image(200, 200)
    buf = io.BytesIO()
    test_img.save(buf, format="PNG")
    test_bytes = buf.getvalue()

    class MockAdapter:
        def execute(self, strategy, request):
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=True,
                output_data={"image": test_img, "image_bytes": test_bytes},
                metadata={"resolution": 1024},
                latency_s=0.5,
                is_simulated=True,
            )

    orchestrator = Orchestrator(
        config=config,
        adapter_lookup=lambda name: MockAdapter(),
    )

    req = UserRequest(
        prompt="Professional presentation slide diagram",
        domain=config.domain,
        inputs={"_category": "presentation_graphic", "route": "direct"},
    )

    record = orchestrator.process_request(req)
    assert record.status == RequestStatus.COMPLETED
    assert "colour_ready" not in record.execution.metadata


# ── Test 6: Engine isolation compliance ──────────────────────────────────────
def test_colour_ready_engine_isolation():
    """Verify backend/engine/colour_ready.py has zero imports from domains, adapters, or api."""
    colour_ready_path = Path("backend/engine/colour_ready.py")
    assert colour_ready_path.exists()

    tree = ast.parse(colour_ready_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("backend.adapters"), f"Imports {alias.name}"
                assert not alias.name.startswith("backend.domains"), f"Imports {alias.name}"
                assert not alias.name.startswith("backend.api"), f"Imports {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith("backend.adapters"), f"Imports from {node.module}"
                assert not node.module.startswith("backend.domains"), f"Imports from {node.module}"
                assert not node.module.startswith("backend.api"), f"Imports from {node.module}"


# ── Test 7: API endpoint integration ─────────────────────────────────────────
def test_colour_ready_generate_api_endpoint():
    """Verify that POST /generate for coloring_sheet returns colour_ready metadata, draft & final preview URLs, and measured time."""
    from fastapi.testclient import TestClient
    from backend.api.main import app

    client = TestClient(app)
    resp = client.post("/generate", json={
        "prompt": "Coloring sheet of friendly lion",
        "purpose": "coloring_sheet",
        "confirmed_tier": "economy",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "colour_ready" in data
    assert data["colour_ready"]["skipped"] is False
    assert data["pipeline_time_origin"] == "Measured"
    assert data["real_cost_caveat"] == "cost does not scale exactly with pixels"
    assert data["pixels_delivered"] > data["pixels_generated"]
    assert data["draft_preview_url"] is not None
    assert data["preview_url"] is not None

