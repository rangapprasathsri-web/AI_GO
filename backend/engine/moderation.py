"""
Moderation hook module.

Runs on prompt before execution and on output after execution.
Blocks and logs content that fails moderation. In the mock implementation,
uses keyword and rules-based checks.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from backend.engine.models import UserRequest


class ModerationResult:
    """Result of a moderation check."""

    def __init__(
        self,
        passed: bool,
        blocked_reason: Optional[str] = None,
        flagged_terms: Optional[list[str]] = None,
        check_type: str = "unknown",
    ):
        self.passed = passed
        self.blocked_reason = blocked_reason
        self.flagged_terms = flagged_terms or []
        self.check_type = check_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "blocked_reason": self.blocked_reason,
            "flagged_terms": self.flagged_terms,
            "check_type": self.check_type,
        }


class ModerationHook:
    """
    Moderation hook that runs before and after execution.
    Uses keyword and pattern-based checks in the mock implementation.
    """

    # Blocked terms for child safety (basic list for demonstration)
    BLOCKED_TERMS = [
        "violence", "violent", "weapon", "weapons", "gore",
        "explicit", "inappropriate", "harmful", "dangerous",
        "drug", "drugs", "alcohol", "tobacco", "smoking",
    ]

    # Personal data patterns
    PERSONAL_DATA_PATTERNS = [
        # Email addresses
        (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', "email address"),
        # Phone numbers (various formats)
        (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', "phone number"),
        # SSN-like patterns
        (r'\b\d{3}-\d{2}-\d{4}\b', "SSN-like number"),
        # Student ID patterns (common formats)
        (r'\bstudent[_\s]?id[:\s]+\w+', "student ID reference"),
    ]

    # Name-in-context patterns (heuristic: "student named X", "for John Smith", "student: John Smith", etc.)
    NAME_CONTEXT_PATTERNS = [
        r'\b(?:student|child|kid|pupil)\s+(?:named?|called)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        r'\bfor\s+(?:student|child)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        r'\b(?:student|child|pupil)[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
    ]

    def check_prompt(self, request: UserRequest) -> ModerationResult:
        """Check the request prompt before execution."""
        prompt = request.prompt
        inputs = request.inputs or {}

        # Check for blocked terms
        flagged = []
        prompt_lower = prompt.lower()
        for term in self.BLOCKED_TERMS:
            if term in prompt_lower:
                flagged.append(term)

        if flagged:
            return ModerationResult(
                passed=False,
                blocked_reason=f"Prompt contains blocked terms: {', '.join(flagged)}",
                flagged_terms=flagged,
                check_type="prompt_content",
            )

        # Check for personal data in prompt
        for pattern, data_type in self.PERSONAL_DATA_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                return ModerationResult(
                    passed=False,
                    blocked_reason=f"Prompt may contain {data_type}. Personal data must not be included in prompts.",
                    flagged_terms=[data_type],
                    check_type="personal_data",
                )

        # Check for personal data in inputs
        for key, value in inputs.items():
            if isinstance(value, str):
                for pattern, data_type in self.PERSONAL_DATA_PATTERNS:
                    if re.search(pattern, value, re.IGNORECASE):
                        return ModerationResult(
                            passed=False,
                            blocked_reason=f"Input '{key}' may contain {data_type}. Personal data must not be included.",
                            flagged_terms=[data_type],
                            check_type="personal_data",
                        )

        # Check for name-in-context patterns
        for pattern in self.NAME_CONTEXT_PATTERNS:
            match = re.search(pattern, prompt)
            if match:
                return ModerationResult(
                    passed=False,
                    blocked_reason=f"Prompt appears to reference a student by name. Personal data must not be included in prompts.",
                    flagged_terms=["student name"],
                    check_type="personal_data",
                )

        return ModerationResult(
            passed=True,
            check_type="prompt_content",
        )

    def check_output(self, output_data: Any) -> ModerationResult:
        """Check the output after execution."""
        # For mock: check if output metadata indicates issues
        if isinstance(output_data, dict):
            metadata = output_data.get("metadata", {})
            if metadata.get("moderation_flag"):
                return ModerationResult(
                    passed=False,
                    blocked_reason="Output flagged by moderation: " + str(metadata.get("moderation_reason", "unspecified")),
                    check_type="output_content",
                )

        return ModerationResult(
            passed=True,
            check_type="output_content",
        )
