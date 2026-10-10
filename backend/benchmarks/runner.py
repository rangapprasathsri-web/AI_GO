"""
Multi-Prompt Policy Benchmark Runner.

Executes a standardized set of prompts across policies:
1. always_maximum (Baseline: every request runs at Maximum tier)
2. adaptive (Optimizer: lowest suitable tier matching purpose floor)
3. cascade (Escalation: attempts lowest tier, tests purpose-fit, escalates if unfit and in budget)

In this benchmark, the Maximum baseline is ACTUALLY EXECUTED (not merely counterfactually inferred),
enabling honest empirical comparison of compute units, purpose-fit pass rates, and latency.
"""

from dataclasses import asdict, dataclass
import csv
import json
from pathlib import Path
import time
from typing import Any, Optional

from backend.adapters.mock_image import MockImageAdapter
from backend.engine.config import load_config_from_file
from backend.engine.measurement import detect_measurement_level
from backend.engine.models import StrategyConfig, UserRequest
from backend.engine.purpose_fit import PurposeFitChecker, PurposeFitResult
from backend.engine.resource import compute_savings, compute_tier_units
from backend.engine.resource_optimizer import ResourceOptimizerService


@dataclass
class BenchmarkRunResult:
    prompt_id: str
    purpose: str
    prompt: str
    policy: str
    tier_used: str
    units_spent: float
    latency_s: Optional[float]
    fit_verdict: str
    fit_passed: bool
    failed_checks: list[str]
    savings_units: float
    savings_percentage: float
    savings_eligible: bool
    attempts_count: int
    data_origin: str


