"""
ColourReady engine module.

For line-art purposes only (e.g. coloring_sheet, colouring_worksheet), takes a small draft
generated at an economical tier, then applies a deterministic local post-processing pipeline:
1. Grayscale
2. Denoise
3. Adaptive threshold
4. Smooth upscale to target print size (default A4 at 300 DPI, configurable)
5. Blur
6. Re-threshold (pure black & white)

Honesty & Standards:
- Latency is labelled 'Measured'.
- Units are a relative proxy; local processing time is converted via a configured factor.
- Real-cost caveat: 'cost does not scale exactly with pixels'.
- Zero imports from adapters, domains, or api (enforced by engine isolation tests).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import io
import math
import time
from typing import Any, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

DEFAULT_LINE_ART_PURPOSES = ["coloring_sheet", "colouring_worksheet"]

STANDARD_PAPER_SIZES_INCHES: dict[str, tuple[float, float]] = {
    "a4": (8.27, 11.69),
    "a5": (5.83, 8.27),
    "letter": (8.5, 11.0),
    "square": (8.27, 8.27),
}


@dataclass
class ColourReadyResult:
    """Outcome of ColourReady local upscale pipeline."""
    skipped: bool
    skip_reason: Optional[str] = None
    draft_image: Optional[Image.Image] = None
    final_image: Optional[Image.Image] = None
    draft_image_bytes: Optional[bytes] = None
    final_image_bytes: Optional[bytes] = None
    draft_dimensions: tuple[int, int] = (0, 0)  # (w, h)
    final_dimensions: tuple[int, int] = (0, 0)  # (w, h)
    pixels_generated: int = 0
    pixels_delivered: int = 0
    pipeline_time_s: float = 0.0
    time_label: str = "Measured"
    time_units_added: float = 0.0
    real_cost_caveat: str = "cost does not scale exactly with pixels"
    is_pure_black_and_white: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dictionary."""
        draft_b64 = None
        if self.draft_image_bytes:
            draft_b64 = f"data:image/png;base64,{base64.b64encode(self.draft_image_bytes).decode('ascii')}"

        final_b64 = None
        if self.final_image_bytes:
            final_b64 = f"data:image/png;base64,{base64.b64encode(self.final_image_bytes).decode('ascii')}"

        ratio = (
            round(self.pixels_delivered / self.pixels_generated, 2)
            if self.pixels_generated > 0
            else 1.0
        )

        return {
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "draft_preview_url": draft_b64,
            "final_preview_url": final_b64,
            "draft_dimensions": list(self.draft_dimensions),
            "final_dimensions": list(self.final_dimensions),
            "pixels_generated": self.pixels_generated,
            "pixels_delivered": self.pixels_delivered,
            "delivery_ratio": ratio,
            "pipeline_time_s": self.pipeline_time_s,
            "pipeline_time_origin": self.time_label,
            "time_units_added": self.time_units_added,
            "real_cost_caveat": self.real_cost_caveat,
            "is_pure_black_and_white": self.is_pure_black_and_white,
            "metadata": self.metadata,
        }


def is_line_art_purpose(purpose: str, allowed_purposes: Optional[list[str]] = None) -> bool:
    """Check if the specified purpose qualifies for line-art ColourReady pipeline."""
    allowed = allowed_purposes or DEFAULT_LINE_ART_PURPOSES
    p = (purpose or "").lower().strip()
    return any(p == a.lower().strip() for a in allowed)


