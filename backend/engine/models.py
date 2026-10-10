"""
Core data models for the Adaptive Request Optimizer engine.

These are domain-agnostic models used throughout the engine.
They MUST NOT reference any specific domain, adapter, or API code.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ──────────────────────────────────────────────────────────────

class RequestStatus(str, Enum):
    PENDING = "pending"
    ANALYSED = "analysed"
    DECIDED = "decided"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    MODERATION_BLOCKED = "moderation_blocked"
    BUDGET_EXCEEDED = "budget_exceeded"


class ColourMode(str, Enum):
    BW = "bw"
    COLOUR = "colour"
    ANY = "any"


class PolicyName(str, Enum):
    BASELINE_ALWAYS_MAX = "baseline_always_max"
    RULE_BASED = "rule_based"
    CHEAPEST_MEETING_QUALITY = "cheapest_meeting_quality"
    LOWEST_SUITABLE_TIER = "lowest_suitable_tier"
    QUALITY_FIRST_WITHIN_BUDGET = "quality_first_within_budget"
    LATENCY_FIRST_WITHIN_BUDGET = "latency_first_within_budget"
    WEIGHTED = "weighted"
    USER_SELECTED = "user_selected"
    MANUAL_APPROVAL = "manual_approval"
    MANUAL_REVIEW = "manual_review"


class DataOrigin(str, Enum):
    SIMULATED = "simulated"
    ESTIMATED = "estimated"
    PROVIDER_REPORTED = "provider_reported"
    BILLING_CONFIRMED = "billing_confirmed"


# ── Quality floor ──────────────────────────────────────────────────────

class QualityFloor(BaseModel):
    """Minimum quality requirements for a task category."""
    min_dpi: int = 72
    colour_mode: ColourMode = ColourMode.ANY
    line_coverage: Optional[list[float]] = None  # [min, max] fraction
    min_resolution: Optional[int] = None
    # Text domain fields
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    readability_level: Optional[str] = None


# ── Task category ──────────────────────────────────────────────────────

class TaskCategory(BaseModel):
    """A category of task within a domain config."""
    name: str
    keywords: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    quality_floor: QualityFloor = Field(default_factory=QualityFloor)
    default_tier_hint: Optional[str] = None
    allowed_strategies: Optional[list[str]] = None
    defaults: dict[str, Any] = Field(default_factory=dict)


# ── Strategy ───────────────────────────────────────────────────────────

class StrategyConfig(BaseModel):
    """A processing strategy with cost and capability info."""
    name: str
    adapter: str
    params: dict[str, Any] = Field(default_factory=dict)
    price_per_call: float
    source: str = "placeholder"
    latency_s: float = 1.0
    effort_level: Optional[str] = None
    description: Optional[str] = None
    levers: dict[str, Any] = Field(default_factory=dict)

    @field_validator("price_per_call")
    @classmethod
    def price_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("price_per_call must be non-negative")
        return v


# ── Budget config ──────────────────────────────────────────────────────

class BudgetConfig(BaseModel):
    per_request_max: float = 1.0
    per_school_monthly: float = 100.0
    per_request_units_max: Optional[float] = None
    session_units_max: Optional[float] = None

    @field_validator("per_request_max", "per_school_monthly")
    @classmethod
    def budget_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Budget values must be non-negative")
        return v

    @field_validator("per_request_units_max", "session_units_max")
    @classmethod
    def unit_budget_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Unit budget values must be non-negative")
        return v


# ── Escalation config ─────────────────────────────────────────────────

class EscalationConfig(BaseModel):
    allow_auto: bool = False
    max_retries: int = 1


# ── Policy config ─────────────────────────────────────────────────────

class PolicyConfig(BaseModel):
    active: PolicyName = PolicyName.CHEAPEST_MEETING_QUALITY
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    latency_max_s: float = 30.0
    approval_required_above_cost: float = 0.10
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    weights: Optional[dict[str, float]] = None  # for weighted policy
    show_relative_cost: bool = True
    hide_currency_from_requester: bool = True


# ── Domain config ──────────────────────────────────────────────────────

class DomainConfig(BaseModel):
    """Complete domain configuration."""
    domain: str
    app_name: Optional[str] = "AI GO"
    version: int = 1
    task_categories: dict[str, TaskCategory] = Field(default_factory=dict)
    strategies: dict[str, StrategyConfig] = Field(default_factory=dict)
    policy: PolicyConfig
    baseline_policy: str = "baseline_always_max"
    config_path: Optional[str] = None
    units: Optional[dict[str, Any]] = None
    tiers: Optional[dict[str, Any]] = None
    purposes: Optional[dict[str, Any]] = None
    energy_model: Optional[dict[str, Any]] = None
    colour_ready: Optional[dict[str, Any]] = None
    raw_config: Optional[dict[str, Any]] = None


# ── Request models ─────────────────────────────────────────────────────

class UserRequest(BaseModel):
    """An incoming request from a user."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str
    domain: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    school_id: Optional[str] = None
    requester_id: Optional[str] = None
    role: str = "requester"  # "requester" or "admin"
    preferred_strategy: Optional[str] = None  # for user_selected policy
    override_reason: Optional[str] = None
    max_budget: Optional[float] = None
    max_latency: Optional[float] = None
    quality_level: Optional[str] = None
    policy_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedConstraints(BaseModel):
    max_budget: Optional[float] = None
    max_latency_ms: Optional[float] = None
    required_colour_mode: Optional[str] = None
    target_size: Optional[str] = None


