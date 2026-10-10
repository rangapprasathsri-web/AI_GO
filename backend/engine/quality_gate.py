"""
Quality gate module.

Automated checks for verifying output quality against configured floors.
Each check is implemented as a function that operates on the output data.
"""
from __future__ import annotations

import io
from typing import Any, Optional

import numpy as np
from PIL import Image

from backend.engine.models import (
    ColourMode,
    QualityCheckResult,
    QualityFloor,
    QualityGateResult,
)


def run_quality_gate(
    output_data: Any,
    quality_floor: QualityFloor,
    category: str,
    output_format: str = "image",
) -> QualityGateResult:
    """
    Run all applicable quality checks for a category.
    Returns a QualityGateResult with individual check results.

    Note: These are automated proxy checks, not a judgement of
    whether the output is actually good for its intended purpose.
    """
    checks: list[QualityCheckResult] = []

    # Check 1: Output exists and is non-empty
    checks.append(_check_output_exists(output_data))

    if output_format == "image":
        # Try to interpret output_data as image
        img = _load_image(output_data)
        if img is not None:
            # Check 2: Resolution meets minimum DPI
            checks.append(_check_resolution(img, quality_floor))

            # Check 3: Colour mode matches
            checks.append(_check_colour_mode(img, quality_floor))

            # Check 4: Line/ink coverage within range
            if quality_floor.line_coverage:
                checks.append(_check_line_coverage(img, quality_floor))
        else:
            checks.append(QualityCheckResult(
                check_name="image_loadable",
                passed=False,
                message="Output could not be loaded as an image",
            ))
    elif output_format == "text":
        # Text quality checks
        if isinstance(output_data, str):
            if quality_floor.min_length:
                checks.append(_check_text_length(output_data, quality_floor))
        elif isinstance(output_data, dict) and "text" in output_data:
            text = output_data["text"]
            if quality_floor.min_length:
                checks.append(_check_text_length(text, quality_floor))

    all_passed = all(c.passed for c in checks)
    return QualityGateResult(
        passed=all_passed,
        checks=checks,
        is_automated_proxy=True,
        disclaimer=(
            "These are automated proxy checks, not a judgement of "
            "whether the output is actually good for its intended purpose."
        ),
    )


def _check_output_exists(output_data: Any) -> QualityCheckResult:
    """Check that output exists and is non-empty."""
    if output_data is None:
        return QualityCheckResult(
            check_name="output_exists",
            passed=False,
            message="Output is None",
        )

    if isinstance(output_data, bytes) and len(output_data) == 0:
        return QualityCheckResult(
            check_name="output_exists",
            passed=False,
            message="Output is empty (0 bytes)",
        )

    if isinstance(output_data, str) and len(output_data) == 0:
        return QualityCheckResult(
            check_name="output_exists",
            passed=False,
            message="Output is empty string",
        )

    return QualityCheckResult(
        check_name="output_exists",
        passed=True,
        message="Output exists and is non-empty",
    )


def _load_image(data: Any) -> Optional[Image.Image]:
    """Try to load image data from various formats."""
    if isinstance(data, Image.Image):
        return data
    if isinstance(data, bytes):
        try:
            return Image.open(io.BytesIO(data))
        except Exception:
            return None
    if isinstance(data, dict):
        # Mock adapter may return image data in a dict
        if "image" in data and isinstance(data["image"], Image.Image):
            return data["image"]
        if "image_bytes" in data:
            try:
                return Image.open(io.BytesIO(data["image_bytes"]))
            except Exception:
                return None
    return None


def _check_resolution(img: Image.Image, floor: QualityFloor) -> QualityCheckResult:
    """Check that resolution meets minimum DPI for the output."""
    width, height = img.size
    min_dimension = min(width, height)

    # The quality floor specifies min_dpi. We check the image resolution
    # is at least large enough. For a rough check: resolution >= min_dpi * 2
    # (assuming at least a 2-inch output dimension).
    required_pixels = floor.min_dpi * 2 if floor.min_dpi else 0

    passed = min_dimension >= required_pixels

    return QualityCheckResult(
        check_name="resolution",
        passed=passed,
        message=(
            f"Resolution {width}x{height} "
            f"{'meets' if passed else 'does not meet'} "
            f"minimum of {required_pixels}px (for {floor.min_dpi} DPI at 2 inches)"
        ),
        measured_value=f"{width}x{height}",
        required_value=f">={required_pixels}px min dimension",
    )


