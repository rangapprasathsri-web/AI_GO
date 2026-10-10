"""
Request analysis module - rules-based task classification.

Uses keywords and input patterns to classify requests into task categories.
Returns clarification questions when confidence is low or categories are ambiguous.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from backend.engine.models import AnalysisResult, DomainConfig, TaskCategory, UserRequest


class AnalysisInterface(ABC):
    """Abstract interface for request analysis."""

    @abstractmethod
    def analyse(
        self, request: UserRequest, config: DomainConfig
    ) -> AnalysisResult:
        """Analyse a request and determine its task category."""
        ...


class RulesBasedAnalyser(AnalysisInterface):
    """
    Rules-based analyser using keywords and input patterns.
    
    Classification logic:
    1. Score each category by keyword matches in the prompt.
    2. If a clear winner exists (score gap >= 1), assign it.
    3. If two categories tie or gap < 1, mark as ambiguous.
    4. Check for missing required inputs.
    5. If category is ambiguous after scoring, return clarification question.
    """

    def analyse(
        self, request: UserRequest, config: DomainConfig
    ) -> AnalysisResult:
        prompt_lower = request.prompt.lower()
        inputs = request.inputs or {}

        # If user explicitly selected category with one-tap purpose selection
        explicit_cat = inputs.get("_category")
        if explicit_cat and explicit_cat in config.task_categories:
            cat_obj = config.task_categories[explicit_cat]
            missing = [i for i in cat_obj.required_inputs if i not in inputs]
            return AnalysisResult(
                category=explicit_cat,
                confidence=1.0,
                matched_keywords=["one_tap_selection"],
                is_ambiguous=False,
                missing_inputs=missing,
            )

        # Score each category
        scores: list[tuple[str, int, list[str]]] = []
        for cat_name, category in config.task_categories.items():
            score = 0
            matched = []
            for keyword in category.keywords:
                if keyword.lower() in prompt_lower:
                    score += 1
                    matched.append(keyword)
            scores.append((cat_name, score, matched))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)

        if not scores:
            return AnalysisResult(
                is_ambiguous=True,
                clarification_question="No task categories are configured for this domain. Please contact an administrator.",
            )

        top_name, top_score, top_matched = scores[0]

        # Check for ambiguity
        is_ambiguous = False
        alternative_categories = []
        if top_score == 0:
            # No keywords matched at all
            is_ambiguous = True
        elif len(scores) > 1:
            second_name, second_score, _ = scores[1]
            if second_score > 0 and (top_score - second_score) < 1:
                # Tie or near-tie
                is_ambiguous = True
                alternative_categories = [s[0] for s in scores if s[1] > 0 and s[0] != top_name]

        if is_ambiguous and top_score == 0:
            # No match at all - fall back to the one-tap question rather than guessing
            options = [
                c.replace("_", " ").title()
                for c in config.task_categories.keys()
            ]
            options.append("Other")
            formatted = ", ".join(options)
            return AnalysisResult(
                is_ambiguous=True,
                clarification_question=f"What is this for? Options: {formatted}",
                alternative_categories=list(config.task_categories.keys()) + ["other"],
                confidence=0.0,
            )

        if is_ambiguous:
            # Multiple matches - fall back to the one-tap question
            all_matching = [s[0] for s in scores if s[1] > 0]
            options = [c.replace("_", " ").title() for c in all_matching] + ["Other"]
            formatted = ", ".join(options)
            return AnalysisResult(
                category=top_name,
                confidence=0.5,
                matched_keywords=top_matched,
                is_ambiguous=True,
                clarification_question=f"What is this for? Options: {formatted}",
                alternative_categories=alternative_categories,
            )

        # Clear winner
        category = config.task_categories[top_name]
        confidence = min(1.0, top_score / max(len(category.keywords), 1))

        # Check for missing required inputs
        missing_inputs = []
        for req_input in category.required_inputs:
            if req_input not in inputs or inputs[req_input] is None:
                missing_inputs.append(req_input)

        clarification = None
        if missing_inputs:
            formatted = ", ".join(missing_inputs)
            clarification = (
                f"For a {top_name.replace('_', ' ')}, I need: {formatted}. "
                f"Please provide these details."
            )

        return AnalysisResult(
            category=top_name,
            confidence=confidence,
            matched_keywords=top_matched,
            is_ambiguous=False,
            missing_inputs=missing_inputs,
            clarification_question=clarification,
            alternative_categories=[s[0] for s in scores[1:] if s[1] > 0],
        )


class LLMAnalyser(AnalysisInterface):
    """
    P2: LLM-based analyser behind the same interface.
    Falls back to rules-based when LLM is unavailable.
    """

    def __init__(self, fallback: Optional[AnalysisInterface] = None):
        self.fallback = fallback or RulesBasedAnalyser()

    def analyse(
        self, request: UserRequest, config: DomainConfig
    ) -> AnalysisResult:
        # P2: Would call an LLM here
        # For now, delegate to fallback
        return self.fallback.analyse(request, config)