class LLMStructuredIntent(BaseModel):
    """Structured output contract for LLM intent analysis."""
    task_type: str
    intended_use: str
    task_category: Optional[str] = None
    quality_requirement: str = "standard"
    constraints: ExtractedConstraints = Field(default_factory=ExtractedConstraints)
    missing_information: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_question: Optional[str] = None
    extracted_facts: dict[str, Any] = Field(default_factory=dict)
    inferred_preferences: dict[str, Any] = Field(default_factory=dict)
    reasoning_summary: str = ""
    overhead_cost: float = 0.001
    overhead_latency_s: float = 0.15
    data_origin: DataOrigin = DataOrigin.SIMULATED


class AnalysisResult(BaseModel):
    """Result of analysing a request to determine its category."""
    category: Optional[str] = None
    confidence: float = 0.0
    matched_keywords: list[str] = Field(default_factory=list)
    is_ambiguous: bool = False
    clarification_question: Optional[str] = None
    missing_inputs: list[str] = Field(default_factory=list)
    alternative_categories: list[str] = Field(default_factory=list)
    llm_analysis: Optional[LLMStructuredIntent] = None
    analysis_overhead_cost: float = 0.0
    analysis_overhead_latency_s: float = 0.0


# ── Cost models ────────────────────────────────────────────────────────

class CostEstimate(BaseModel):
    """Estimated cost before execution."""
    strategy_name: str
    estimated_cost: float
    currency: str = "USD"
    source: str = "placeholder"
    source_updated_at: str = "2026-10-01"
    is_simulated: bool = True
    data_origin: DataOrigin = DataOrigin.SIMULATED
    breakdown: dict[str, float] = Field(default_factory=dict)


class CostRecord(BaseModel):
    """Actual cost after execution."""
    strategy_name: str
    estimated_cost: float
    actual_cost: float
    currency: str = "USD"
    source: str = "placeholder"
    source_updated_at: str = "2026-10-01"
    is_simulated: bool = True
    data_origin: DataOrigin = DataOrigin.SIMULATED
    attempts: int = 1
    includes_retries: bool = False
    breakdown: dict[str, float] = Field(default_factory=dict)


# ── Decision models ───────────────────────────────────────────────────

class Alternative(BaseModel):
    """An alternative strategy the user could choose."""
    strategy_name: str
    estimated_cost: float
    trade_off: str  # plain language explanation
    is_upgrade: bool
    effort_level: Optional[str] = None
    relative_cost: Optional[str] = None
    display_cost: Optional[str] = None
    levers: dict[str, Any] = Field(default_factory=dict)
    preview_output_ref: Optional[str] = None


class DecisionExplanation(BaseModel):
    """Plain-language explanation of the engine's decision."""
    detected_purpose: str
    chosen_strategy: str
    estimated_cost: float
    reason: str
    effort_level: Optional[str] = None
    display_cost: Optional[str] = None
    relative_cost: Optional[str] = None
    quality_status: Optional[str] = None
    levers: dict[str, Any] = Field(default_factory=dict)
    preview_output_ref: Optional[str] = None
    alternatives: list[Alternative] = Field(default_factory=list)
    all_values_estimated: bool = True
    is_simulated: bool = True


class Decision(BaseModel):
    """The engine's decision for a request."""
    request_id: str
    category: str
    chosen_strategy: str
    cost_estimate: CostEstimate
    explanation: DecisionExplanation
    requires_approval: bool = False
    policy_used: str = ""
    filtered_strategies: dict[str, str] = Field(default_factory=dict)  # name -> reason filtered
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Execution models ──────────────────────────────────────────────────

class ExecutionResult(BaseModel):
    """Result from running a strategy through an adapter."""
    request_id: str
    strategy_name: str
    success: bool
    output_reference: Optional[str] = None  # path or identifier
    output_data: Optional[Any] = None  # the actual output data (for quality checks)
    actual_cost: float = 0.0
    latency_s: float = 0.0
    is_simulated: bool = True
    data_origin: DataOrigin = DataOrigin.SIMULATED
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Quality models ─────────────────────────────────────────────────────

class QualityCheckResult(BaseModel):
    """Result of a single quality check."""
    check_name: str
    passed: bool
    message: str
    measured_value: Optional[Any] = None
    required_value: Optional[Any] = None


class QualityGateResult(BaseModel):
    """Aggregate quality gate result."""
    passed: bool
    checks: list[QualityCheckResult] = Field(default_factory=list)
    human_rating: Optional[int] = None  # 1-5 optional
    is_automated_proxy: bool = True
    disclaimer: str = "These are automated proxy checks, not a judgement of actual output quality."


# ── Complete request record ────────────────────────────────────────────

class RequestRecord(BaseModel):
    """Complete record of a request through the system."""
    request: UserRequest
    analysis: Optional[AnalysisResult] = None
    decision: Optional[Decision] = None
    execution: Optional[ExecutionResult] = None
    cost: Optional[CostRecord] = None
    quality: Optional[QualityGateResult] = None
    status: RequestStatus = RequestStatus.PENDING
    override_reason: Optional[str] = None
    moderation_reason: Optional[str] = None
    human_rating: Optional[int] = None  # 1-5 optional
    moderation_result: Optional[dict[str, Any]] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