def calculate_target_dimensions(
    draft_w: int,
    draft_h: int,
    print_size: str = "A4",
    dpi: int = 300,
    explicit_dimensions: Optional[tuple[int, int]] = None,
    sizes_table: Optional[dict[str, tuple[float, float]]] = None,
    preserve_aspect_ratio: bool = False,
) -> tuple[int, int]:
    """
    Calculate target dimensions in pixels based on print size, DPI, and draft orientation.
    If explicit_dimensions is provided, it is returned directly.
    """
    if explicit_dimensions is not None:
        return explicit_dimensions

    sizes = sizes_table or STANDARD_PAPER_SIZES_INCHES
    key = (print_size or "a4").lower().strip()
    short_in, long_in = sizes.get(key, (8.27, 11.69))

    if key == "square":
        dim = int(round(short_in * dpi))
        return (dim, dim)

    # Orientation determined by draft aspect ratio
    if draft_w > draft_h:
        # Landscape
        pw = int(round(long_in * dpi))
        ph = int(round(short_in * dpi))
    else:
        # Portrait (default for standard A4 sheets)
        pw = int(round(short_in * dpi))
        ph = int(round(long_in * dpi))

    if not preserve_aspect_ratio or draft_w <= 0 or draft_h <= 0:
        return (pw, ph)

    ratio = draft_w / draft_h
    page_ratio = pw / ph
    if ratio > page_ratio:
        return (pw, max(1, int(round(pw / ratio))))
    else:
        return (max(1, int(round(ph * ratio))), ph)