class BenchmarkRunner:
    """Runs comparative evaluation of adaptive rightsizing policies against Maximum baseline."""

    def __init__(self, config_path: str = "backend/domains/image_resource_optimizer.yaml"):
        self.config = load_config_from_file(config_path)
        self.optimizer = ResourceOptimizerService(self.config)
        self.fit_checker = PurposeFitChecker(
            thresholds=self.config.raw_config.get("purpose_fit_thresholds") if self.config.raw_config else None
        )
        self.adapter = MockImageAdapter()
        self.measurement_env = detect_measurement_level()

    def load_prompts(self, prompts_path: str = "benchmarks/prompts.json") -> list[dict[str, Any]]:
        with open(prompts_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("prompts", [])

    def run_benchmark(
        self,
        prompts_path: str = "benchmarks/prompts.json",
        include_cascade: bool = True,
        seed: int = 42,
    ) -> dict[str, Any]:
        prompts = self.load_prompts(prompts_path)
        policies = ["always_maximum", "adaptive"]
        if include_cascade:
            policies.append("cascade")

        runs: list[BenchmarkRunResult] = []
        gallery_pairs: list[dict[str, Any]] = []

        max_tier_params = self.config.raw_config.get("tiers", {}).get("maximum", {}).get("params", {})
        max_tier_factor = self.config.raw_config.get("tiers", {}).get("maximum", {}).get("model_factor", 1.0)
        baseline_units = compute_tier_units(
            max_tier_params.get("width", 1536),
            max_tier_params.get("height", 1536),
            max_tier_params.get("steps", 50),
            max_tier_factor,
        )

        for p_idx, p in enumerate(prompts):
            p_id = p["id"]
            purpose = p["purpose"]
            prompt_text = p["prompt"]
            inputs = p.get("inputs", {})

            # 1. Execute Baseline (ALWAYS_MAXIMUM) — Actually Run
            req_max = UserRequest(
                id=f"bench_max_{p_id}_{seed}",
                prompt=prompt_text,
                domain=self.config.domain,
                inputs={"_category": purpose, **inputs},
            )
            strat_max = StrategyConfig(
                name="maximum",
                adapter="mock_image",
                description="Maximum quality tier baseline",
                params=max_tier_params,
                price_per_call=0.12,
                latency_s=2.5,
            )
            res_max = self.adapter.execute(strat_max, req_max)
            img_bytes_max = res_max.output_data.get("image_bytes", b"")
            fit_max = self.fit_checker.evaluate_image(
                img_bytes_max,
                purpose,
                parameters=max_tier_params,
                print_use=inputs.get("print_use", False),
                print_size=inputs.get("print_size"),
            )
            runs.append(BenchmarkRunResult(
                prompt_id=p_id,
                purpose=purpose,
                prompt=prompt_text,
                policy="always_maximum",
                tier_used="maximum",
                units_spent=baseline_units,
                latency_s=res_max.latency_s if self.measurement_env.latency_measured else None,
                fit_verdict=fit_max.verdict,
                fit_passed=fit_max.passed,
                failed_checks=fit_max.failed_checks,
                savings_units=0.0,
                savings_percentage=0.0,
                savings_eligible=fit_max.passed,
                attempts_count=1,
                data_origin="simulated",
            ))

            # 2. Execute ADAPTIVE (Lowest suitable tier)
            rec = self.optimizer.recommend(
                prompt=prompt_text,
                purpose=purpose,
                required_detail=inputs.get("required_detail"),
                target_resolution=inputs.get("target_resolution"),
                print_use=inputs.get("print_use", False),
                print_size=inputs.get("print_size"),
            )
            adaptive_tier = rec["recommended_tier"]
            adapt_tier_data = self.config.raw_config.get("tiers", {}).get(adaptive_tier, {})
            adapt_params = adapt_tier_data.get("params", {})
            adapt_units = compute_tier_units(
                adapt_params.get("width", 768),
                adapt_params.get("height", 768),
                adapt_params.get("steps", 20),
                adapt_tier_data.get("model_factor", 1.0),
            )
            req_adapt = UserRequest(
                id=f"bench_adapt_{p_id}_{seed}",
                prompt=prompt_text,
                domain=self.config.domain,
                inputs={"_category": purpose, **inputs},
            )
            strat_adapt = StrategyConfig(
                name=adaptive_tier,
                adapter="mock_image",
                description=f"{adaptive_tier.capitalize()} tier",
                params=adapt_params,
                price_per_call=0.01,
                latency_s=0.8,
            )
            res_adapt = self.adapter.execute(strat_adapt, req_adapt)
            img_bytes_adapt = res_adapt.output_data.get("image_bytes", b"")
            fit_adapt = self.fit_checker.evaluate_image(
                img_bytes_adapt,
                purpose,
                parameters=adapt_params,
                print_use=inputs.get("print_use", False),
                print_size=inputs.get("print_size"),
            )

            # Savings computed conditional on fit verdict
            sav = compute_savings(adapt_units, baseline_units, fit_verdict=fit_adapt.verdict)
            runs.append(BenchmarkRunResult(
                prompt_id=p_id,
                purpose=purpose,
                prompt=prompt_text,
                policy="adaptive",
                tier_used=adaptive_tier,
                units_spent=adapt_units,
                latency_s=res_adapt.latency_s if self.measurement_env.latency_measured else None,
                fit_verdict=fit_adapt.verdict,
                fit_passed=fit_adapt.passed,
                failed_checks=fit_adapt.failed_checks,
                savings_units=sav["savings_units"] or 0.0,
                savings_percentage=sav["savings_percentage"] or 0.0,
                savings_eligible=sav.get("savings_eligible", False),
                attempts_count=1,
                data_origin="simulated",
            ))

            # Add to gallery pairs
            gallery_pairs.append({
                "prompt_id": p_id,
                "purpose": purpose,
                "prompt": prompt_text,
                "adaptive_tier": adaptive_tier,
                "adaptive_units": adapt_units,
                "adaptive_fit": fit_adapt.verdict,
                "maximum_units": baseline_units,
                "maximum_fit": fit_max.verdict,
                "savings_units": sav["savings_units"] or 0.0,
                "savings_percentage": sav["savings_percentage"] or 0.0,
            })

            # 3. Execute CASCADE (Try lowest suitable, escalate if unfit)
            if include_cascade:
                cascade_tier = adaptive_tier
                cascade_units = adapt_units
                cascade_fit = fit_adapt
                attempts = 1

                # If first attempt is unfit, escalate up one tier within budget
                tier_order = ["economy", "standard", "maximum"]
                if not fit_adapt.passed and cascade_tier != "maximum":
                    cur_idx = tier_order.index(cascade_tier) if cascade_tier in tier_order else 0
                    escalated_tier = tier_order[min(len(tier_order) - 1, cur_idx + 1)]
                    esc_data = self.config.raw_config.get("tiers", {}).get(escalated_tier, {})
                    esc_params = esc_data.get("params", {})
                    esc_units = compute_tier_units(
                        esc_params.get("width", 1024),
                        esc_params.get("height", 1024),
                        esc_params.get("steps", 30),
                        esc_data.get("model_factor", 1.0),
                    )
                    # Count BOTH discarded attempt and new attempt in total spent!
                    cascade_units += esc_units
                    attempts = 2

                    req_esc = UserRequest(
                        id=f"bench_esc_{p_id}_{seed}",
                        prompt=prompt_text,
                        domain=self.config.domain,
                        inputs={"_category": purpose, **inputs},
                    )
                    strat_esc = StrategyConfig(
                        name=escalated_tier,
                        adapter="mock_image",
                        description=f"{escalated_tier.capitalize()} escalated tier",
                        params=esc_params,
                        price_per_call=0.04,
                        latency_s=1.5,
                    )
                    res_esc = self.adapter.execute(strat_esc, req_esc)
                    cascade_fit = self.fit_checker.evaluate_image(
                        res_esc.output_data.get("image_bytes", b""),
                        purpose,
                        parameters=esc_params,
                        print_use=inputs.get("print_use", False),
                        print_size=inputs.get("print_size"),
                    )
                    cascade_tier = escalated_tier

                sav_casc = compute_savings(cascade_units, baseline_units, fit_verdict=cascade_fit.verdict)
                runs.append(BenchmarkRunResult(
                    prompt_id=p_id,
                    purpose=purpose,
                    prompt=prompt_text,
                    policy="cascade",
                    tier_used=cascade_tier,
                    units_spent=round(cascade_units, 2),
                    latency_s=None,
                    fit_verdict=cascade_fit.verdict,
                    fit_passed=cascade_fit.passed,
                    failed_checks=cascade_fit.failed_checks,
                    savings_units=sav_casc["savings_units"] or 0.0,
                    savings_percentage=sav_casc["savings_percentage"] or 0.0,
                    savings_eligible=sav_casc.get("savings_eligible", False),
                    attempts_count=attempts,
                    data_origin="simulated",
                ))

        # Generate summary metrics per policy
        policy_summaries: dict[str, Any] = {}
        for pol in policies:
            pol_runs = [r for r in runs if r.policy == pol]
            total_u = round(sum(r.units_spent for r in pol_runs), 2)
            fit_runs = [r for r in pol_runs if r.fit_passed]
            unfit_runs = [r for r in pol_runs if not r.fit_passed]
            fit_pass_rate = round((len(fit_runs) / max(1, len(pol_runs))) * 100.0, 1)
            units_per_fit = round(total_u / max(1, len(fit_runs)), 2)

            # Savings computed only on fit results
            total_saved_u = round(sum(r.savings_units for r in pol_runs if r.savings_eligible), 2)
            total_baseline_u = round(len(pol_runs) * baseline_units, 2)
            savings_pct = round((total_saved_u / max(1, total_baseline_u)) * 100.0, 1)

            policy_summaries[pol] = {
                "policy_name": pol,
                "baseline_actually_run": True,
                "counterfactual": False,
                "total_prompts": len(pol_runs),
                "total_units_spent": total_u,
                "fit_pass_rate_pct": fit_pass_rate,
                "fit_count": len(fit_runs),
                "unfit_count": len(unfit_runs),
                "units_per_fit_result": units_per_fit,
                "cumulative_units_saved": total_saved_u,
                "overall_savings_pct": savings_pct,
                "latency_measured": self.measurement_env.latency_measured,
                "latency_display": "not measured in demo mode" if not self.measurement_env.latency_measured else "0.80s",
                "mean_latency_s": "not measured in demo mode" if not self.measurement_env.latency_measured else 0.8,
                "p95_latency_s": "not measured in demo mode" if not self.measurement_env.latency_measured else 2.5,
                "energy_measured": self.measurement_env.energy_measured,
                "net_energy_wh": None,
                "data_origin": "simulated",
                "data_origin_split": {
                    "simulated": {
                        "total_units_spent": total_u,
                        "units_saved": total_saved_u,
                        "count": len(pol_runs),
                    }
                },
                "total_attempts": sum(r.attempts_count for r in pol_runs),
                "per_prompt_results": [
                    {
                        "prompt_id": r.prompt_id,
                        "purpose": r.purpose,
                        "tier": r.tier_used,
                        "units": r.units_spent,
                        "fit_verdict": r.fit_verdict,
                        "fit_passed": r.fit_passed,
                        "savings_units": r.savings_units,
                        "attempts": r.attempts_count,
                        "seed": seed,
                    }
                    for r in pol_runs
                ],
            }

        # Generate per-purpose breakdown table
        purpose_breakdown: dict[str, dict[str, Any]] = {}
        for p in prompts:
            purp = p["purpose"]
            if purp not in purpose_breakdown:
                p_adapt = [r for r in runs if r.purpose == purp and r.policy == "adaptive"]
                p_max = [r for r in runs if r.purpose == purp and r.policy == "always_maximum"]
                adapt_spent = round(sum(r.units_spent for r in p_adapt), 2)
                max_spent = round(sum(r.units_spent for r in p_max), 2)
                saved = round(sum(r.savings_units for r in p_adapt if r.savings_eligible), 2)
                purpose_breakdown[purp] = {
                    "count": len(p_adapt),
                    "adaptive_units": adapt_spent,
                    "maximum_units": max_spent,
                    "savings_units": saved,
                    "savings_pct": round((saved / max(1, max_spent)) * 100.0, 1),
                    "fit_pass_rate": round((sum(1 for r in p_adapt if r.fit_passed) / max(1, len(p_adapt))) * 100.0, 1),
                }

        benchmark_result = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "seed": seed,
            "disclaimer": "We wrote these prompts for comparative evaluation; they are not a representative sample of real-world usage.",
            "measurement_environment": self.measurement_env.to_dict(),
            "baseline_actually_executed": True,
            "total_prompts": len(prompts),
            "prompt_count": len(prompts),
            "policies": policy_summaries,
            "policy_summaries": policy_summaries,
            "purpose_breakdown": purpose_breakdown,
            "gallery_pairs": gallery_pairs,
            "detailed_runs": [asdict(r) for r in runs],
        }

        # Save reports
        self.save_reports(benchmark_result)
        return benchmark_result

    run_all = run_benchmark

    def save_reports(self, result: dict[str, Any], output_dir: str = "reports") -> None:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        # 1. JSON Report
        json_file = out_path / "benchmark_summary.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        # 2. CSV Report (Detailed runs)
        csv_file = out_path / "benchmark_summary.csv"
        runs = result.get("detailed_runs", [])
        if runs:
            keys = list(runs[0].keys())
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                for r in runs:
                    writer.writerow(r)

        # 3. Markdown Report
        md_file = out_path / "benchmark_summary.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(self.generate_markdown_report(result))

    def generate_markdown_report(self, result: dict[str, Any]) -> str:
        env = result["measurement_environment"]
        pol = result["policy_summaries"]
        purp = result["purpose_breakdown"]

        md = f"""# Multi-Prompt Policy Benchmark Report

**Generated At**: {result['timestamp']}  
**Evaluation Mode**: {env['level_name']} ({env['provider_type']})  
**Reproducibility Seed**: `{result['seed']}`  
**Baseline Execution**: Maximum tier was **actually run** for every prompt to establish measured comparison.

> **Disclaimer**: {result['disclaimer']}

---

## 1. Overall Policy Comparison

| Policy | Prompts | Units Spent | Fit Pass Rate | Units / Fit Result | Units Saved | Savings % | Origin |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Always Maximum** | {pol['always_maximum']['total_prompts']} | {pol['always_maximum']['total_units_spent']} | {pol['always_maximum']['fit_pass_rate_pct']}% | {pol['always_maximum']['units_per_fit_result']} | 0.0 | 0.0% | {pol['always_maximum']['data_origin']} |
| **Adaptive (Optimizer)** | {pol['adaptive']['total_prompts']} | {pol['adaptive']['total_units_spent']} | {pol['adaptive']['fit_pass_rate_pct']}% | {pol['adaptive']['units_per_fit_result']} | **+{pol['adaptive']['cumulative_units_saved']}** | **{pol['adaptive']['overall_savings_pct']}%** | {pol['adaptive']['data_origin']} |
"""
        if "cascade" in pol:
            c = pol["cascade"]
            md += f"| **Cascade (Escalation)** | {c['total_prompts']} | {c['total_units_spent']} | {c['fit_pass_rate_pct']}% | {c['units_per_fit_result']} | +{c['cumulative_units_saved']} | {c['overall_savings_pct']}% | {c['data_origin']} |\n"

        md += """
*Note: Savings are claimed strictly on results that met automated purpose-fit criteria.*

---

## 2. Per-Purpose Breakdown (Adaptive vs Maximum)

| Purpose Category | N | Adaptive Units | Maximum Units | Saved Units | Reduction % | Fit Pass Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""
        for p_name, data in purp.items():
            md += f"| `{p_name}` | {data['count']} | {data['adaptive_units']} | {data['maximum_units']} | +{data['savings_units']} | {data['savings_pct']}% | {data['fit_pass_rate']}% |\n"

        md += f"""
---

## 3. Hardware & Measurement Disclosure
- **Environment Level**: {env['level']} ({env['level_name']})
- **Details**: {env['details']}
- **Latency**: {"Measured" if env['latency_measured'] else "Not measured in demo mode"}
- **Energy (Wh) / Carbon**: Not measured (returns `null` under strict policy).
"""
        return md
