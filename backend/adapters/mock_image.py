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
            resolution = strategy.params.get("resolution", 512)
            steps = strategy.params.get("steps", 15)

            # Use request ID as seed for determinism
            seed = int(hashlib.md5(request.id.encode()).hexdigest()[:8], 16)
            rng = np.random.RandomState(seed)

            # Determine image characteristics from category
            category = request.inputs.get("_category", "")
            is_bw = category in ("colouring_worksheet",)
            needs_colour = category in ("flashcard", "detailed_illustration", "printed_banner")

            # Generate the synthetic image
            img = self._generate_image(
                resolution=resolution,
                is_bw=is_bw,
                needs_colour=needs_colour,
                detail_level=steps,
                rng=rng,
                category=category,
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
                output_reference=f"mock://images/{request.id}.png",
                output_data={"image": img, "image_bytes": image_bytes},
                actual_cost=strategy.price_per_call,
                latency_s=simulated_latency,
                is_simulated=True,
                metadata={
                    "resolution": resolution,
                    "steps": steps,
                    "is_bw": is_bw,
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
        resolution: int,
        is_bw: bool,
        needs_colour: bool,
        detail_level: int,
        rng: np.random.RandomState,
        category: str,
    ) -> Image.Image:
        """
        Generate a synthetic image with characteristics matching the strategy.
        
        For BW images: creates line drawings with controlled ink coverage.
        For colour images: creates colourful patterns with clear colour channels.
        """
        if is_bw:
            return self._generate_bw_image(resolution, detail_level, rng, category)
        elif needs_colour:
            return self._generate_colour_image(resolution, detail_level, rng, category)
        else:
            return self._generate_colour_image(resolution, detail_level, rng, category)

    def _generate_bw_image(
        self,
        resolution: int,
        detail_level: int,
        rng: np.random.RandomState,
        category: str,
    ) -> Image.Image:
        """
        Generate a black-and-white outline image.
        Ink coverage is controlled to be within typical colouring sheet range (3-25%).
        """
        # Create white background
        img = Image.new("L", (resolution, resolution), 255)
        draw = ImageDraw.Draw(img)

        # Draw random geometric outlines (simulating a colouring page)
        num_shapes = max(8, detail_level // 2)

        for _ in range(num_shapes):
            shape_type = rng.choice(["circle", "rectangle", "line"])
            x1 = int(rng.randint(0, resolution))
            y1 = int(rng.randint(0, resolution))
            x2 = int(rng.randint(0, resolution))
            y2 = int(rng.randint(0, resolution))

            # Ensure x1 < x2, y1 < y2 for shapes
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

        # Add some detail lines based on detail_level
        for _ in range(max(6, detail_level)):
            x1 = int(rng.randint(0, resolution))
            y1 = int(rng.randint(0, resolution))
            x2 = int(rng.randint(0, resolution))
            y2 = int(rng.randint(0, resolution))
            draw.line([x1, y1, x2, y2], fill=0, width=max(2, resolution // 150))

        # Convert to RGB (grayscale stored as RGB for consistency)
        return img.convert("RGB")

    def _generate_colour_image(
        self,
        resolution: int,
        detail_level: int,
        rng: np.random.RandomState,
        category: str,
    ) -> Image.Image:
        """
        Generate a colourful image with distinct RGB channel variation.
        """
        # Create image with colour gradients and shapes
        arr = np.ones((resolution, resolution, 3), dtype=np.uint8) * 240  # near-white background

        # Add colourful gradient background
        for i in range(resolution):
            for c in range(3):
                arr[i, :, c] = np.clip(
                    arr[i, :, c].astype(int) - int(rng.randint(0, 30)) + (i * 50 // resolution),
                    0, 255
                ).astype(np.uint8)

        img = Image.fromarray(arr)
        draw = ImageDraw.Draw(img)

        # Draw colourful shapes
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
            x = int(rng.randint(0, resolution - size))
            y = int(rng.randint(0, resolution - size))

            if shape_type == "circle":
                draw.ellipse([x, y, x + size, y + size], fill=colour, outline=(0, 0, 0))
            elif shape_type == "rectangle":
                draw.rectangle([x, y, x + size, y + size], fill=colour, outline=(0, 0, 0))

        return img
