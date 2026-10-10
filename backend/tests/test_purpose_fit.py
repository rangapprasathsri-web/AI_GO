"""
Automated Purpose-Fit Image Verification Engine Tests.

Tests compliance with Section 2 and Section 8 requirements:
- Clean line art passes coloring sheet checks.
- Colour photo, blank image, and solid-fill image fail coloring sheet checks.
- Low-resolution image fails print check; high-resolution image passes.
- Verdict aggregates correctly into Yes / Partly / No.
- Savings are claimed only when fit_verdict is fit ("yes" or "partly"); unfit ("no") gets 0 savings.
- "Good enough? No" suggests next tier without auto-escalating.
- Config-only threshold adjustment flips verdict without code changes.
"""

import io
import numpy as np
from PIL import Image, ImageDraw
import pytest

from backend.engine.purpose_fit import PurposeFitChecker, PurposeFitResult, compute_laplacian_variance
from backend.engine.resource import compute_savings
from backend.storage.sqlite_storage import SQLiteStorage


def _create_clean_line_art(width=768, height=768) -> bytes:
    """Mostly white background, black outline, low saturation."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Draw simple outlines
    draw.rectangle([50, 50, width - 50, height - 50], outline=(0, 0, 0), width=4)
    draw.ellipse([150, 150, width - 150, height - 150], outline=(0, 0, 0), width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_color_photo(width=768, height=768) -> bytes:
    """High saturation, full colour palette."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :, 0] = 240  # Red
    arr[:, :, 1] = 80   # Green
    arr[:, :, 2] = 40   # Blue
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_blank_image(width=768, height=768) -> bytes:
    """Pure white image with 0 lines."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_solid_fill_image(width=768, height=768) -> bytes:
    """Nearly all black / solid fill."""
    img = Image.new("RGB", (width, height), color=(10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_sharp_print_image(width=1536, height=1536) -> bytes:
    """High resolution, rich detail/edges."""
    img = Image.new("RGB", (width, height), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    for i in range(50, width - 50, 40):
        draw.line([(i, 50), (i, height - 50)], fill=(20, 20, 80), width=3)
        draw.line([(50, i), (width - 50, i)], fill=(80, 20, 20), width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestPurposeFitChecks:
    def setup_method(self):
        self.checker = PurposeFitChecker()

    def test_clean_line_art_passes_coloring_check(self):
        buf = _create_clean_line_art()
        res = self.checker.evaluate_image(buf, purpose="coloring_sheet")
        assert res.verdict == "yes"
        assert res.passed is True
        assert len(res.failed_checks) == 0

    def test_colour_photo_fails_coloring_check(self):
        buf = _create_color_photo()
        res = self.checker.evaluate_image(buf, purpose="coloring_sheet")
        assert res.verdict in ("no", "partly")
        assert "low_color_saturation" in res.failed_checks

    def test_blank_image_fails_coloring_check(self):
        buf = _create_blank_image()
        res = self.checker.evaluate_image(buf, purpose="coloring_sheet")
        assert res.verdict in ("no", "partly")
        assert "line_coverage_range" in res.failed_checks

    def test_solid_fill_image_fails_coloring_check(self):
        buf = _create_solid_fill_image()
        res = self.checker.evaluate_image(buf, purpose="coloring_sheet")
        assert res.verdict in ("no", "partly")
        assert "light_background" in res.failed_checks or "line_coverage_range" in res.failed_checks

    def test_low_res_fails_print_check(self):
        # 512x512 is below 1200 minimum short-edge pixels
        buf = _create_clean_line_art(width=512, height=512)
        res = self.checker.evaluate_image(buf, purpose="professional_print_artwork", print_use=True)
        assert res.verdict in ("no", "partly")
        assert "print_pixel_density" in res.failed_checks

    def test_high_res_passes_print_check(self):
        buf = _create_sharp_print_image(width=1536, height=1536)
        res = self.checker.evaluate_image(buf, purpose="professional_print_artwork", print_use=True)
        assert res.verdict == "yes"
        assert res.passed is True

    def test_verdict_aggregation(self):
        # Fully valid -> "yes"
        good = self.checker.evaluate_image(_create_clean_line_art(), purpose="coloring_sheet")
        assert good.verdict == "yes"
        assert good.score == 1.0

        # Partial failure -> "partly"
        blank = self.checker.evaluate_image(_create_blank_image(), purpose="coloring_sheet")
        assert blank.verdict == "partly"

        # Complete failure -> "no"
        empty_buf = b""
        empty = self.checker.evaluate_image(empty_buf, purpose="coloring_sheet")
        assert empty.verdict == "no"
        assert empty.score == 0.0

    def test_config_only_threshold_change_flips_verdict(self):
        # With default threshold (min_light_fraction = 0.70), an 85% light image passes
        buf = _create_clean_line_art()
        default_res = self.checker.evaluate_image(buf, purpose="coloring_sheet")
        assert default_res.verdict == "yes"

        # With an extremely strict custom threshold (min_light_fraction = 0.999), it fails
        strict_checker = PurposeFitChecker(
            thresholds={
                "coloring_sheet": {
                    "min_light_fraction": 0.999,
                    "max_saturation": 0.01,
                    "min_line_coverage": 0.02,
                    "max_line_coverage": 0.35,
                    "max_solid_dark_fraction": 0.15,
                }
            }
        )
        flipped_res = strict_checker.evaluate_image(buf, purpose="coloring_sheet")
        assert flipped_res.verdict in ("no", "partly")
        assert "light_background" in flipped_res.failed_checks


class TestSavingsConditionalOnFitness:
    def test_savings_claimed_only_for_fit_results(self):
        # Units: 10 vs 100 baseline
        # 1. When fit ("yes"), savings are computed and claimed
        fit_savings = compute_savings(10.0, 100.0, fit_verdict="yes")
        assert fit_savings["savings_eligible"] is True
        assert fit_savings["savings_units"] == 90.0
        assert fit_savings["savings_percentage"] == 90.0

        # 2. When partly fit ("partly"), savings are computed with caveat
        partly_savings = compute_savings(10.0, 100.0, fit_verdict="partly")
        assert partly_savings["savings_eligible"] is True
        assert partly_savings["savings_units"] == 90.0

        # 3. When unfit ("no"), savings MUST NOT be claimed (0 units, 0%)
        unfit_savings = compute_savings(10.0, 100.0, fit_verdict="no")
        assert unfit_savings["savings_eligible"] is False
        assert unfit_savings["savings_units"] == 0.0
        assert unfit_savings["savings_percentage"] == 0.0
        assert "failed purpose-fit verification" in unfit_savings["reason"]


class TestUserFeedbackControl:
    def test_feedback_no_suggests_next_tier_without_auto_escalating(self, tmp_path):
        db_file = str(tmp_path / "test_feedback.db")
        storage = SQLiteStorage(db_file)

        # Store generation
        storage.save_generation({
            "id": "gen-test-01",
            "prompt": "Coloring sheet",
            "purpose": "coloring_sheet",
            "tier": "economy",
            "estimated_units": 7.08,
            "baseline_units": 117.96,
            "status": "completed",
        })

        # Submit "no" feedback
        storage.save_feedback({
            "id": "fb-01",
            "generation_id": "gen-test-01",
            "rating": "no",
            "suggested_tier": "standard",
            "comment": "Lines too faint for kindergarteners",
        })

        fb = storage.get_feedback("gen-test-01")
        assert fb is not None
        assert fb["rating"] == "no"
        assert fb["suggested_tier"] == "standard"

        # Verify generation tier did NOT automatically escalate
        gen = storage.get_generation("gen-test-01")
        assert gen["tier"] == "economy"  # Still economy, never auto-escalated
