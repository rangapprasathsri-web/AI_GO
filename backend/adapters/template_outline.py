"""
Template outline adapter.

A deterministic, non-generative mock that produces black-and-white
outlines from a template set with zero generative AI calls.
Strictly limited to line-art purposes (e.g., colouring worksheets).
"""
from __future__ import annotations

import hashlib
import io
import time
from typing import Any

from PIL import Image, ImageDraw

from backend.adapters.base import AdapterCapability, AdapterPricing, BaseAdapter
from backend.engine.models import CostEstimate, ExecutionResult, StrategyConfig, UserRequest


class TemplateOutlineAdapter(BaseAdapter):
    """
    Deterministic non-generative adapter producing black-and-white outlines
    from a template set for line-art purposes only.
    """

    def __init__(self, templates: dict[str, list[str]] | None = None):
        self.templates = templates or {
            "farm_animals": ["barn", "sheep", "cow", "tractor"],
            "shapes": ["circle", "star", "flower", "tree"],
            "marine": ["fish", "whale", "turtle", "seaweed"],
        }

    @property
    def name(self) -> str:
        return "template_outline"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            task_categories=["colouring_worksheet"],
            output_types=["image/png"],
            parameter_limits={
                "resolution": {"min": 256, "max": 2048},
            },
        )

    @property
    def pricing(self) -> AdapterPricing:
        return AdapterPricing(
            method="per_call",
            values={"template_outline": 0.002},
            source="placeholder",
        )

    def estimate_cost(self, strategy: StrategyConfig, request: UserRequest) -> CostEstimate:
        return CostEstimate(
            strategy_name=strategy.name,
            estimated_cost=strategy.price_per_call,
            currency="USD",
            source="placeholder",
            is_simulated=True,
            breakdown={"template_fee": strategy.price_per_call, "generative_fee": 0.0},
        )

    def execute(self, strategy: StrategyConfig, request: UserRequest) -> ExecutionResult:
        start_time = time.time()
        category = request.inputs.get("_category", "")
        # If category is not line-art, fail
        if category and category != "colouring_worksheet":
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=0.0,
                latency_s=0.05,
                is_simulated=True,
                error="Template outline adapter only supports line-art purposes (colouring_worksheet)",
            )

        try:
            resolution = strategy.params.get("resolution", 768)
            seed = int(hashlib.md5(request.prompt.encode()).hexdigest()[:8], 16)
            
            # Deterministic template rendering
            img = self._render_template(resolution, seed)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_bytes = buf.getvalue()

            latency = 0.05  # near-instant template lookup and render
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=True,
                output_reference=f"template://outlines/{request.id}.png",
                output_data={"image": img, "image_bytes": image_bytes},
                actual_cost=strategy.price_per_call,
                latency_s=latency,
                is_simulated=True,
                metadata={
                    "resolution": resolution,
                    "is_bw": True,
                    "non_generative": True,
                    "template_rendered": True,
                    "generation_time_s": time.time() - start_time,
                },
            )
        except Exception as e:
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=0.0,
                latency_s=time.time() - start_time,
                is_simulated=True,
                error=f"Template render error: {str(e)}",
            )

    def _render_template(self, resolution: int, seed: int) -> Image.Image:
        """Render a deterministic, crisp black-and-white outline template."""
        img = Image.new("L", (resolution, resolution), 255)
        draw = ImageDraw.Draw(img)

        # Consistent line width for high-contrast B&W coloring sheet
        lw = max(3, resolution // 100)
        margin = int(resolution * 0.1)

        # Deterministic outer frame
        draw.rectangle([margin, margin, resolution - margin, resolution - margin], outline=0, width=lw)

        # Draw clear inner template motifs: circles, central animal/shape outline
        cx, cy = resolution // 2, resolution // 2
        r = int(resolution * 0.25)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=lw)

        # Petals / ear motifs around center
        offsets = [(-r, -r // 2), (r, -r // 2), (-r // 2, r), (r // 2, r)]
        for ox, oy in offsets:
            draw.ellipse([cx + ox - r // 3, cy + oy - r // 3, cx + ox + r // 3, cy + oy + r // 3], outline=0, width=lw)

        # Internal coloring lines (eyes/smile/pattern)
        draw.arc([cx - r // 2, cy - r // 4, cx + r // 2, cy + r // 2], start=20, end=160, fill=0, width=lw)
        draw.line([cx - r // 3, cy - r // 3, cx - r // 4, cy - r // 4], fill=0, width=lw)
        draw.line([cx + r // 3, cy - r // 3, cx + r // 4, cy - r // 4], fill=0, width=lw)

        # Extra decorative coloring zones
        for i in range(4):
            inset = margin + 15 * (i + 1)
            draw.arc([inset, inset, resolution - inset, resolution - inset], start=i * 90, end=i * 90 + 60, fill=0, width=lw)

        return img.convert("RGB")
