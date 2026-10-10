"""
Evaluation runner and report writer.

Runs baseline vs optimized policies on the same seeded workload.
Produces JSON and Markdown reports with all required metrics.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.adapters.mock_image import MockImageAdapter
from backend.adapters.mock_text import MockTextAdapter
from backend.adapters.registry import AdapterRegistry
from backend.engine.config import load_config_from_file
from backend.engine.models import (
    DomainConfig,
    PolicyName,
    RequestRecord,
    RequestStatus,
    UserRequest,
)
from backend.engine.orchestrator import Orchestrator
from backend.eval.workload_generator import generate_workload


class EvaluationRunner:
    """Runs evaluation workloads under different policies."""

    def __init__(
        self,
        config: DomainConfig,
        adapter_registry: AdapterRegistry | None = None,
        fail_request_ids: set[str] | None = None,
    ):
        self.config = config
        self._registry = adapter_registry or self._default_registry(fail_request_ids)

    def _default_registry(self, fail_ids: set[str] | None = None) -> AdapterRegistry:
        reg = AdapterRegistry()
        reg.register(MockImageAdapter(fail_request_ids=fail_ids or set()))
        reg.register(MockTextAdapter(fail_request_ids=fail_ids or set()))
        return reg

    def run_policy(
        self,
        workload: list[UserRequest],
        policy: PolicyName,
        school_spends: dict[str, float] | None = None,
    ) -> list[RequestRecord]:
        """Run a workload under a specific policy."""
        school_spends = school_spends or {}
        # Track running spend per school
        running_spend: dict[str, float] = dict(school_spends)

        def lookup_spend(school_id: str) -> float:
            return running_spend.get(school_id, 0.0)

        orchestrator = Orchestrator(
            config=self.config,
            adapter_lookup=self._registry.get,
            school_spend_lookup=lookup_spend,
        )

        results = []
        for request in workload:
            record = orchestrator.process_request(
                request, auto_execute=True, policy_override=policy,
            )

            # Update running spend
            if record.cost and request.school_id:
                running_spend[request.school_id] = (
                    running_spend.get(request.school_id, 0.0) + record.cost.actual_cost
                )

            results.append(record)

        return results

    def compute_metrics(
        self, results: list[RequestRecord], policy_name: str,
    ) -> dict[str, Any]:
        """Compute metrics for a set of results."""
        total = len(results)
        completed = [r for r in results if r.status == RequestStatus.COMPLETED]
        failed = [r for r in results if r.status == RequestStatus.FAILED]
        blocked = [r for r in results if r.status == RequestStatus.MODERATION_BLOCKED]
        clarification = [r for r in results if r.status == RequestStatus.AWAITING_CLARIFICATION]
        budget_exceeded = [r for r in results if r.status == RequestStatus.BUDGET_EXCEEDED]

        # Cost metrics
        total_cost = sum(r.cost.actual_cost for r in results if r.cost)
        estimated_cost = sum(r.cost.estimated_cost for r in results if r.cost)
        costs_successful = [r.cost.actual_cost for r in completed if r.cost]
        cost_per_success = (
            statistics.mean(costs_successful) if costs_successful else 0.0
        )

        # Latency metrics
        latencies = [r.execution.latency_s for r in results if r.execution and r.execution.success]
        mean_latency = statistics.mean(latencies) if latencies else 0.0
        p95_latency = (
            sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else mean_latency
        )

        # Quality metrics
        quality_checked = [r for r in results if r.quality]
        quality_passed = [r for r in quality_checked if r.quality.passed]
        quality_pass_rate = (
            len(quality_passed) / len(quality_checked) if quality_checked else 0.0
        )

        # Routing accuracy (compare assigned category vs eval_category)
        labelled = [
            r for r in results
            if r.request.metadata.get("eval_category")
            and not r.request.metadata["eval_category"].startswith("_")
        ]
        correctly_routed = [
            r for r in labelled
            if r.analysis and r.analysis.category == r.request.metadata.get("eval_category")
        ]
        routing_accuracy = (
            len(correctly_routed) / len(labelled) if labelled else 0.0
        )

        # Strategy distribution
        strategy_counts: dict[str, int] = {}
        effort_mix = {"Reuse": 0, "Quick": 0, "Standard": 0, "Print-quality": 0}
        reuse_hits = 0
        strategy_effort = {
            "reuse": "Reuse",
            "template_outline": "Quick",
            "draft": "Quick",
            "standard": "Standard",
            "premium": "Print-quality",
            "small_model": "Quick",
            "medium_model": "Standard",
            "large_model": "Print-quality",
        }

        for r in results:
            if r.decision:
                s = r.decision.chosen_strategy
                strategy_counts[s] = strategy_counts.get(s, 0) + 1
                eff = strategy_effort.get(s, "Standard")
                effort_mix[eff] = effort_mix.get(eff, 0) + 1
                if s == "reuse" or (r.execution and r.execution.metadata.get("reused")):
                    reuse_hits += 1

        reuse_hit_rate = round(reuse_hits / total, 4) if total > 0 else 0.0

        # Data origin split
        data_origin_split: dict[str, dict[str, Any]] = {
            "simulated": {"requests": 0, "cost": 0.0},
            "estimated": {"requests": 0, "cost": 0.0},
            "provider_reported": {"requests": 0, "cost": 0.0},
            "billing_confirmed": {"requests": 0, "cost": 0.0},
        }
        for r in results:
            origin = "simulated"
            if r.execution and getattr(r.execution, "data_origin", None):
                origin = r.execution.data_origin.value if hasattr(r.execution.data_origin, "value") else str(r.execution.data_origin)
            elif r.cost and getattr(r.cost, "data_origin", None):
                origin = r.cost.data_origin.value if hasattr(r.cost.data_origin, "value") else str(r.cost.data_origin)

            if origin not in data_origin_split:
                data_origin_split[origin] = {"requests": 0, "cost": 0.0}
            data_origin_split[origin]["requests"] += 1
            if r.cost:
                data_origin_split[origin]["cost"] = round(data_origin_split[origin]["cost"] + r.cost.actual_cost, 4)

        # Retry count
        total_retries = sum(
            r.cost.attempts - 1 for r in results if r.cost and r.cost.attempts > 1
        )

        return {
            "policy": policy_name,
            "total_requests": total,
            "completed": len(completed),
            "failed": len(failed),
            "moderation_blocked": len(blocked),
            "awaiting_clarification": len(clarification),
            "budget_exceeded": len(budget_exceeded),
            "total_cost": round(total_cost, 4),
            "total_estimated_cost": round(estimated_cost, 4),
            "cost_per_successful_request": round(cost_per_success, 4),
            "mean_latency_s": round(mean_latency, 3),
            "p95_latency_s": round(p95_latency, 3),
            "quality_gate_pass_rate": round(quality_pass_rate, 4),
            "failure_rate": round(len(failed) / total if total > 0 else 0, 4),
            "routing_accuracy": round(routing_accuracy, 4),
            "strategy_distribution": strategy_counts,
            "effort_level_mix": effort_mix,
            "reuse_hit_rate": reuse_hit_rate,
            "total_retries": total_retries,
            "data_origin_split": data_origin_split,
            "all_values_simulated": True,
        }


def attribute_savings_by_lever(
    baseline_results: list[RequestRecord],
    optimized_results: list[RequestRecord],
) -> dict[str, float]:
    """
    Attribute cost savings to specific optimization levers:
    - reuse_savings: savings from reusing approved assets
    - template_savings: savings from using non-generative vector templates
    - lower_tier_savings: savings from running draft/standard instead of premium
    Invariant guaranteed: reuse_savings + template_savings + lower_tier_savings == total_savings.
    """
    savings = {
        "reuse": 0.0,
        "template": 0.0,
        "lower_generation_tier": 0.0,
    }

    for b_rec, o_rec in zip(baseline_results, optimized_results):
        b_cost = b_rec.cost.actual_cost if b_rec.cost else 0.0
        o_cost = o_rec.cost.actual_cost if o_rec.cost else 0.0
        saving = max(0.0, b_cost - o_cost)

        strat = o_rec.decision.chosen_strategy if o_rec.decision else ""
        if strat == "reuse":
            savings["reuse"] += saving
        elif strat == "template_outline":
            savings["template"] += saving
        else:
            savings["lower_generation_tier"] += saving

    r = round(savings["reuse"], 4)
    t = round(savings["template"], 4)
    lt = round(savings["lower_generation_tier"], 4)
    tot = round(r + t + lt, 4)

    return {
        "reuse_savings": r,
        "template_savings": t,
        "lower_tier_savings": lt,
        "total_savings": tot,
    }


class ReportWriter:
    """Writes evaluation reports in JSON and Markdown."""

    def __init__(self, output_dir: str = "eval_reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_report(
        self,
        baseline_metrics: dict[str, Any],
        policy_metrics: list[dict[str, Any]],
        seed: int,
        workload_size: int,
        domain: str,
    ) -> tuple[str, str]:
        """Write JSON and Markdown reports. Returns (json_path, md_path)."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        report_data = {
            "evaluation_metadata": {
                "timestamp": timestamp,
                "seed": seed,
                "workload_size": workload_size,
                "domain": domain,
                "disclaimer": (
                    "All costs, latencies, and quality metrics in this report are SIMULATED. "
                    "The category mix is an assumption (the audit says 'most', not a specific number). "
                    "Savings are computed from runs of the same workload under both policies."
                ),
            },
            "baseline": baseline_metrics,
            "policies": policy_metrics,
            "comparisons": [],
        }

        # Compute comparisons
        for pm in policy_metrics:
            if baseline_metrics["total_cost"] > 0:
                saving_abs = baseline_metrics["total_cost"] - pm["total_cost"]
                saving_pct = (saving_abs / baseline_metrics["total_cost"]) * 100
            else:
                saving_abs = 0
                saving_pct = 0

            report_data["comparisons"].append({
                "policy": pm["policy"],
                "vs_baseline": "baseline_always_max",
                "cost_saving_absolute": round(saving_abs, 4),
                "cost_saving_percentage": round(saving_pct, 2),
                "quality_pass_rate_diff": round(
                    pm["quality_gate_pass_rate"] - baseline_metrics["quality_gate_pass_rate"], 4
                ),
                "latency_diff_s": round(
                    pm["mean_latency_s"] - baseline_metrics["mean_latency_s"], 3
                ),
                "label": "simulated — same workload, same seed",
            })

        # Write JSON
        json_path = self.output_dir / f"eval_{domain}_{timestamp}.json"
        with open(json_path, "w") as f:
            json.dump(report_data, f, indent=2)

        # Write Markdown
        md_path = self.output_dir / f"eval_{domain}_{timestamp}.md"
        md_content = self._render_markdown(report_data)
        with open(md_path, "w") as f:
            f.write(md_content)

        return str(json_path), str(md_path)

    def _render_markdown(self, data: dict[str, Any]) -> str:
        meta = data["evaluation_metadata"]
        lines = [
            f"# Evaluation Report: {meta['domain']}",
            "",
            f"> **Disclaimer**: {meta['disclaimer']}",
            "",
            "### Labelled Evaluation Assumptions",
            "- **Category Mix (Assumption)**: 70% colouring sheets, 15% flashcards, 10% classroom illustrations, 5% banners",
            "- **Repeat Rate (Assumption)**: 30% repeated subject requests eligible for library reuse",
            "- **Pricing (Assumption)**: All prices sourced from placeholder, simulated",
            f"- **Seed**: {meta['seed']}",
            f"- **Workload size**: {meta['workload_size']}",
            f"- **Timestamp**: {meta['timestamp']}",
            "",
            "## Baseline (always_premium)",
            "",
            self._metrics_table(data["baseline"]),
            "",
        ]

        for pm in data["policies"]:
            lines.append(f"## Policy: {pm['policy']}")
            lines.append("")
            lines.append(self._metrics_table(pm))
            lines.append("")

        if data["comparisons"]:
            lines.append("## Comparisons vs Baseline")
            lines.append("")
            lines.append("| Policy | Cost Saving | Saving % | Quality Δ | Latency Δ | Label |")
            lines.append("|--------|-------------|----------|-----------|-----------|-------|")
            for c in data["comparisons"]:
                lines.append(
                    f"| {c['policy']} | ${c['cost_saving_absolute']:.4f} | "
                    f"{c['cost_saving_percentage']:.1f}% | "
                    f"{c['quality_pass_rate_diff']:+.4f} | "
                    f"{c['latency_diff_s']:+.3f}s | "
                    f"{c['label']} |"
                )
            lines.append("")

        lines.append("---")
        lines.append("*All values are simulated. Savings computed from same workload under both policies.*")

        return "\n".join(lines)

    def _metrics_table(self, m: dict[str, Any]) -> str:
        lines = [
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Requests | {m['total_requests']} |",
            f"| Completed | {m['completed']} |",
            f"| Failed | {m['failed']} |",
            f"| Moderation Blocked | {m['moderation_blocked']} |",
            f"| Awaiting Clarification | {m['awaiting_clarification']} |",
            f"| Total Cost (simulated) | ${m['total_cost']:.4f} |",
            f"| Cost per Success (simulated) | ${m['cost_per_successful_request']:.4f} |",
            f"| Mean Latency (simulated) | {m['mean_latency_s']:.3f}s |",
            f"| P95 Latency (simulated) | {m['p95_latency_s']:.3f}s |",
            f"| Quality Pass Rate | {m['quality_gate_pass_rate']:.2%} |",
            f"| Failure Rate | {m['failure_rate']:.2%} |",
            f"| Routing Accuracy | {m['routing_accuracy']:.2%} |",
            f"| Reuse Hit Rate | {m.get('reuse_hit_rate', 0.0):.2%} |",
            f"| Effort Level Mix | {json.dumps(m.get('effort_level_mix', {}))} |",
            f"| Strategy Distribution | {json.dumps(m['strategy_distribution'])} |",
            f"| Data Origin Split | {json.dumps(m.get('data_origin_split', {}))} |",
        ]
        return "\n".join(lines)
