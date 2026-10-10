"""
Automated Purpose-Fit Image Verification Engine.

Performs objective, mathematically verifiable proxy checks on generated image files:
- All purposes: file validity, non-empty, expected format, resolution.
- Coloring sheet: light background fraction, low saturation, dark line coverage, solid fills.
- Presentation graphic: aspect ratio (16:9, 4:3), minimum width.
- Social media artwork: aspect ratios (1:1, 4:5, 9:16), minimum dimensions.
- Professional / Print: minimum pixels for target print size at DPI, Laplacian sharpness proxy.
- Educational illustration: moderate resolution, non-blank variance.

Disclaimer: Automated proxy checks, not a judgement of whether a person will like the image.
"""

from dataclasses import dataclass, field
import io
import math
from typing import Any, Optional
from PIL import Image
import numpy as np


@dataclass
class CheckItem:
    name: str
    passed: bool
    observed_value: Any
    threshold: Any
    message: str


@dataclass
class PurposeFitResult:
    verdict: str  # "yes", "partly", "no"
    passed: bool
    score: float  # 0.0 to 1.0
    checks: list[CheckItem] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    summary: str = ""
    disclaimer: str = "Automated proxy checks, not a judgement of whether a person will like the image."

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "passed": self.passed,
            "score": round(self.score, 2),
            "summary": self.summary,
            "disclaimer": self.disclaimer,
            "failed_checks": self.failed_checks,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "observed": c.observed_value,
                    "threshold": c.threshold,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


def compute_laplacian_variance(gray_array: np.ndarray) -> float:
    """
    Compute variance of Laplacian as a proxy for image sharpness.
    Approximated via discrete convolution with 3x3 Laplacian kernel.
    """
    if gray_array.ndim != 2 or gray_array.shape[0] < 3 or gray_array.shape[1] < 3:
        return 0.0
    
    # 3x3 Laplacian kernel: [[0, 1, 0], [1, -4, 1], [0, 1, 0]]
    lap = (
        gray_array[:-2, 1:-1]
        + gray_array[2:, 1:-1]
        + gray_array[1:-1, :-2]
        + gray_array[1:-1, 2:]
        - 4.0 * gray_array[1:-1, 1:-1]
    )
    return float(np.var(lap))


