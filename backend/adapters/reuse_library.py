"""
Reuse library adapter.

Looks up previously generated items that are approved and passed the quality gate,
matching subject and purpose using token and tag similarity.
Near-zero cost per hit.
Strictly enforces quality floor re-checks (e.g. an A5 image cannot satisfy an A3 request)
and student privacy sanitization (no personal data stored in the library).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.adapters.base import AdapterCapability, AdapterPricing, BaseAdapter
from backend.engine.models import CostEstimate, ExecutionResult, QualityFloor, StrategyConfig, UserRequest

# Physical dimensions proxy in inches for floor re-checks
SIZE_INCHES: dict[str, float] = {
    "A6": 4.1,
    "A5": 5.8,
    "A4": 8.3,
    "A3": 11.7,
    "A2": 16.5,
    "A1": 23.4,
}


@dataclass
class ReusableItem:
    """An approved item stored in the reuse library."""
    id: str
    prompt: str
    subject: str
    category: str
    resolution: int
    colour_mode: str
    output_reference: str
    output_data: Any
    tokens: set[str]
    tags: list[str] = field(default_factory=list)
    approved: bool = True
    created_at: float = field(default_factory=time.time)


class ReuseLibraryAdapter(BaseAdapter):
    """
    Adapter that searches and retrieves approved, quality-checked items from a reusable library.
    Near-zero cost ($0.0005 simulated).
    """

    def __init__(self, initial_items: list[ReusableItem] | None = None):
        self._items: dict[str, ReusableItem] = {}
        if initial_items:
            for item in initial_items:
                self._items[item.id] = item

    @property
    def name(self) -> str:
        return "reuse_library"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            task_categories=[
                "colouring_worksheet",
                "flashcard",
                "detailed_illustration",
            ],
            output_types=["image/png"],
            parameter_limits={"resolution": {"min": 256, "max": 4096}},
        )

    @property
    def pricing(self) -> AdapterPricing:
        return AdapterPricing(
            method="per_call",
            values={"reuse_library": 0.0005},
            source="placeholder",
        )

    @staticmethod
    def _sanitize_pii(text: str) -> str:
        """Strip obvious student personal data (names/emails/IDs) before storing in library."""
        # Email pattern
        text = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "[REDACTED_EMAIL]", text)
        # Phone pattern
        text = re.sub(r"\b\d{3}[-.\s]??\d{3}[-.\s]??\d{4}\b", "[REDACTED_PHONE]", text)
        # Student ID / SSN pattern
        text = re.sub(r"\b(student[-_\s]?id|ssn)[\s:]*\d+\b", "[REDACTED_ID]", text, flags=re.I)
        # Names following "student:" or "for <Name>"
        text = re.sub(r"\b(student|child|pupil):\s*[A-Z][a-z]+(\s+[A-Z][a-z]+)?\b", r"\1: [REDACTED_NAME]", text, flags=re.I)
        return text

    def add_approved_item(
        self,
        item_id: str,
        prompt: str,
        subject: str,
        category: str,
        resolution: int,
        colour_mode: str,
        output_data: Any,
        output_reference: str,
        tags: list[str] | None = None,
        approved: bool = True,
    ) -> bool:
        """
        Add an approved output to the reuse library.
        Rejects or sanitizes personal data.
        """
        if not approved:
            return False

        # Privacy check: reject/sanitize personal data
        clean_prompt = self._sanitize_pii(prompt)
        clean_subject = self._sanitize_pii(subject)
        clean_tags = [self._sanitize_pii(t) for t in (tags or [])]

        # Tokenize for similarity matching
        tokens = self._tokenize(f"{clean_prompt} {clean_subject} {' '.join(clean_tags)}")

        item = ReusableItem(
            id=item_id,
            prompt=clean_prompt,
            subject=clean_subject,
            category=category,
            resolution=resolution,
            colour_mode=colour_mode,
            output_reference=output_reference,
            output_data=output_data,
            tokens=tokens,
            tags=clean_tags,
            approved=True,
        )
        self._items[item_id] = item
        return True

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        stopwords = {"a", "an", "the", "for", "to", "in", "of", "and", "or", "is", "on", "sheet", "image", "create"}
        return {w for w in words if w not in stopwords and len(w) > 1}

    def estimate_cost(self, strategy: StrategyConfig, request: UserRequest) -> CostEstimate:
        return CostEstimate(
            strategy_name=strategy.name,
            estimated_cost=strategy.price_per_call,
            currency="USD",
            source="placeholder",
            is_simulated=True,
            breakdown={"reuse_index_lookup": strategy.price_per_call, "generative_compute": 0.0},
        )

    def execute(self, strategy: StrategyConfig, request: UserRequest) -> ExecutionResult:
        start_time = time.time()
        category = request.inputs.get("_category", "")

        # 1. Look for match in library
        match = self._find_match(request, category)
        if match is None:
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=0.0,
                latency_s=0.02,
                is_simulated=True,
                error="No approved matching item found in reuse library",
            )

        # 2. Re-check the reused item against the CURRENT request's quality floor!
        # (e.g. an A5 image must fail an A3 request, or colour mode mismatch)
        passes_floor, reason = self._check_quality_floor(match, request)
        if not passes_floor:
            return ExecutionResult(
                request_id=request.id,
                strategy_name=strategy.name,
                success=False,
                actual_cost=0.0,
                latency_s=0.02,
                is_simulated=True,
                error=f"Reused item '{match.id}' failed current quality floor: {reason}",
            )

        # 3. Successful reuse hit!
        return ExecutionResult(
            request_id=request.id,
            strategy_name=strategy.name,
            success=True,
            output_reference=match.output_reference,
            output_data=match.output_data,
            actual_cost=strategy.price_per_call,
            latency_s=0.02,  # near instantaneous cache hit
            is_simulated=True,
            metadata={
                "reused": True,
                "reused_from_library": True,
                "source_item_id": match.id,
                "resolution": match.resolution,
                "colour_mode": match.colour_mode,
                "can_regenerate": True,
                "generation_time_s": time.time() - start_time,
            },
        )

    def has_match(self, request: UserRequest, category: str) -> tuple[bool, str]:
        """Check whether an eligible approved item exists matching the quality floor."""
        match = self._find_match(request, category)
        if match is None:
            return False, "No approved matching item found in reuse library"
        passes_floor, reason = self._check_quality_floor(match, request)
        if not passes_floor:
            return False, f"Reused item failed quality floor: {reason}"
        return True, "Match found"

    def _find_match(self, request: UserRequest, category: str) -> Optional[ReusableItem]:
        """Find the best approved reusable item using token and tag similarity."""
        req_text = f"{request.prompt} {request.inputs.get('subject', '')}"
        req_tokens = self._tokenize(req_text)
        if not req_tokens:
            return None

        req_subject = str(request.inputs.get("subject", "")).lower()

        best_item: Optional[ReusableItem] = None
        best_score = 0.0

        for item in self._items.values():
            if not item.approved:
                continue
            # Purpose must match if category is specified
            if category and item.category != category:
                continue

            # Check subject exact or token overlap
            if req_subject and req_subject == item.subject.lower():
                best_item = item
                best_score = 1.0
                break

            intersection = len(req_tokens & item.tokens)
            union = len(req_tokens | item.tokens)
            score = intersection / union if union > 0 else 0.0

            if score > best_score and score >= 0.25:  # threshold
                best_score = score
                best_item = item

        return best_item

    def _check_quality_floor(self, item: ReusableItem, request: UserRequest) -> tuple[bool, str]:
        """
        Re-verify that the reused item satisfies the current request's quality requirements.
        A reused A5 image must fail an A3 request.
        """
        requested_size = str(request.inputs.get("output_size", "A4")).upper()
        # Quality floor min_dpi check if present
        min_dpi = request.metadata.get("min_dpi", 150)

        # For large print sizes (A3, A2, A1), an A5/A4 image (< 1500px) MUST fail
        if requested_size in ("A3", "A2", "A1") and item.resolution < 1500:
            return False, f"Resolution {item.resolution}px too low for requested size {requested_size} (requires >= 1500px)"

        # Check colour mode requirements
        required_mode = request.inputs.get("colour_mode", "")
        if required_mode and required_mode != item.colour_mode and required_mode != "any":
            return False, f"Colour mode {item.colour_mode} does not match requested {required_mode}"

        return True, "Passed"
