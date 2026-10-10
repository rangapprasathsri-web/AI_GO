"""
LLM Intent Service Adapter.

Provides structured intent analysis behind an abstract interface.
Rules-first fallback guarantees the engine works with no LLM and no credentials.
Extracts:
- Task type and intended purpose
- Extracted facts vs inferred preferences
- Complexity & quality indicators
- Missing information and ambiguities
- Prompt injection defense & student PII rejection
- Tracks analysis overhead cost and latency
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from backend.engine.models import (
    DataOrigin,
    DomainConfig,
    ExtractedConstraints,
    LLMStructuredIntent,
    UserRequest,
)


class LLMIntentAdapterInterface(ABC):
    """Abstract interface for LLM intent analysis."""

    @abstractmethod
    def analyze(
        self, request: UserRequest, config: DomainConfig
    ) -> LLMStructuredIntent:
        """Analyze a request and return structured intent."""
        ...


class LLMProviderError(Exception):
    """Raised when an external LLM provider fails."""
    pass


class LLMTimeoutError(LLMProviderError):
    """Raised when an LLM request times out."""
    pass


class LLMMalformedOutputError(LLMProviderError):
    """Raised when LLM returns invalid or unparseable JSON."""
    pass


class MockLLMIntentAdapter(LLMIntentAdapterInterface):
    """
    Mock LLM intent adapter that validates structured outputs offline.
    Supports timeout simulation, provider failure simulation, prompt injection detection,
    and request caching.
    """

    INJECTION_PATTERNS = [
        r"ignore\s+(?:all\s+)?previous\s+instructions",
        r"system\s*:\s*override",
        r"disregard\s+budget",
        r"set\s+policy\s+to\s+baseline_always_max",
        r"bypass\s+quality\s+floor",
        r"you\s+are\s+now\s+in\s+developer\s+mode",
    ]

    def __init__(
        self,
        simulate_timeout: bool = False,
        simulate_unavailable: bool = False,
        simulate_malformed: bool = False,
        overhead_cost: float = 0.001,
        overhead_latency_s: float = 0.15,
    ):
        self.simulate_timeout = simulate_timeout
        self.simulate_unavailable = simulate_unavailable
        self.simulate_malformed = simulate_malformed
        self.overhead_cost = overhead_cost
        self.overhead_latency_s = overhead_latency_s
        self._cache: dict[str, LLMStructuredIntent] = {}

    def _normalize_prompt(self, prompt: str) -> str:
        return " ".join(prompt.strip().lower().split())

    def _detect_prompt_injection(self, text: str) -> bool:
        for pat in self.INJECTION_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return False

    def _strip_pii(self, text: str) -> str:
        # Mask emails
        text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[REDACTED_EMAIL]', text)
        # Mask phones
        text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[REDACTED_PHONE]', text)
        # Mask student IDs
        text = re.sub(r'\bstudent[_\s]?id[:\s]+\w+', '[REDACTED_ID]', text, flags=re.IGNORECASE)
        return text

    def analyze(
        self, request: UserRequest, config: DomainConfig
    ) -> LLMStructuredIntent:
        """
        Analyze prompt text, protect against prompt injection,
        validate against strict Pydantic model, and cache.
        """
        # 1. Simulate failure cases if configured
        if self.simulate_unavailable:
            raise LLMProviderError("LLM provider service is temporarily unavailable (HTTP 503)")

        if self.simulate_timeout:
            raise LLMTimeoutError("LLM provider request timed out after 3.0s")

        if self.simulate_malformed:
            raise LLMMalformedOutputError("LLM output is malformed: Unexpected token < in JSON at position 0")

        # 2. Check cache
        norm_key = f"{request.domain}:{self._normalize_prompt(request.prompt)}"
        if norm_key in self._cache:
            return self._cache[norm_key]

        start_time = time.time()

        # 3. Privacy: strip PII before sending
        sanitized_prompt = self._strip_pii(request.prompt)

        # 4. Prompt injection defense
        has_injection = self._detect_prompt_injection(request.prompt)

        prompt_lower = sanitized_prompt.lower()
        extracted_facts: dict[str, Any] = {}
        inferred_prefs: dict[str, Any] = {}
        missing_info: list[str] = []
        requires_clarification = False
        clarification_q = None

        # Check domain and match intent
        category = None
        task_type = "image_generation"
        quality_req = "standard"

        # Explicit detection
        if "colour" in prompt_lower or "coloring" in prompt_lower or "outline" in prompt_lower or "worksheet" in prompt_lower:
            task_type = "worksheet_creation"
            category = "colouring_worksheet"
            quality_req = "low"
            extracted_facts["line_art"] = True
            extracted_facts["colour_mode"] = "bw"
            inferred_prefs["paper_size"] = "A4"
        elif "flashcard" in prompt_lower or "vocabulary card" in prompt_lower or "study card" in prompt_lower:
            task_type = "card_creation"
            category = "flashcard"
            quality_req = "standard"
            extracted_facts["card_format"] = "4x6"
            extracted_facts["colour_mode"] = "colour"
        elif "banner" in prompt_lower or "poster" in prompt_lower or "annual report" in prompt_lower:
            task_type = "large_format_print"
            category = "printed_banner"
            quality_req = "print"
            extracted_facts["print_scale"] = "A1"
            extracted_facts["dpi"] = 300
        elif "illustration" in prompt_lower or "diagram" in prompt_lower:
            task_type = "classroom_visual"
            category = "detailed_illustration"
            quality_req = "standard"
            extracted_facts["colour_mode"] = "colour"
        else:
            # Ambiguous or non-image
            if "summarize" in prompt_lower or "summary" in prompt_lower:
                task_type = "text_summarization"
                category = "brief_summary"
                quality_req = "standard"
            else:
                task_type = "general_request"
                category = None
                requires_clarification = True
                clarification_q = "What is this for? Options: Colouring sheet, Flashcard, Classroom illustration, Poster or banner, Other"
                missing_info.append("intended_purpose")

        # Injected prompt safety: if prompt tried to override budget or policy, neutralise it!
        constraints = ExtractedConstraints(
            max_budget=request.max_budget,
            max_latency_ms=(request.max_latency * 1000) if request.max_latency else None,
            required_colour_mode=extracted_facts.get("colour_mode"),
            target_size=extracted_facts.get("paper_size") or extracted_facts.get("card_format") or extracted_facts.get("print_scale"),
        )

        reasoning = (
            f"Extracted task '{task_type}' with quality tier '{quality_req}'. "
            f"{'Prompt injection detected and neutralized. ' if has_injection else ''}"
            f"Observable keywords: {', '.join(k for k in ['colouring', 'flashcard', 'banner', 'illustration'] if k in prompt_lower)}."
        )

        intent = LLMStructuredIntent(
            task_type=task_type,
            intended_use=sanitized_prompt,
            task_category=category,
            quality_requirement=quality_req,
            constraints=constraints,
            missing_information=missing_info,
            requires_clarification=requires_clarification,
            clarification_question=clarification_q,
            extracted_facts=extracted_facts,
            inferred_preferences=inferred_prefs,
            reasoning_summary=reasoning,
            overhead_cost=self.overhead_cost,
            overhead_latency_s=self.overhead_latency_s,
            data_origin=DataOrigin.SIMULATED,
        )

        # Cache
        self._cache[norm_key] = intent
        return intent