class PurposeFitChecker:
    """Evaluates image assets against domain-configured purpose fitness criteria."""

    def __init__(self, thresholds: Optional[dict[str, Any]] = None):
        self.thresholds = thresholds or self._default_thresholds()

    @staticmethod
    def _default_thresholds() -> dict[str, Any]:
        return {
            "coloring_sheet": {
                "min_light_fraction": 0.70,     # >= 70% pixels should be near-white (> 215)
                "max_saturation": 0.20,          # Mean saturation < 0.20 (mostly black/white/gray)
                "min_line_coverage": 0.02,       # >= 2% pixels are line art (< 80)
                "max_line_coverage": 0.35,       # <= 35% line coverage
                "max_solid_dark_fraction": 0.15, # <= 15% solid filled dark area
            },
            "presentation_graphic": {
                "min_width": 1024,
                "allowed_aspect_ratios": [16 / 9, 4 / 3, 16 / 10],
                "aspect_tolerance": 0.15,
            },
            "social_media_artwork": {
                "min_dimension": 768,
                "allowed_aspect_ratios": [1.0, 4 / 5, 9 / 16, 16 / 9],
                "aspect_tolerance": 0.15,
            },
            "professional_print_artwork": {
                "min_dpi": 300,
                "preview_min_dpi": 150,
                "min_pixels_short_edge": 1200,   # High-resolution print requirement
                "min_sharpness_variance": 40.0,  # Laplacian variance sharpness proxy
            },
            "educational_illustration": {
                "min_width": 768,
                "min_height": 768,
                "min_contrast_std": 15.0,        # Non-blank / non-flat content
            },
            "custom": {
                "min_width": 512,
                "min_height": 512,
            },
        }

    def evaluate_image(
        self,
        image_bytes: bytes,
        purpose: str,
        parameters: Optional[dict[str, Any]] = None,
        print_use: bool = False,
        print_size: Optional[str] = None,
    ) -> PurposeFitResult:
        """Evaluate an image buffer against the criteria for the specified purpose."""
        parameters = parameters or {}
        checks: list[CheckItem] = []

        # 1. Base File Checks (Applies to all purposes)
        if not image_bytes or len(image_bytes) == 0:
            return PurposeFitResult(
                verdict="no",
                passed=False,
                score=0.0,
                checks=[CheckItem("valid_file", False, 0, "> 0 bytes", "Empty or missing file buffer")],
                failed_checks=["valid_file"],
                summary="Generation produced empty or invalid byte buffer.",
            )

        try:
            pil_img = Image.open(io.BytesIO(image_bytes))
            pil_img.verify()
            # Reopen after verify
            pil_img = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            return PurposeFitResult(
                verdict="no",
                passed=False,
                score=0.0,
                checks=[CheckItem("valid_format", False, "corrupted", "valid image", str(e))],
                failed_checks=["valid_format"],
                summary="Corrupted or unreadable image file.",
            )

        checks.append(CheckItem("valid_format", True, pil_img.format or "PNG", "valid format", "Valid image format"))
        width, height = pil_img.size
        aspect_ratio = width / max(1, height)

        # Convert to RGB array for pixel-level analysis
        rgb_img = pil_img.convert("RGB")
        rgb_arr = np.array(rgb_img, dtype=np.float32)
        gray_arr = 0.2989 * rgb_arr[:, :, 0] + 0.5870 * rgb_arr[:, :, 1] + 0.1140 * rgb_arr[:, :, 2]

        # 2. Purpose-Specific Checks
        p_thresh = self.thresholds.get(purpose, self.thresholds.get("custom", {}))

        if purpose == "coloring_sheet":
            # (a) Mostly light background: fraction of pixels with gray > 215
            light_fraction = float(np.mean(gray_arr > 215.0))
            min_light = p_thresh.get("min_light_fraction", 0.70)
            checks.append(CheckItem(
                "light_background",
                light_fraction >= min_light,
                f"{light_fraction * 100:.1f}%",
                f">={min_light * 100:.1f}%",
                "Light background for coloring" if light_fraction >= min_light else "Background too dark/heavy for coloring",
            ))

            # (b) Low color saturation (near-grayscale line art)
            max_c = np.maximum(np.maximum(rgb_arr[:, :, 0], rgb_arr[:, :, 1]), rgb_arr[:, :, 2])
            min_c = np.minimum(np.minimum(rgb_arr[:, :, 0], rgb_arr[:, :, 1]), rgb_arr[:, :, 2])
            denom = np.where(max_c > 0, max_c, 1.0)
            sat_arr = np.where(max_c > 0, (max_c - min_c) / denom, 0.0)
            mean_sat = float(np.mean(sat_arr))
            max_sat = p_thresh.get("max_saturation", 0.20)
            checks.append(CheckItem(
                "low_color_saturation",
                mean_sat <= max_sat,
                f"{mean_sat:.2f}",
                f"<={max_sat:.2f}",
                "Outline is black/white/monochrome" if mean_sat <= max_sat else "Image contains excess color fill",
            ))

            # (c) Line coverage: dark line pixels (gray < 85)
            line_coverage = float(np.mean(gray_arr < 85.0))
            min_lines = p_thresh.get("min_line_coverage", 0.02)
            max_lines = p_thresh.get("max_line_coverage", 0.35)
            lines_ok = (line_coverage >= min_lines) and (line_coverage <= max_lines)
            checks.append(CheckItem(
                "line_coverage_range",
                lines_ok,
                f"{line_coverage * 100:.1f}%",
                f"[{min_lines * 100:.1f}%, {max_lines * 100:.1f}%]",
                "Outline lines present and balanced" if lines_ok else "Lines either absent or excessively thick/filled",
            ))

            # (d) Large print check if requested
            if print_size in ["A1", "A0", "POSTER", "BANNER"]:
                print_dim_ok = min(width, height) >= 1024
                checks.append(CheckItem(
                    "large_print_resolution",
                    print_dim_ok,
                    f"{width}x{height}",
                    ">=1024px",
                    "Resolution sufficient for large print poster" if print_dim_ok else "Resolution too low for requested poster print size",
                ))

        elif purpose == "presentation_graphic":
            min_w = p_thresh.get("min_width", 1024)
            width_ok = width >= min_w
            checks.append(CheckItem(
                "minimum_width",
                width_ok,
                f"{width}px",
                f">={min_w}px",
                "Width suitable for slide deck display" if width_ok else f"Width below minimum {min_w}px",
            ))

            # Aspect ratio check: 16:9, 4:3, or 16:10
            allowed_ratios = p_thresh.get("allowed_aspect_ratios", [16 / 9, 4 / 3])
            tol = p_thresh.get("aspect_tolerance", 0.15)
            ratio_ok = any(abs(aspect_ratio - r) <= tol for r in allowed_ratios)
            checks.append(CheckItem(
                "slide_aspect_ratio",
                ratio_ok,
                f"{aspect_ratio:.2f}",
                "16:9 or 4:3 (±15%)",
                "Aspect ratio matches presentation formats" if ratio_ok else "Aspect ratio not optimized for presentations",
            ))

        elif purpose == "social_media_artwork":
            min_dim = p_thresh.get("min_dimension", 768)
            dim_ok = (width >= min_dim) and (height >= min_dim)
            checks.append(CheckItem(
                "social_minimum_size",
                dim_ok,
                f"{width}x{height}px",
                f">={min_dim}px",
                "Dimensions sufficient for social feed/story" if dim_ok else "Dimensions below social media minimum",
            ))

            allowed_ratios = p_thresh.get("allowed_aspect_ratios", [1.0, 4 / 5, 9 / 16, 16 / 9])
            tol = p_thresh.get("aspect_tolerance", 0.15)
            ratio_ok = any(abs(aspect_ratio - r) <= tol for r in allowed_ratios)
            checks.append(CheckItem(
                "social_aspect_ratio",
                ratio_ok,
                f"{aspect_ratio:.2f}",
                "1:1, 4:5, 9:16, or 16:9",
                "Aspect ratio matches standard social formats" if ratio_ok else "Unusual aspect ratio for social media",
            ))

        elif purpose == "professional_print_artwork":
            # Print artwork strictly requires high pixel density and sharpness
            min_edge = p_thresh.get("min_pixels_short_edge", 1200)
            edge_ok = min(width, height) >= min_edge
            checks.append(CheckItem(
                "print_pixel_density",
                edge_ok,
                f"{min(width, height)}px",
                f">={min_edge}px",
                "Pixel density suitable for 300 DPI reproduction" if edge_ok else f"Resolution below minimum {min_edge}px for print artwork",
            ))

            # Sharpness proxy via Laplacian variance
            sharpness = compute_laplacian_variance(gray_arr)
            min_sharp = p_thresh.get("min_sharpness_variance", 40.0)
            sharp_ok = sharpness >= min_sharp
            checks.append(CheckItem(
                "sharpness_proxy",
                sharp_ok,
                f"{sharpness:.1f}",
                f">={min_sharp:.1f}",
                "High detail sharpness proxy passed" if sharp_ok else "Image detail below threshold for fine art print",
            ))

        elif purpose == "educational_illustration":
            min_w = p_thresh.get("min_width", 768)
            dim_ok = width >= min_w and height >= min_w
            checks.append(CheckItem(
                "illustration_resolution",
                dim_ok,
                f"{width}x{height}px",
                f">={min_w}px",
                "Resolution adequate for educational materials" if dim_ok else "Resolution too small for classroom illustration",
            ))

            # Non-blank content check
            contrast_std = float(np.std(gray_arr))
            min_std = p_thresh.get("min_contrast_std", 15.0)
            contrast_ok = contrast_std >= min_std
            checks.append(CheckItem(
                "non_blank_content",
                contrast_ok,
                f"{contrast_std:.1f}",
                f">={min_std:.1f}",
                "Image contains visible illustrated content" if contrast_ok else "Image appears mostly flat or blank",
            ))

        else:
            # Custom / Fallback
            min_w = p_thresh.get("min_width", 512)
            dim_ok = width >= min_w and height >= min_w
            checks.append(CheckItem(
                "custom_minimum_size",
                dim_ok,
                f"{width}x{height}px",
                f">={min_w}px",
                "Custom dimensions met" if dim_ok else "Dimensions below minimum",
            ))

        # Additional print_use check if flag was raised for any purpose
        if print_use and purpose != "professional_print_artwork":
            print_ok = min(width, height) >= 1024
            checks.append(CheckItem(
                "physical_print_flag_resolution",
                print_ok,
                f"{min(width, height)}px",
                ">=1024px",
                "Resolution meets physical print requirements" if print_ok else "Lower tier lacks sufficient resolution for physical printing",
            ))

        # 3. Aggregate Verdict: Yes / Partly / No
        total_checks = len(checks)
        passed_checks = [c for c in checks if c.passed]
        failed_checks = [c for c in checks if not c.passed]
        score = len(passed_checks) / max(1, total_checks)

        # Critical checks that immediately trigger "no"
        critical_names = {
            "valid_format",
            "print_pixel_density",
            "large_print_resolution",
            "physical_print_flag_resolution",
        }
        critical_failed = any(c.name in critical_names for c in failed_checks)

        if len(failed_checks) == 0:
            verdict = "yes"
            passed = True
            summary = f"Passed all {total_checks} automated purpose-fit checks."
        elif critical_failed or score < 0.5:
            verdict = "no"
            passed = False
            failed_str = ", ".join([c.name for c in failed_checks])
            summary = f"Failed critical purpose requirements: {failed_str}."
        else:
            verdict = "partly"
            passed = True  # Partial fitness allows conditional use
            failed_str = ", ".join([c.name for c in failed_checks])
            summary = f"Met core floor with minor limitations: failed {failed_str}."

        return PurposeFitResult(
            verdict=verdict,
            passed=passed,
            score=score,
            checks=checks,
            failed_checks=[c.name for c in failed_checks],
            summary=summary,
        )
