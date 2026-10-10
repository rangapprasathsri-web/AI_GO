"""
Main orchestrator - the decision pipeline.

Pipeline: validate → moderate → analyse → filter → rank → explain → approval gate → execute → quality gate → record.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from backend.engine.analysis import AnalysisInterface, RulesBasedAnalyser
from backend.engine.config import ConfigValidationError
from backend.engine.cost import (
    check_request_budget,
    check_school_budget,
    estimate_cost,
    format_cost_comparison,
    record_cost,
)
from backend.engine.models import (
    Alternative,
    AnalysisResult,
    ColourMode,
    CostEstimate,
    CostRecord,
    Decision,
    DecisionExplanation,
    DomainConfig,
    ExecutionResult,
    PolicyName,
    QualityFloor,
    QualityGateResult,
    RequestRecord,
    RequestStatus,
    StrategyConfig,
    UserRequest,
)
from backend.engine.moderation import ModerationHook, ModerationResult
from backend.engine.policies import get_policy
from backend.engine.quality_gate import run_quality_gate


class Orchestrator:
    """
    Main decision engine orchestrator.

    Coordinates the full pipeline from request to result.
    Does NOT import from adapters, domains, or API — uses injected interfaces.
    """

    def __init__(
        self,
        config: DomainConfig,
        adapter_lookup: Callable[[str], Any],  # name -> adapter instance
        analyser: AnalysisInterface | None = None,
        moderation: ModerationHook | None = None,
        school_spend_lookup: Callable[[str], float] | None = None,
    ):
        self.config = config
        self._adapter_lookup = adapter_lookup
        self._analyser = analyser or RulesBasedAnalyser()
        self._moderation = moderation or ModerationHook()
        self._school_spend_lookup = school_spend_lookup or (lambda _: 0.0)

    def update_config(self, config: DomainConfig) -> None:
        """Update the active config (for config-change tests)."""
        self.config = config

    # ── Full pipeline ─────────────────────────────────────────────────

    def process_request(
        self,
        request: UserRequest,
        auto_execute: bool = True,
        policy_override: PolicyName | None = None,
    ) -> RequestRecord:
        """
        Run the full pipeline for a request.

        Args:
            request: The incoming user request.
            auto_execute: If True, execute immediately after decision (unless approval needed).
            policy_override: Override the active policy for this request.

        Returns:
            Complete RequestRecord with all stages populated.
        """
        record = RequestRecord(request=request, status=RequestStatus.PENDING)

        # Step 0: Moderation check on prompt
        mod_result = self._moderation.check_prompt(request)
        record.moderation_result = mod_result.to_dict()
        if not mod_result.passed:
            record.status = RequestStatus.MODERATION_BLOCKED
            return record

        # Step 1: Analyse
        analysis = self._analyser.analyse(request, self.config)
        record.analysis = analysis

        if analysis.is_ambiguous and analysis.category is None:
            record.status = RequestStatus.AWAITING_CLARIFICATION
            return record

        if analysis.category is None:
            record.status = RequestStatus.AWAITING_CLARIFICATION
            return record

        # Pre-fill per-purpose defaults into inputs if not explicitly specified
        cat_obj = self.config.task_categories.get(analysis.category)
        if cat_obj and cat_obj.defaults:
            for k, v in cat_obj.defaults.items():
                if k not in request.inputs:
                    request.inputs[k] = v

        # Re-check missing inputs after defaults are pre-filled
        if analysis.missing_inputs:
            analysis.missing_inputs = [
                inp for inp in analysis.missing_inputs
                if inp not in request.inputs
            ]
            if analysis.missing_inputs:
                record.status = RequestStatus.AWAITING_CLARIFICATION
                return record

        # Inject category into inputs for downstream use
        request.inputs["_category"] = analysis.category

        record.status = RequestStatus.ANALYSED

        # Step 2: Make decision
        policy_name = policy_override or self.config.policy.active
        decision = self.make_decision(request, analysis, policy_name)
        record.decision = decision
        record.status = RequestStatus.DECIDED

        # Step 3: Approval gate
        if decision.requires_approval:
            record.status = RequestStatus.AWAITING_APPROVAL
            return record

        # Step 4: Execute (if auto_execute)
        if auto_execute:
            record = self.execute_decision(record)

        return record

    # ── Decision making ───────────────────────────────────────────────

    def make_decision(
        self,
        request: UserRequest,
        analysis: AnalysisResult,
        policy_name: PolicyName | None = None,
    ) -> Decision:
        """
        Make a decision: filter strategies, rank with policy, explain.
        """
        policy_name = policy_name or self.config.policy.active
        category_name = analysis.category or ""
        category = self.config.task_categories.get(category_name)

        if category is None:
            # Use manual review if category unknown
            return self._manual_review_decision(request, analysis, "Unknown category")

        quality_floor = category.quality_floor

        # Filter strategies
        candidates, filtered_out = self._filter_strategies(
            request, quality_floor, category_name
        )

        if not candidates:
            return self._manual_review_decision(
                request, analysis,
                "No strategy meets all constraints",
                filtered_out,
            )

        # Rank with policy
        policy = get_policy(policy_name)
        ranked = policy.rank_strategies(candidates, quality_floor, request, self.config)

        if not ranked:
            return self._manual_review_decision(
                request, analysis, "Policy returned no candidates"
            )

        chosen_strategy, reason = ranked[0]

        # Cost estimate
        cost_est = estimate_cost(chosen_strategy, request, self.config)

        # Check budgets
        within_budget, budget_msg = check_request_budget(
            cost_est.estimated_cost, self.config
        )
        if not within_budget:
            return self._budget_exceeded_decision(
                request, analysis, budget_msg, cost_est
            )

        # School budget check
        if request.school_id:
            current_spend = self._school_spend_lookup(request.school_id)
            school_ok, remaining, school_msg = check_school_budget(
                request.school_id, cost_est.estimated_cost, current_spend, self.config
            )
            if not school_ok:
                return self._budget_exceeded_decision(
                    request, analysis, school_msg, cost_est
                )

        # Approval gate
        requires_approval = (
            cost_est.estimated_cost > self.config.policy.approval_required_above_cost
        )

        # Build alternatives
        alternatives = self._build_alternatives(
            ranked[1:], chosen_strategy, cost_est, category_name
        )

        # Build explanation
        premium_strategy = max(self.config.strategies.values(), key=lambda s: s.price_per_call)
        premium_cost = premium_strategy.price_per_call
        hide_currency = (request.role == "requester") and self.config.policy.hide_currency_from_requester
        cost_comparison = format_cost_comparison(
            cost_est.estimated_cost,
            premium_cost,
            category_name,
            hide_currency=hide_currency,
            effort_level_name=premium_strategy.effort_level or "Print-quality",
        )

        ratio = premium_cost / cost_est.estimated_cost if cost_est.estimated_cost > 0 else 1.0
        rel_cost = f"about 1/{ratio:.0f} of {premium_strategy.effort_level or 'Print-quality'}" if ratio > 1.1 else "Highest tier"
        disp_cost = rel_cost if hide_currency else f"${cost_est.estimated_cost:.2f} (simulated)"

        explanation = DecisionExplanation(
            detected_purpose=f"{category_name.replace('_', ' ').title()} — {category.quality_floor.colour_mode.value} mode",
            chosen_strategy=chosen_strategy.name,
            estimated_cost=cost_est.estimated_cost,
            effort_level=chosen_strategy.effort_level or "Standard",
            display_cost=disp_cost,
            relative_cost=rel_cost,
            quality_status=f"Cheapest level meeting all quality requirements for {category_name.replace('_', ' ')}.",
            levers=chosen_strategy.levers,
            reason=(
                f"{reason}. {cost_comparison} "
                f"This tier meets the quality requirements for {category_name.replace('_', ' ')}."
            ),
            alternatives=alternatives,
            all_values_estimated=True,
            is_simulated=True,
        )

        return Decision(
            request_id=request.id,
            category=category_name,
            chosen_strategy=chosen_strategy.name,
            cost_estimate=cost_est,
            explanation=explanation,
            requires_approval=requires_approval,
            policy_used=policy_name.value if isinstance(policy_name, PolicyName) else str(policy_name),
            filtered_strategies=filtered_out,
        )

    # ── Execution ─────────────────────────────────────────────────────

    def execute_decision(self, record: RequestRecord) -> RequestRecord:
        """Execute the chosen strategy and run quality gate."""
        if record.decision is None:
            record.status = RequestStatus.FAILED
            return record

        decision = record.decision
        request = record.request
        strategy_name = decision.chosen_strategy
        strategy = self.config.strategies.get(strategy_name)

        if strategy is None:
            record.status = RequestStatus.FAILED
            return record

        adapter = self._adapter_lookup(strategy.adapter)
        if adapter is None:
            record.status = RequestStatus.FAILED
            return record

        record.status = RequestStatus.EXECUTING

        # Execute with retry support
        max_retries = self.config.policy.escalation.max_retries
        attempts = 0
        execution = None
        last_error = None

        for attempt in range(max_retries + 1):
            attempts += 1
            execution = adapter.execute(strategy, request)

            if execution.success:
                break

            last_error = execution.error

            # Do NOT auto-escalate unless config allows
            if not self.config.policy.escalation.allow_auto:
                break

        if execution is None or not execution.success:
            record.execution = execution
            record.status = RequestStatus.FAILED
            record.cost = record_cost(
                strategy, decision.cost_estimate, execution or ExecutionResult(
                    request_id=request.id,
                    strategy_name=strategy_name,
                    success=False,
                    error=last_error or "Unknown error",
                    is_simulated=True,
                ),
                attempts=attempts,
            )
            return record

        record.execution = execution

        # Moderation check on output
        if execution.output_data:
            mod_result = self._moderation.check_output(execution.output_data)
            if not mod_result.passed:
                record.moderation_result = mod_result.to_dict()
                record.status = RequestStatus.MODERATION_BLOCKED
                record.cost = record_cost(
                    strategy, decision.cost_estimate, execution, attempts
                )
                return record

        # Quality gate
        category = self.config.task_categories.get(decision.category)
        quality_floor = category.quality_floor if category else QualityFloor()

        output_format = "image" if "image" in strategy.adapter else "text"
        quality_result = run_quality_gate(
            execution.output_data, quality_floor, decision.category, output_format
        )
        record.quality = quality_result

        # Record cost
        record.cost = record_cost(
            strategy, decision.cost_estimate, execution, attempts
        )

        if quality_result.passed:
            record.status = RequestStatus.COMPLETED
        else:
            record.status = RequestStatus.FAILED

        record.updated_at = datetime.utcnow()
        return record

    # ── Private helpers ───────────────────────────────────────────────

    def _filter_strategies(
        self,
        request: UserRequest,
        quality_floor: QualityFloor,
        category_name: str,
    ) -> tuple[list[StrategyConfig], dict[str, str]]:
        """
        Filter strategies by hard constraints.
        Returns (candidates, filtered_out_with_reasons).
        """
        candidates = []
        filtered_out: dict[str, str] = {}

        category = self.config.task_categories.get(category_name)

        for name, strategy in self.config.strategies.items():
            # Check if strategy is allowed for this category
            if category and category.allowed_strategies is not None:
                if name not in category.allowed_strategies:
                    filtered_out[name] = f"Strategy '{name}' not allowed for category '{category_name}'"
                    continue

            # Check adapter availability
            adapter = self._adapter_lookup(strategy.adapter)
            if adapter is None:
                filtered_out[name] = "Adapter not available"
                continue

            if hasattr(adapter, 'available') and not adapter.available:
                filtered_out[name] = "Adapter currently unavailable"
                continue

            # Check capability
            if hasattr(adapter, 'capabilities'):
                caps = adapter.capabilities
                if category_name not in caps.task_categories:
                    filtered_out[name] = f"Adapter does not support category '{category_name}'"
                    continue

            # Check dynamic match (e.g. reuse library hit availability)
            if hasattr(adapter, 'has_match'):
                has_hit, hit_msg = adapter.has_match(request, category_name)
                if not has_hit:
                    filtered_out[name] = f"Reuse unavailable: {hit_msg}"
                    continue

            # Check quality floor plausibility
            if not self._strategy_meets_floor(strategy, quality_floor):
                filtered_out[name] = "Cannot meet quality floor"
                continue

            # Check budget
            within_budget, msg = check_request_budget(
                strategy.price_per_call, self.config
            )
            if not within_budget:
                filtered_out[name] = msg
                continue

            # Check latency
            if strategy.latency_s > self.config.policy.latency_max_s:
                filtered_out[name] = f"Latency {strategy.latency_s}s exceeds max {self.config.policy.latency_max_s}s"
                continue

            candidates.append(strategy)

        return candidates, filtered_out

    def _strategy_meets_floor(
        self, strategy: StrategyConfig, floor: QualityFloor
    ) -> bool:
        """Check if a strategy can plausibly meet a quality floor."""
        resolution = strategy.params.get("resolution", 0)

        # Resolution vs DPI check (min 2 inches output size proxy)
        required_pixels = floor.min_dpi * 2 if floor.min_dpi else 0
        if floor.min_resolution:
            required_pixels = max(required_pixels, floor.min_resolution)

        if required_pixels > 0 and resolution > 0:
            if resolution < required_pixels:
                return False

        return True

    def _build_alternatives(
        self,
        remaining_ranked: list[tuple[StrategyConfig, str]],
        chosen: StrategyConfig,
        chosen_cost: CostEstimate,
        category: str,
    ) -> list[Alternative]:
        """Build list of alternatives with trade-off explanations."""
        premium_strategy = max(self.config.strategies.values(), key=lambda s: s.price_per_call)
        premium_cost = premium_strategy.price_per_call
        hide_currency = self.config.policy.hide_currency_from_requester

        alternatives = []
        for strategy, reason in remaining_ranked[:4]:
            is_upgrade = strategy.price_per_call > chosen.price_per_call
            effort = strategy.effort_level or "Standard"
            ratio = premium_cost / strategy.price_per_call if strategy.price_per_call > 0 else 1.0
            rel_cost = f"about 1/{ratio:.0f} of {premium_strategy.effort_level or 'Print-quality'}" if ratio > 1.1 else "Highest tier"
            disp_cost = rel_cost if hide_currency else f"${strategy.price_per_call:.2f} (simulated)"

            if is_upgrade:
                trade_off = (
                    f"Higher effort level: {effort} ({strategy.params.get('resolution', 'N/A')} resolution, "
                    f"{strategy.params.get('steps', 'N/A')} steps) at "
                    f"${strategy.price_per_call:.2f} (estimated, simulated). "
                    f"May provide {'better detail' if category != 'colouring_worksheet' else 'nothing noticeable for this use'}."
                )
            else:
                trade_off = (
                    f"Lower effort level: {effort} at ${strategy.price_per_call:.2f} (estimated, simulated) "
                    f"with {strategy.params.get('resolution', 'N/A')} resolution."
                )

            alternatives.append(Alternative(
                strategy_name=strategy.name,
                estimated_cost=strategy.price_per_call,
                trade_off=trade_off,
                is_upgrade=is_upgrade,
                effort_level=effort,
                relative_cost=rel_cost,
                display_cost=disp_cost,
                levers=strategy.levers,
            ))

        return alternatives

    def _manual_review_decision(
        self,
        request: UserRequest,
        analysis: AnalysisResult,
        reason: str,
        filtered: dict[str, str] | None = None,
    ) -> Decision:
        """Create a decision that routes to manual review."""
        # Pick the cheapest strategy as a suggestion
        strategies = sorted(
            self.config.strategies.values(),
            key=lambda s: (s.price_per_call, s.latency_s, s.name),
        )
        suggestion = strategies[0] if strategies else None
        strategy_name = suggestion.name if suggestion else "none"
        est_cost = suggestion.price_per_call if suggestion else 0.0

        return Decision(
            request_id=request.id,
            category=analysis.category or "unknown",
            chosen_strategy=strategy_name,
            cost_estimate=CostEstimate(
                strategy_name=strategy_name,
                estimated_cost=est_cost,
                is_simulated=True,
                source="placeholder",
            ),
            explanation=DecisionExplanation(
                detected_purpose=f"Uncertain: {analysis.category or 'unclassified'}",
                chosen_strategy=strategy_name,
                estimated_cost=est_cost,
                reason=f"Manual review required: {reason}",
                is_simulated=True,
            ),
            requires_approval=True,
            policy_used="manual_review",
            filtered_strategies=filtered or {},
        )

    def _budget_exceeded_decision(
        self,
        request: UserRequest,
        analysis: AnalysisResult,
        message: str,
        cost_est: CostEstimate,
    ) -> Decision:
        """Create a decision indicating budget is exceeded."""
        return Decision(
            request_id=request.id,
            category=analysis.category or "unknown",
            chosen_strategy="none",
            cost_estimate=cost_est,
            explanation=DecisionExplanation(
                detected_purpose=f"{analysis.category or 'unknown'}",
                chosen_strategy="none",
                estimated_cost=cost_est.estimated_cost,
                reason=f"Budget exceeded: {message}",
                is_simulated=True,
            ),
            requires_approval=True,
            policy_used="budget_block",
            filtered_strategies={},
        )