def _extract_image_data(image_input: Any) -> tuple[Optional[Image.Image], Optional[bytes]]:
    """Normalize image_input to (PIL.Image, bytes)."""
    if image_input is None:
        return None, None

    if isinstance(image_input, dict):
        raw = image_input.get("image_bytes")
        img_obj = image_input.get("image")
        if raw and isinstance(raw, (bytes, bytearray)):
            img = Image.open(io.BytesIO(raw))
            return img, bytes(raw)
        if img_obj and hasattr(img_obj, "save"):
            buf = io.BytesIO()
            img_obj.save(buf, format="PNG")
            return img_obj, buf.getvalue()
        return None, None

    if isinstance(image_input, (bytes, bytearray)):
        img = Image.open(io.BytesIO(image_input))
        return img, bytes(image_input)

    if isinstance(image_input, Image.Image):
        buf = io.BytesIO()
        image_input.save(buf, format="PNG")
        return image_input, buf.getvalue()

    if isinstance(image_input, str):
        if image_input.startswith("data:image"):
            _, encoded = image_input.split(",", 1)
            raw = base64.b64decode(encoded)
            img = Image.open(io.BytesIO(raw))
            return img, raw

    if isinstance(image_input, np.ndarray):
        if len(image_input.shape) == 2:
            img = Image.fromarray(image_input, mode="L")
        elif image_input.shape[2] == 4:
            img = Image.fromarray(image_input, mode="RGBA")
        else:
            img = Image.fromarray(image_input, mode="RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return img, buf.getvalue()

    return None, None


def process_line_art(
    image_input: Any,
    purpose: str,
    print_size: str = "A4",
    dpi: int = 300,
    target_dimensions: Optional[tuple[int, int]] = None,
    config: Optional[dict[str, Any]] = None,
) -> ColourReadyResult:
    """
    Run the 6-step ColourReady upscale pipeline for line-art purposes.
    Non-line-art purposes skip it and return skipped=True with the draft image intact.

    Steps:
    1. Grayscale
    2. Denoise
    3. Adaptive threshold
    4. Smooth upscale to target print size
    5. Blur
    6. Re-threshold (pure black and white)
    """
    cfg = config or {}
    allowed_purposes = cfg.get("line_art_purposes", DEFAULT_LINE_ART_PURPOSES)

    # Gating check: only line-art purposes qualify
    if not is_line_art_purpose(purpose, allowed_purposes):
        pil_img, raw_bytes = _extract_image_data(image_input)
        dims = pil_img.size if pil_img else (0, 0)
        return ColourReadyResult(
            skipped=True,
            skip_reason=f"Purpose '{purpose}' is not line art; ColourReady requires line art ({', '.join(allowed_purposes)}).",
            draft_image=pil_img,
            final_image=pil_img,
            draft_image_bytes=raw_bytes,
            final_image_bytes=raw_bytes,
            draft_dimensions=dims,
            final_dimensions=dims,
            pixels_generated=dims[0] * dims[1],
            pixels_delivered=dims[0] * dims[1],
            pipeline_time_s=0.0,
            time_label="Measured",
            time_units_added=0.0,
            real_cost_caveat="cost does not scale exactly with pixels",
            is_pure_black_and_white=False,
            metadata={"purpose": purpose, "route": "skipped_non_line_art"},
        )

    pil_img, draft_bytes = _extract_image_data(image_input)
    if pil_img is None:
        return ColourReadyResult(
            skipped=True,
            skip_reason="Input image could not be decoded.",
        )

    draft_w, draft_h = pil_img.size
    pixels_gen = draft_w * draft_h

    # Calculate target dimensions
    final_w, final_h = calculate_target_dimensions(
        draft_w=draft_w,
        draft_h=draft_h,
        print_size=print_size,
        dpi=dpi,
        explicit_dimensions=target_dimensions,
        sizes_table=cfg.get("sizes_inches"),
    )
    pixels_del = final_w * final_h

    # Convert to NumPy for OpenCV operations
    np_img = np.array(pil_img)

    t0 = time.perf_counter()

    # Step 1: Grayscale
    if len(np_img.shape) == 3:
        if np_img.shape[2] == 4:
            gray = cv2.cvtColor(np_img, cv2.COLOR_RGBA2GRAY)
        elif np_img.shape[2] == 3:
            gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)
        else:
            gray = np_img[:, :, 0]
    else:
        gray = np_img.copy()

    # Step 2: Denoise
    denoise_k = int(cfg.get("denoise_kernel", 3))
    if denoise_k % 2 == 0:
        denoise_k += 1
    denoised = cv2.medianBlur(gray, max(1, denoise_k))

    # Step 3: Adaptive threshold
    block_size = int(cfg.get("adaptive_block_size", 11))
    if block_size % 2 == 0:
        block_size += 1
    c_val = int(cfg.get("adaptive_c", 2))
    thresh = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, max(3, block_size), c_val
    )

    # Step 4: Smooth upscale to target print size
    upscaled = cv2.resize(thresh, (final_w, final_h), interpolation=cv2.INTER_LANCZOS4)

    # Step 5: Blur (smooth edge anti-aliasing)
    blur_k = int(cfg.get("blur_kernel", 3))
    if blur_k % 2 == 0:
        blur_k += 1
    blur_sigma = float(cfg.get("blur_sigma", 0.8))
    blurred = cv2.GaussianBlur(upscaled, (max(1, blur_k), max(1, blur_k)), blur_sigma)

    # Step 6: Re-threshold (pure black & white: only 0 and 255)
    cutoff = int(cfg.get("threshold_cutoff", 128))
    _, final_bw = cv2.threshold(blurred, cutoff, 255, cv2.THRESH_BINARY)

    t1 = time.perf_counter()
    pipeline_time_s = round(t1 - t0, 4)

    # Verify black and white purity
    unique_vals = np.unique(final_bw)
    is_pure_bw = set(unique_vals).issubset({0, 255})

    # Calculate added units proxy based on measured local pipeline time
    time_unit_rate = float(cfg.get("time_to_units_rate", 0.1))
    time_units_added = round(pipeline_time_s * time_unit_rate, 4)

    # Encode final image
    final_pil = Image.fromarray(final_bw, mode="L")
    buf = io.BytesIO()
    final_pil.save(buf, format="PNG")
    final_bytes = buf.getvalue()

    caveat = cfg.get("caveat", "cost does not scale exactly with pixels")

    return ColourReadyResult(
        skipped=False,
        draft_image=pil_img,
        final_image=final_pil,
        draft_image_bytes=draft_bytes,
        final_image_bytes=final_bytes,
        draft_dimensions=(draft_w, draft_h),
        final_dimensions=(final_w, final_h),
        pixels_generated=pixels_gen,
        pixels_delivered=pixels_del,
        pipeline_time_s=pipeline_time_s,
        time_label="Measured",
        time_units_added=time_units_added,
        real_cost_caveat=caveat,
        is_pure_black_and_white=is_pure_bw,
        metadata={
            "print_size": print_size,
            "target_dpi": dpi,
            "delivery_ratio": round(pixels_del / pixels_gen, 2) if pixels_gen > 0 else 1.0,
            "pipeline_steps": [
                "grayscale",
                "denoise",
                "adaptive_threshold",
                "smooth_upscale",
                "blur",
                "re_threshold",
            ],
        },
    )
