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
                prompt=request.prompt,
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
        prompt: str = "",
    ) -> Image.Image:
        """
        Generate a synthetic image with characteristics matching the strategy.
        Prompt-aware so subjects like 'cute cat' produce recognizable illustrations.
        Always stamped with a prominent DEMO PLACEHOLDER mark.
        """
        prompt_lower = (prompt or "").lower()
        if is_bw:
            img = self._generate_bw_image(width, height, detail_level, rng, category, prompt_lower)
        else:
            img = self._generate_colour_image(width, height, detail_level, rng, category, prompt_lower)

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
        prompt_lower: str = "",
    ) -> Image.Image:
        """
        Generate a clean black-and-white outline image.
        Ink coverage is controlled within typical colouring sheet range (3-25%).
        """
        img = Image.new("L", (width, height), 255)
        draw = ImageDraw.Draw(img)
        res = min(width, height)
        line_w = max(3, res // 120)

        if "cat" in prompt_lower or "kitten" in prompt_lower or "feline" in prompt_lower:
            self._draw_cat_bw(draw, width, height, line_w, detail_level)
        elif "space" in prompt_lower or "planet" in prompt_lower or "solar" in prompt_lower or "galaxy" in prompt_lower:
            self._draw_space_bw(draw, width, height, line_w, detail_level)
        elif "mountain" in prompt_lower or "landscape" in prompt_lower or "sun" in prompt_lower:
            self._draw_landscape_bw(draw, width, height, line_w, detail_level)
        else:
            self._draw_scenic_bw(draw, width, height, line_w, detail_level, rng)

        return img.convert("RGB")

    def _draw_cat_bw(self, draw: ImageDraw.ImageDraw, width: int, height: int, line_w: int, detail: int):
        cx, cy = width // 2, height // 2
        r = int(min(width, height) * 0.28)

        # Cat head
        draw.ellipse([cx - r, cy - int(r*0.8), cx + r, cy + int(r*0.9)], outline=0, width=line_w)

        # Ears (triangles)
        ear_offset = int(r * 0.7)
        ear_h = int(r * 0.9)
        draw.polygon([(cx - ear_offset, cy - int(r*0.4)), (cx - int(ear_offset*1.1), cy - ear_h), (cx - int(ear_offset*0.2), cy - int(r*0.7))], outline=0)
        draw.polygon([(cx + ear_offset, cy - int(r*0.4)), (cx + int(ear_offset*1.1), cy - ear_h), (cx + int(ear_offset*0.2), cy - int(r*0.7))], outline=0)

        # Inner ears
        draw.line([(cx - int(ear_offset*0.85), cy - int(r*0.4)), (cx - int(ear_offset*0.95), cy - int(ear_h*0.85))], fill=0, width=max(2, line_w-1))
        draw.line([(cx + int(ear_offset*0.85), cy - int(r*0.4)), (cx + int(ear_offset*0.95), cy - int(ear_h*0.85))], fill=0, width=max(2, line_w-1))

        # Eyes (large round eyes with shine for cuteness)
        eye_r = int(r * 0.16)
        eye_y = cy - int(r * 0.05)
        draw.ellipse([cx - int(r*0.5) - eye_r, eye_y - eye_r, cx - int(r*0.5) + eye_r, eye_y + eye_r], fill=0)
        draw.ellipse([cx + int(r*0.5) - eye_r, eye_y - eye_r, cx + int(r*0.5) + eye_r, eye_y + eye_r], fill=0)
        # Eye shine
        shine_r = max(2, eye_r // 3)
        draw.ellipse([cx - int(r*0.5) - shine_r, eye_y - eye_r + 2, cx - int(r*0.5) + shine_r, eye_y - eye_r + 2 + shine_r*2], fill=255)
        draw.ellipse([cx + int(r*0.5) - shine_r, eye_y - eye_r + 2, cx + int(r*0.5) + shine_r, eye_y - eye_r + 2 + shine_r*2], fill=255)

        # Nose
        nose_y = cy + int(r * 0.25)
        nose_w = int(r * 0.1)
        draw.polygon([(cx - nose_w, nose_y), (cx + nose_w, nose_y), (cx, nose_y + nose_w)], fill=0)

        # Mouth
        draw.arc([cx - int(r*0.25), nose_y + int(nose_w*0.5), cx, nose_y + int(r*0.3)], start=0, end=180, fill=0, width=line_w)
        draw.arc([cx, nose_y + int(nose_w*0.5), cx + int(r*0.25), nose_y + int(r*0.3)], start=0, end=180, fill=0, width=line_w)

        # Whiskers (3 on each side)
        for dy in (-int(r*0.08), 0, int(r*0.08)):
            draw.line([(cx - int(r*0.45), nose_y + dy), (cx - int(r*1.3), nose_y + dy*2)], fill=0, width=max(2, line_w-1))
            draw.line([(cx + int(r*0.45), nose_y + dy), (cx + int(r*1.3), nose_y + dy*2)], fill=0, width=max(2, line_w-1))

        # Body outline below head
        draw.arc([cx - int(r*1.1), cy + int(r*0.5), cx + int(r*1.1), cy + int(r*1.8)], start=0, end=180, fill=0, width=line_w)

    def _draw_space_bw(self, draw: ImageDraw.ImageDraw, width: int, height: int, line_w: int, detail: int):
        cx, cy = width // 2, height // 2
        r = int(min(width, height) * 0.25)
        # Main planet
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=line_w)
        # Ring around planet
        draw.ellipse([cx - int(r*1.8), cy - int(r*0.4), cx + int(r*1.8), cy + int(r*0.4)], outline=0, width=line_w)
        # Moons & stars
        for i in range(min(12, max(6, detail))):
            sx = (cx * (i + 1) * 37) % (width - 40) + 20
            sy = (cy * (i + 1) * 59) % (height - 80) + 40
            draw.line([(sx - 8, sy), (sx + 8, sy)], fill=0, width=max(2, line_w-1))
            draw.line([(sx, sy - 8), (sx, sy + 8)], fill=0, width=max(2, line_w-1))

    def _draw_landscape_bw(self, draw: ImageDraw.ImageDraw, width: int, height: int, line_w: int, detail: int):
        # Mountains
        pts1 = [(0, int(height*0.7)), (int(width*0.35), int(height*0.35)), (int(width*0.7), int(height*0.75))]
        pts2 = [(int(width*0.3), int(height*0.75)), (int(width*0.65), int(height*0.28)), (width, int(height*0.7))]
        draw.line(pts1, fill=0, width=line_w)
        draw.line(pts2, fill=0, width=line_w)
        # Rising sun
        draw.arc([int(width*0.7), int(height*0.12), int(width*0.9), int(height*0.32)], start=0, end=360, fill=0, width=line_w)
        # Ground
        draw.line([(0, int(height*0.72)), (width, int(height*0.72))], fill=0, width=line_w)

    def _draw_scenic_bw(self, draw: ImageDraw.ImageDraw, width: int, height: int, line_w: int, detail: int, rng: np.random.RandomState):
        cx, cy = width // 2, height // 2
        # Stylized artistic sun and rolling hills
        draw.ellipse([cx - int(width*0.2), int(height*0.15), cx + int(width*0.2), int(height*0.55)], outline=0, width=line_w)
        draw.arc([0, int(height*0.45), int(width*0.8), int(height*0.9)], start=180, end=360, fill=0, width=line_w)
        draw.arc([int(width*0.3), int(height*0.55), width, int(height*0.95)], start=180, end=360, fill=0, width=line_w)
        # Detail waves/birds
        for i in range(max(4, detail // 3)):
            bx = int(rng.randint(int(width*0.1), int(width*0.85)))
            by = int(rng.randint(int(height*0.1), int(height*0.35)))
            draw.arc([bx, by, bx + 24, by + 16], start=180, end=360, fill=0, width=max(2, line_w-1))
            draw.arc([bx + 24, by, bx + 48, by + 16], start=180, end=360, fill=0, width=max(2, line_w-1))

    def _generate_colour_image(
        self,
        width: int,
        height: int,
        detail_level: int,
        rng: np.random.RandomState,
        category: str,
        prompt_lower: str = "",
    ) -> Image.Image:
        """
        Generate a colourful artwork with subject awareness and rich palette.
        """
        img = Image.new("RGB", (width, height), (248, 245, 255))
        draw = ImageDraw.Draw(img)
        res = min(width, height)

        if "cat" in prompt_lower or "kitten" in prompt_lower or "feline" in prompt_lower:
            # Cute pastel gradient background
            for y in range(height):
                r = int(245 + (10 * y / height))
                g = int(235 - (20 * y / height))
                b = int(250 - (10 * y / height))
                draw.line([(0, y), (width, y)], fill=(r, g, b))

            cx, cy = width // 2, height // 2
            cr = int(res * 0.28)
            # Body & paws
            draw.ellipse([cx - int(cr*0.9), cy + int(cr*0.3), cx + int(cr*0.9), cy + int(cr*1.4)], fill=(255, 205, 160), outline=(50, 40, 40), width=4)
            # Head
            draw.ellipse([cx - cr, cy - int(cr*0.8), cx + cr, cy + int(cr*0.9)], fill=(255, 215, 175), outline=(50, 40, 40), width=4)
            # Ears
            draw.polygon([(cx - int(cr*0.7), cy - int(cr*0.4)), (cx - int(cr*1.1), cy - int(cr*0.9)), (cx - int(cr*0.2), cy - int(cr*0.7))], fill=(255, 200, 160), outline=(50, 40, 40))
            draw.polygon([(cx + int(cr*0.7), cy - int(cr*0.4)), (cx + int(cr*1.1), cy - int(cr*0.9)), (cx + int(cr*0.2), cy - int(cr*0.7))], fill=(255, 200, 160), outline=(50, 40, 40))
            # Inner pink ears
            draw.polygon([(cx - int(cr*0.65), cy - int(cr*0.45)), (cx - int(cr*0.95), cy - int(cr*0.8)), (cx - int(cr*0.3), cy - int(cr*0.65))], fill=(255, 170, 180))
            draw.polygon([(cx + int(cr*0.65), cy - int(cr*0.45)), (cx + int(cr*0.95), cy - int(cr*0.8)), (cx + int(cr*0.3), cy - int(cr*0.65))], fill=(255, 170, 180))
            # Cheeks
            draw.ellipse([cx - int(cr*0.7), cy + int(cr*0.1), cx - int(cr*0.4), cy + int(cr*0.35)], fill=(255, 190, 200))
            draw.ellipse([cx + int(cr*0.4), cy + int(cr*0.1), cx + int(cr*0.7), cy + int(cr*0.35)], fill=(255, 190, 200))
            # Eyes (sparkly)
            eye_r = int(cr * 0.16)
            eye_y = cy - int(cr * 0.05)
            draw.ellipse([cx - int(cr*0.45) - eye_r, eye_y - eye_r, cx - int(cr*0.45) + eye_r, eye_y + eye_r], fill=(30, 30, 40))
            draw.ellipse([cx + int(cr*0.45) - eye_r, eye_y - eye_r, cx + int(cr*0.45) + eye_r, eye_y + eye_r], fill=(30, 30, 40))
            draw.ellipse([cx - int(cr*0.45) - 3, eye_y - eye_r + 4, cx - int(cr*0.45) + 5, eye_y - eye_r + 12], fill=(255, 255, 255))
            draw.ellipse([cx + int(cr*0.45) - 3, eye_y - eye_r + 4, cx + int(cr*0.45) + 5, eye_y - eye_r + 12], fill=(255, 255, 255))
            # Nose
            draw.polygon([(cx - 10, cy + int(cr*0.2)), (cx + 10, cy + int(cr*0.2)), (cx, cy + int(cr*0.2) + 12)], fill=(255, 120, 150))
            # Collar
            draw.rectangle([cx - int(cr*0.6), cy + int(cr*0.75), cx + int(cr*0.6), cy + int(cr*0.85)], fill=(110, 52, 226))
            draw.ellipse([cx - 10, cy + int(cr*0.85), cx + 10, cy + int(cr*0.85) + 20], fill=(255, 215, 0))
        else:
            # Scenic poster gradient with sunset and mountains
            for y in range(height):
                r = int(70 + (160 * y / height))
                g = int(30 + (120 * y / height))
                b = int(120 + (80 * y / height))
                draw.line([(0, y), (width, y)], fill=(r, g, b))

            # Sun
            draw.ellipse([width//2 - res//5, int(height*0.2), width//2 + res//5, int(height*0.2) + int(res*0.4)], fill=(255, 220, 100))
            # Mountains
            draw.polygon([(0, height), (int(width*0.35), int(height*0.45)), (int(width*0.7), height)], fill=(40, 25, 60))
            draw.polygon([(int(width*0.3), height), (int(width*0.7), int(height*0.38)), (width, height)], fill=(60, 35, 90))

        return img
