"""
Mock image adapter.

A deterministic mock that generates synthetic images for testing.
Images are crafted to genuinely pass or fail quality gate checks
based on the strategy parameters and request type.
"""
from __future__ import annotations

import hashlib
import io
import time
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from backend.adapters.base import AdapterCapability, AdapterPricing, BaseAdapter
from backend.engine.models import CostEstimate, ExecutionResult, StrategyConfig, UserRequest


class MockImageAdapter(BaseAdapter):
    """
    Deterministic mock image provider with three tiers.
    
    Generates synthetic images that can genuinely pass or fail
    quality gate checks. Uses the request ID as seed for determinism.
    """

    def __init__(self, fail_rate: float = 0.0, fail_request_ids: set[str] | None = None):
        """
        Args:
            fail_rate: Probability of simulated failure (0.0 to 1.0). Not used in deterministic mode.
            fail_request_ids: Set of request IDs that should fail (for testing).
        """
        self._fail_request_ids = fail_request_ids or set()

    @property
    def name(self) -> str:
        return "mock_image"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            task_categories=[
                "colouring_worksheet",
                "flashcard",
                "detailed_illustration",
                "printed_banner",
            ],
            output_types=["image/png"],
            parameter_limits={
                "steps": {"min": 1, "max": 100},
                "resolution": {"min": 256, "max": 4096},
            },
        )

    @property
    def pricing(self) -> AdapterPricing:
        return AdapterPricing(
            method="per_call",
            values={
                "draft": 0.01,
                "standard": 0.04,
                "premium": 0.12,
            },
            source="placeholder",
        )

    def estimate_cost(self, strategy: StrategyConfig, request: UserRequest) -> CostEstimate:
        return CostEstimate(
            strategy_name=strategy.name,
            estimated_cost=strategy.price_per_call,
            source="placeholder",
            is_simulated=True,
            breakdown={"base_price": strategy.price_per_call},
        )

    def execute(self, strategy: StrategyConfig, request: UserRequest) -> ExecutionResult:
        """
        Generate a synthetic image based on strategy parameters.
        
        The image characteristics are controlled by strategy params to ensure
        quality gate checks are meaningful:
        - Draft: small, black-and-white, with controlled ink coverage
        - Standard: medium, colour, moderate detail
        - Premium: large, full colour, high detail
        """
        start_time = time.time()

        # Check for deliberate failures
        if request.id in self._fail_request_ids:
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=strategy.price_per_call,
                latency_s=0.1,
                is_simulated=True,
                error="Simulated provider error: service unavailable",
            )

        try:
            width = strategy.params.get("width") or strategy.params.get("resolution", 512)
            height = strategy.params.get("height") or strategy.params.get("resolution", 512)
            steps = strategy.params.get("steps", 15)

            # Use request ID as seed for determinism
            seed = int(hashlib.md5(request.id.encode()).hexdigest()[:8], 16)
            rng = np.random.RandomState(seed)

            # Determine image characteristics from category
            category = request.inputs.get("_category", "")
            is_bw = category in ("colouring_worksheet", "coloring_sheet")
            needs_colour = category in ("flashcard", "detailed_illustration", "printed_banner", "educational_illustration", "presentation_graphic", "social_media_artwork", "professional_print_artwork")

            # Generate the synthetic image
            img = self._generate_image(
                width=width,
                height=height,
                is_bw=is_bw,
                needs_colour=needs_colour,
                detail_level=steps,
                rng=rng,
                category=category,
                strategy_name=strategy.name,
            )

            # Simulate latency based on strategy
            simulated_latency = strategy.latency_s
            actual_time = time.time() - start_time

            # Convert image to bytes
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_bytes = buf.getvalue()

            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=True,
                output_reference=f"mock://placeholders/{strategy.name}_{request.id}.png",
                output_data={"image": img, "image_bytes": image_bytes},
                actual_cost=strategy.price_per_call,
                latency_s=simulated_latency,
                is_simulated=True,
                metadata={
                    "resolution": max(width, height),
                    "width": width,
                    "height": height,
                    "steps": steps,
                    "is_bw": is_bw,
                    "is_placeholder": True,
                    "placeholder_label": "DEMO PLACEHOLDER: illustrative placeholder asset, not real model output",
                    "data_origin": "simulated",
                    "generation_time_s": actual_time,
                    "simulated_latency_s": simulated_latency,
                },
            )

        except Exception as e:
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=strategy.price_per_call,
                latency_s=time.time() - start_time,
                is_simulated=True,
                error=f"Mock adapter error: {str(e)}",
            )

    def _generate_image(
        self,
        width: int,
        height: int,
        is_bw: bool,
        needs_colour: bool,
        detail_level: int,
        rng: np.random.RandomState,
        category: str,
        strategy_name: str = "",
    ) -> Image.Image:
        """
        Generate a synthetic image with characteristics matching the strategy.
        Always stamped with a prominent DEMO PLACEHOLDER mark.
        """
        if is_bw:
            img = self._generate_bw_image(width, height, detail_level, rng, category)
        else:
            img = self._generate_colour_image(width, height, detail_level, rng, category)

        # Apply prominent DEMO PLACEHOLDER banner
        return self._stamp_demo_placeholder(img, strategy_name, width, height, detail_level)

    def _stamp_demo_placeholder(
        self,
        img: Image.Image,
        strategy_name: str,
        width: int,
        height: int,
        steps: int,
    ) -> Image.Image:
        """Stamp an unambiguous DEMO PLACEHOLDER label across the image."""
        draw = ImageDraw.Draw(img)
        banner_h = max(32, height // 16)

        # Top banner (dark charcoal with bright orange accent)
        draw.rectangle([0, 0, width, banner_h], fill=(24, 24, 27))
        banner_text = f"DEMO PLACEHOLDER - NOT REAL MODEL OUTPUT [{strategy_name.upper()}] ({width}x{height}, {steps} steps)"
        draw.text((12, banner_h // 4), banner_text, fill=(251, 146, 60))

        # Bottom banner (subtle watermark)
        draw.rectangle([0, height - banner_h, width, height], fill=(24, 24, 27))
        footer_text = f"Simulated placeholder asset | Computational proxy demonstration"
        draw.text((12, height - banner_h + (banner_h // 4)), footer_text, fill=(156, 163, 175))

        return img

    def _generate_bw_image(
        self,
        width: int,
        height: int,
        detail_level: int,
        rng: np.random.RandomState,
        category: str,
    ) -> Image.Image:
        """
        Generate a black-and-white outline image.
        Ink coverage is controlled to be within typical colouring sheet range (3-25%).
        """
        img = Image.new("L", (width, height), 255)
        draw = ImageDraw.Draw(img)

        resolution = min(width, height)
        num_shapes = max(8, detail_level // 2)

        for _ in range(num_shapes):
            shape_type = rng.choice(["circle", "rectangle", "line"])
            x1 = int(rng.randint(0, width))
            y1 = int(rng.randint(0, height))
            x2 = int(rng.randint(0, width))
            y2 = int(rng.randint(0, height))

            if x1 > x2:
                x1, x2 = x2, x1
            if y1 > y2:
                y1, y2 = y2, y1

            line_width = max(3, resolution // 100)

            if shape_type == "circle":
                draw.ellipse([x1, y1, x2, y2], outline=0, width=line_width)
            elif shape_type == "rectangle":
                draw.rectangle([x1, y1, x2, y2], outline=0, width=line_width)
            elif shape_type == "line":
                draw.line([x1, y1, x2, y2], fill=0, width=line_width)

        # Add detail lines based on detail_level
        for _ in range(max(6, detail_level)):
            x1 = int(rng.randint(0, width))
            y1 = int(rng.randint(0, height))
            x2 = int(rng.randint(0, width))
            y2 = int(rng.randint(0, height))
            draw.line([x1, y1, x2, y2], fill=0, width=max(2, resolution // 150))

        return img.convert("RGB")

    def _generate_colour_image(
        self,
        width: int,
        height: int,
        detail_level: int,
        rng: np.random.RandomState,
        category: str,
    ) -> Image.Image:
        """
        Generate a colourful image with distinct RGB channel variation.
        """
        arr = np.ones((height, width, 3), dtype=np.uint8) * 240

        for i in range(height):
            for c in range(3):
                arr[i, :, c] = np.clip(
                    arr[i, :, c].astype(int) - int(rng.randint(0, 30)) + (i * 50 // height),
                    0, 255
                ).astype(np.uint8)

        img = Image.fromarray(arr)
        draw = ImageDraw.Draw(img)

        resolution = min(width, height)
        num_shapes = max(5, detail_level // 3)
        colours = [
            (255, 100, 100),   # Red
            (100, 255, 100),   # Green
            (100, 100, 255),   # Blue
            (255, 200, 50),    # Yellow
            (200, 100, 255),   # Purple
            (100, 200, 200),   # Cyan
            (255, 150, 50),    # Orange
        ]

        for _ in range(num_shapes):
            colour = colours[int(rng.randint(0, len(colours)))]
            shape_type = rng.choice(["circle", "rectangle"])
            size = int(rng.randint(resolution // 10, resolution // 3))
            x = int(rng.randint(0, max(1, width - size)))
            y = int(rng.randint(0, max(1, height - size)))

            if shape_type == "circle":
                draw.ellipse([x, y, x + size, y + size], fill=colour, outline=(0, 0, 0))
            elif shape_type == "rectangle":
                draw.rectangle([x, y, x + size, y + size], fill=colour, outline=(0, 0, 0))

        return img
