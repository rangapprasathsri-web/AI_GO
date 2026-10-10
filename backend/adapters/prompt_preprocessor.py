"""
Prompt Preprocessor and Model Router Adapter.

Uses Groq LLMs (with 3-tier failover: Primary -> Fallback -> 2nd Fallback)
to:
1. Determine the right-sized image model/LLM and quality tier for a user prompt.
2. Explain the suggestions and rationale (preventing compute and energy waste).
3. Generate a revised, value-added prompt optimized for the chosen model.
4. Provide structured improvements for user review and inline editing.
5. Provide an offline rule-based fallback if all keys are unavailable or offline.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional
import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert AI Model Router and Prompt Engineer for an Adaptive AI Resource Optimizer.
The system generates educational, classroom, and school materials while strictly minimizing unnecessary compute and energy waste.

Available Image Generation Models & Tiers:
- Economy Tier ('gemini-2.5-flash-image'): 512x512 resolution, lowest compute (~15-20 units). Ideal for coloring sheets, line art, simple drafts, basic icons, coloring worksheets.
- Standard Tier ('gemini-3.1-flash-image'): 768x768 to 1024x1024, medium compute (~40 units). Ideal for classroom diagrams, educational illustrations, flashcards, presentation slides.
- Maximum Tier ('gemini-3-pro-image'): 1024x1024+ HD, highest compute (~80-120 units). Ideal for print posters, fine artwork, complex multi-character compositions, exhibition materials.

When a user provides a prompt, you must:
1. Determine which Model & Tier to use (Right-sizing: select the lowest suitable tier that satisfies the requirement without waste).
2. Explain your suggestion clearly (why this model/tier fits best and avoids over-computation).
3. Create a revised, value-added prompt optimized for that specific model to yield highest quality results.
4. List 2-3 key improvements made to the user's prompt.

Return valid JSON with the following schema:
{
  "recommended_model": string (e.g. "gemini-2.5-flash-image", "gemini-3.1-flash-image", or "gemini-3-pro-image"),
  "recommended_tier": "economy" | "standard" | "maximum",
  "model_display_name": string (e.g. "Gemini 2.5 Flash (Economy Tier)"),
  "explanation": string (clear explanation of why this model/tier is recommended),
  "revised_prompt": string (enriched, value-added prompt ready for generation),
  "improvements": [string, string, string] (concise bullet points of improvements)
}
"""