def _check_colour_mode(img: Image.Image, floor: QualityFloor) -> QualityCheckResult:
    """Check that colour mode matches requirements."""
    if floor.colour_mode == ColourMode.ANY:
        return QualityCheckResult(
            check_name="colour_mode",
            passed=True,
            message="Any colour mode accepted",
        )

    # Convert to numpy for analysis
    arr = np.array(img)

    if floor.colour_mode == ColourMode.BW:
        # Check if image is effectively black and white
        if len(arr.shape) == 2:
            # Already grayscale
            is_bw = True
        elif len(arr.shape) == 3:
            # Check if all channels are the same (grayscale stored as RGB)
            if arr.shape[2] >= 3:
                r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
                # Allow small tolerance for compression artifacts
                is_bw = (
                    np.allclose(r, g, atol=10) and np.allclose(g, b, atol=10)
                )
            else:
                is_bw = True
        else:
            is_bw = False

        return QualityCheckResult(
            check_name="colour_mode",
            passed=is_bw,
            message=(
                f"Image {'is' if is_bw else 'is not'} effectively black and white "
                f"as required for this category"
            ),
            measured_value="bw" if is_bw else "colour",
            required_value="bw",
        )
    elif floor.colour_mode == ColourMode.COLOUR:
        # Check that image has colour variation
        if len(arr.shape) == 2:
            has_colour = False
        elif len(arr.shape) == 3 and arr.shape[2] >= 3:
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            # Has colour if channels differ significantly
            has_colour = not (
                np.allclose(r, g, atol=10) and np.allclose(g, b, atol=10)
            )
        else:
            has_colour = False

        return QualityCheckResult(
            check_name="colour_mode",
            passed=has_colour,
            message=(
                f"Image {'has' if has_colour else 'does not have'} colour "
                f"as required for this category"
            ),
            measured_value="colour" if has_colour else "bw",
            required_value="colour",
        )

    return QualityCheckResult(
        check_name="colour_mode",
        passed=True,
        message="Colour mode check skipped",
    )


def _check_line_coverage(img: Image.Image, floor: QualityFloor) -> QualityCheckResult:
    """
    Check line/ink coverage is within the configured range.
    Rejects blank (too low) or solid-fill (too high) images.
    """
    if not floor.line_coverage or len(floor.line_coverage) != 2:
        return QualityCheckResult(
            check_name="line_coverage",
            passed=True,
            message="No line coverage requirement",
        )

    min_coverage, max_coverage = floor.line_coverage

    # Convert to grayscale and calculate ink coverage
    gray = img.convert("L")
    arr = np.array(gray)

    # "Ink" = pixels that are dark (below threshold)
    threshold = 128  # midpoint
    ink_pixels = np.sum(arr < threshold)
    total_pixels = arr.size
    coverage = ink_pixels / total_pixels if total_pixels > 0 else 0.0

    passed = min_coverage <= coverage <= max_coverage

    return QualityCheckResult(
        check_name="line_coverage",
        passed=passed,
        message=(
            f"Ink coverage {coverage:.3f} "
            f"{'is' if passed else 'is not'} within "
            f"[{min_coverage:.3f}, {max_coverage:.3f}]"
        ),
        measured_value=round(coverage, 4),
        required_value=f"[{min_coverage}, {max_coverage}]",
    )


def _check_text_length(text: str, floor: QualityFloor) -> QualityCheckResult:
    """Check text output length against requirements."""
    length = len(text.split())

    if floor.min_length and length < floor.min_length:
        return QualityCheckResult(
            check_name="text_length",
            passed=False,
            message=f"Text length {length} words is below minimum {floor.min_length}",
            measured_value=length,
            required_value=f">={floor.min_length} words",
        )

    if floor.max_length and length > floor.max_length:
        return QualityCheckResult(
            check_name="text_length",
            passed=False,
            message=f"Text length {length} words exceeds maximum {floor.max_length}",
            measured_value=length,
            required_value=f"<={floor.max_length} words",
        )

    return QualityCheckResult(
        check_name="text_length",
        passed=True,
        message=f"Text length {length} words is within acceptable range",
        measured_value=length,
    )