class PromptPreprocessor:
    """Preprocesses user prompts and routes to optimal image models via Groq LLM."""

    GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
    DEFAULT_MODEL = "openai/gpt-oss-20b"

    def __init__(
        self,
        primary_key: Optional[str] = None,
        fallback_key: Optional[str] = None,
        fallback_key_2: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: float = 12.0,
    ):
        self.primary_key = primary_key if primary_key is not None else os.getenv("GROQ_API_KEY", "").strip()
        self.fallback_key = fallback_key if fallback_key is not None else os.getenv("GROQ_API_KEY_FALLBACK", "").strip()
        self.fallback_key_2 = fallback_key_2 if fallback_key_2 is not None else os.getenv("GROQ_API_KEY_FALLBACK_2", "").strip()
        self.model = model
        self.timeout = timeout
        self._cache: dict[str, dict[str, Any]] = {}

    def _get_key_candidates(self) -> list[tuple[str, str]]:
        candidates = []
        if self.primary_key:
            candidates.append(("primary", self.primary_key))
        if self.fallback_key:
            candidates.append(("fallback_1", self.fallback_key))
        if self.fallback_key_2:
            candidates.append(("fallback_2", self.fallback_key_2))
        return candidates

    def _strip_pii(self, text: str) -> str:
        text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[REDACTED_EMAIL]", text)
        text = re.sub(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[REDACTED_PHONE]", text)
        text = re.sub(r"\bstudent[_\s]?id[:\s]+\w+", "[REDACTED_ID]", text, flags=re.IGNORECASE)
        return text

    def _sanitize_log(self, text: str) -> str:
        for k in [self.primary_key, self.fallback_key, self.fallback_key_2]:
            if k:
                text = text.replace(k, "[REDACTED]")
        return text

    def preprocess(
        self,
        prompt: str,
        purpose: Optional[str] = None,
        print_size: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Analyze user prompt via Groq LLM with multi-key failover.
        Falls back to offline deterministic rule engine if all network calls fail.
        """
        clean_prompt = self._strip_pii(prompt.strip())
        cache_key = f"{purpose or 'default'}:{clean_prompt.lower()}"
        if cache_key in self._cache:
            res = dict(self._cache[cache_key])
            res["cached"] = True
            return res

        user_content = f"User Prompt: '{clean_prompt}'"
        if purpose:
            user_content += f"\nIntended Purpose: '{purpose}'"
        if print_size:
            user_content += f"\nTarget Print Size: '{print_size}'"

        candidates = self._get_key_candidates()
        for tier_label, api_key in candidates:
            try:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 600,
                    "temperature": 0.2,
                }
                resp = httpx.post(self.GROQ_ENDPOINT, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    content_str = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content_str)
                    result = {
                        "original_prompt": clean_prompt,
                        "recommended_model": parsed.get("recommended_model", "gemini-2.5-flash-image"),
                        "recommended_tier": parsed.get("recommended_tier", "economy").lower(),
                        "model_display_name": parsed.get("model_display_name", "Gemini 2.5 Flash (Economy Tier)"),
                        "explanation": parsed.get("explanation", "Right-sized model to minimize compute."),
                        "revised_prompt": parsed.get("revised_prompt", clean_prompt),
                        "improvements": parsed.get("improvements", ["Optimized prompt structure"]),
                        "provider_used": f"groq ({tier_label})",
                        "cached": False,
                    }
                    self._cache[cache_key] = result
                    return result
                else:
                    safe_msg = self._sanitize_log(resp.text[:200])
                    logger.warning("Groq (%s) returned status %d: %s", tier_label, resp.status_code, safe_msg)
            except Exception as e:
                safe_err = self._sanitize_log(str(e))
                logger.warning("Groq (%s) request failed: %s", tier_label, safe_err)

        # Offline deterministic fallback
        logger.info("Using offline deterministic prompt preprocessor fallback")
        return self._rule_based_fallback(clean_prompt, purpose, print_size)

    def _rule_based_fallback(
        self, prompt: str, purpose: Optional[str], print_size: Optional[str]
    ) -> dict[str, Any]:
        """Offline fallback ensuring zero downtime when network or external keys are absent."""
        p_lower = (prompt + " " + (purpose or "")).lower()
        if any(w in p_lower for w in ["color", "colour", "outline", "worksheet"]):
            tier = "economy"
            model = "gemini-2.5-flash-image"
            display = "Gemini 2.5 Flash (Economy Tier)"
            explanation = (
                "A line-art coloring worksheet requires clean, uncluttered outlines rather than complex shading. "
                "The Economy tier delivers sharp black-and-white contours at 75% compute savings."
            )
            revised = f"Clear black and white coloring book outline of {prompt}, clean bold contour line art, child-friendly shapes, zero shading, pure white background"
            improvements = [
                "Specified coloring book outline style with clean contours",
                "Explicitly excluded color and complex gradients",
                "Optimized for high-contrast black and white print",
            ]
        elif any(w in p_lower for w in ["poster", "banner", "fine art", "print", "exhibition"]):
            tier = "maximum"
            model = "gemini-3-pro-image"
            display = "Gemini 3 Pro (Maximum Tier)"
            explanation = (
                "Large format and exhibition prints require fine textures and maximum detail density. "
                "The Maximum tier provides premium resolution and detailed fidelity."
            )
            revised = f"High-detail exhibition grade artwork of {prompt}, masterwork quality, rich color depth, sharp textures, high resolution"
            improvements = [
                "Enhanced detail density for large format print fidelity",
                "Added rich color depth and textural clarity markers",
            ]
        else:
            tier = "standard"
            model = "gemini-3.1-flash-image"
            display = "Gemini 3.1 Flash (Standard Tier)"
            explanation = (
                "Educational visuals and presentation graphics require balanced clarity without over-computation. "
                "The Standard tier ensures pedagogical clarity while conserving resources."
            )
            revised = f"Educational instructional visual of {prompt}, balanced vibrant colors, clean subject isolation, pedagogical clarity"
            improvements = [
                "Added instructional layout guidelines",
                "Enhanced color balance and subject focus",
            ]

        return {
            "original_prompt": prompt,
            "recommended_model": model,
            "recommended_tier": tier,
            "model_display_name": display,
            "explanation": explanation,
            "revised_prompt": revised,
            "improvements": improvements,
            "provider_used": "rule_based_fallback",
            "cached": False,
        }
