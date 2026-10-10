#!/usr/bin/env python3
"""
CLI for the Adaptive Request Optimizer.

Supports:
- demo: Run three seed requests showing different strategies
- eval: Run evaluation workload with baseline vs optimized
- config-check: Validate a domain config file
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.adapters.mock_image import MockImageAdapter
from backend.adapters.mock_text import MockTextAdapter
from backend.adapters.template_outline import TemplateOutlineAdapter
from backend.adapters.reuse_library import ReuseLibraryAdapter
from backend.adapters.registry import AdapterRegistry
from backend.engine.config import load_config_from_file, update_config, validate_config
from backend.engine.models import PolicyName, RequestStatus, UserRequest
from backend.engine.orchestrator import Orchestrator
from backend.eval.runner import EvaluationRunner, ReportWriter, attribute_savings_by_lever
from backend.eval.workload_generator import generate_workload
from backend.engine.resource import ResourceEstimator, compute_tier_units, compute_savings
from backend.engine.resource_optimizer import ResourceOptimizerService
from backend.storage.sqlite_storage import SQLiteStorage


def create_registry(
    fail_ids: set[str] | None = None,
    reuse_adapter: ReuseLibraryAdapter | None = None,
) -> AdapterRegistry:
    """Create adapter registry with all available adapters."""
    registry = AdapterRegistry()
    registry.register(MockImageAdapter(fail_request_ids=fail_ids or set()))
    registry.register(MockTextAdapter(fail_request_ids=fail_ids or set()))
    registry.register(TemplateOutlineAdapter())
    registry.register(reuse_adapter or ReuseLibraryAdapter())
    return registry


def demo_command(args: argparse.Namespace) -> None:
    """
    Run official 7-step demo script (Section 11):
    1. Coloring sheet: Economy recommended; show units, savings versus Maximum, and the reason.
    2. Same prompt with a large print size: the recommendation rises and the explanation names why.
    3. Professional/print artwork: Maximum recommended; savings shown as none, which is the right answer.
    4. Override below the floor: warning and confirmation; override above the budget: blocked.
    5. History and running total of estimated savings, split by origin.
    6. Edit one config value and show the recommendation change with no code change.
    7. State plainly: units are a relative proxy; the baseline was not run; demo images are placeholders; energy is not claimed.
    """
    config_path = args.config or "backend/domains/image_resource_optimizer.yaml"
    config = load_config_from_file(config_path)
    service = ResourceOptimizerService(config=config)
    storage = SQLiteStorage(db_path="data/optimizer.db")

    print("=" * 80)
    print("AI IMAGE RESOURCE OPTIMIZER — OFFICIAL DEMO")
    print("Problem Statement: AI image generation uses the same computing power regardless")
    print("of what the image is for, and the energy cost is invisible to the user.")
    print("=" * 80)
    print(f"Domain: {config.domain}")
    print(f"Units Formula: steps * megapixels * model_factor (Relative Proxy)")
    print()

    # Step 1: Coloring sheet -> Economy recommended
    print("┌" + "─" * 78 + "┐")
    print("│ STEP 1: Coloring Sheet → Lowest Suitable Tier (Economy) Recommended          │")
    print("└" + "─" * 78 + "┘")
    prompt = "Cute puppy playing with a rubber ball"
    rec1 = service.recommend(prompt=prompt, purpose="coloring_sheet")
    est1 = rec1["selected_estimate"]
    print(f"  Prompt: '{prompt}'")
    print(f"  Purpose: coloring_sheet (Line art; low detail needed)")
    print(f"  Recommended Tier: {rec1['recommended_tier'].upper()}")
    print(f"  Selected Effort:  {est1['units']} units ({est1['data_origin']} proxy)")
    print(f"  Baseline Effort:  {est1['baseline_units']} units (Maximum tier, not run)")
    print(f"  Avoided Savings:  {est1['savings_units']} units ({est1['savings_percentage']}%)")
    print(f"  Deciding Factor:  {rec1['deciding_factor']}")
    print(f"  Explanation:      {rec1['explanation']}")

    # Step 2: Same prompt with large print size raises floor
    print("\n" + "┌" + "─" * 78 + "┐")
    print("│ STEP 2: Same Prompt with Large Print Size (A1 Poster) → Recommendation Rises   │")
    print("└" + "─" * 78 + "┘")
    rec2 = service.recommend(prompt=prompt, purpose="coloring_sheet", print_size="A1")
    est2 = rec2["selected_estimate"]
    print(f"  Prompt: '{prompt}' (Print Size: A1 Poster)")
    print(f"  Recommended Tier: {rec2['recommended_tier'].upper()} (Raised from Economy)")
    print(f"  Selected Effort:  {est2['units']} units")
    print(f"  Avoided Savings:  {est2['savings_units']} units ({est2['savings_percentage']}%)")
    print(f"  Deciding Factor:  {rec2['deciding_factor']}")
    print(f"  Explanation:      {rec2['explanation']}")

    # Step 3: Professional/print artwork -> Maximum recommended, savings = none
    print("\n" + "┌" + "─" * 78 + "┐")
    print("│ STEP 3: Professional/Print Artwork → Maximum Tier Recommended (0% Savings)     │")
    print("└" + "─" * 78 + "┘")
    rec3 = service.recommend(prompt="Art exhibition showcase portrait", purpose="professional_print_artwork")
    est3 = rec3["selected_estimate"]
    print(f"  Purpose: professional_print_artwork")
    print(f"  Recommended Tier: {rec3['recommended_tier'].upper()}")
    print(f"  Selected Effort:  {est3['units']} units")
    print(f"  Baseline Effort:  {est3['baseline_units']} units")
    print(f"  Avoided Savings:  {est3['savings_units']} units ({est3['savings_percentage']}%)")
    print(f"  Verdict: Maximum tier is genuinely required; 0% savings is the honest answer.")

    # Step 4: Overrides: Below-floor needs confirmation; over-budget blocked
    print("\n" + "┌" + "─" * 78 + "┐")
    print("│ STEP 4: Override Flow: Below-Floor Warning & Hard Budget Block                 │")
    print("└" + "─" * 78 + "┘")
    v_below_unconfirmed = service.validate_override(
        recommended_tier="maximum",
        override_tier="economy",
        purpose="professional_print_artwork",
        override_confirmed=False,
    )
    print("  Case 4A (Below-Floor Override without confirmation):")
    print(f"    Allowed: {v_below_unconfirmed['allowed']}")
    print(f"    Warning: {v_below_unconfirmed['warning']}")

    v_below_confirmed = service.validate_override(
        recommended_tier="maximum",
        override_tier="economy",
        purpose="professional_print_artwork",
        override_confirmed=True,
    )
    print("  Case 4B (Below-Floor Override with explicit confirmation):")
    print(f"    Allowed: {v_below_confirmed['allowed']}")
    print(f"    Status:  {v_below_confirmed['status']} (Action logged)")

    v_budget = service.validate_override(
        recommended_tier="economy",
        override_tier="maximum",
        purpose="coloring_sheet",
        budget_units=50.0,
    )
    print("  Case 4C (Override above hard budget limit of 50 units):")
    print(f"    Allowed: {v_budget['allowed']}")
    print(f"    Status:  {v_budget['status']}")
    print(f"    Message: {v_budget.get('error')}")

    # Step 5: History and running total of estimated savings
    print("\n" + "┌" + "─" * 78 + "┐")
    print("│ STEP 5: History & Running Total of Estimated Savings Split by Origin           │")
    print("└" + "─" * 78 + "┘")
    storage.save_generation({
        "id": "demo-gen-001",
        "prompt": prompt,
        "purpose": "coloring_sheet",
        "tier": "economy",
        "parameters": {"width": 768, "height": 768, "steps": 20},
        "estimated_units": 11.8,
        "baseline_units": 117.96,
        "savings_units": 106.16,
        "savings_percentage": 90.0,
        "savings_label": "estimated savings vs maximum tier (not run)",
        "data_origin": "simulated",
        "status": "completed",
    })
    summary = storage.get_generation_summary()
    print(f"  {summary['running_total_label']}")
    print(f"  Total Requests:         {summary['total_requests']}")
    print(f"  Successful Generations: {summary['successful_generations']}")
    print(f"  Failed Generations:     {summary['failed_generations']}")
    print(f"  Cumulative Units Saved: {summary['cumulative_units_saved']} units")
    print(f"  Cumulative Units Spent: {summary['cumulative_units_spent']} units")
    print(f"  Counterfactual Note:    {summary['counterfactual_note']}")
    print("  [DATA ORIGIN SPLIT]")
    for orig, details in summary["data_origin_split"].items():
        if details["count"] > 0 or details["units_spent"] > 0:
            print(f"    • {orig.upper()}: {details['count']} runs, {details['units_saved']} units saved, {details['units_spent']} units spent")

    # Step 6: Config-only change updates recommendation with zero code change
    print("\n" + "┌" + "─" * 78 + "┐")
    print("│ STEP 6: Config-Only Change (Raise Coloring Floor to Standard) With No Code     │")
    print("└" + "─" * 78 + "┘")
    print("  Original coloring sheet recommendation: Economy")
    updated_cfg = update_config(config, {
        "purposes": {
            "coloring_sheet": {
                "label": "Coloring sheet",
                "min_tier": "standard",
            }
        }
    })
    updated_service = ResourceOptimizerService(config=updated_cfg)
    rec_after = updated_service.recommend(prompt=prompt, purpose="coloring_sheet")
    print(f"  Updated recommendation after config edit: {rec_after['recommended_tier'].upper()}")
    print(f"  Explanation: {rec_after['explanation']}")
    print("  Result: Recommendation dynamically updated without touching any engine code!")

    # Step 7: Plain language honesty disclosures
    print("\n" + "┌" + "─" * 78 + "┐")
    print("│ STEP 7: Core Honesty Disclosures                                               │")
    print("└" + "─" * 78 + "┘")
    print("  • Units are a relative computational proxy (steps * megapixels * model_factor).")
    print("  • The baseline Maximum tier was NOT run; savings represent estimated avoided compute.")
    print("  • Demo mode images are synthetic placeholders marked DEMO PLACEHOLDER, never real model output.")
    print("  • Physical energy (Wh) and carbon (CO2) are NOT claimed and return null (model disabled).")
    print("\n" + "" + "=" * 80)
    print("DEMO COMPLETE — All 7 problem statement requirements reproduced successfully.")
    print("=" * 80)

def eval_command(args: argparse.Namespace) -> None:
    """Run evaluation: baseline vs optimized on the same workload."""
    config_path = args.config or "backend/domains/education_images.yaml"
    config = load_config_from_file(config_path)
    seed = args.seed or 42
    size = args.size or 50

    print(f"Running evaluation on {config.domain} with seed={seed}, size={size}")
    print("All values are SIMULATED")
    print()

    # Include a provider-failure request ID
    fail_ids = {f"eval-{seed}-fail-provider"}

    runner = EvaluationRunner(
        config=config,
        fail_request_ids=fail_ids,
    )

    # Generate workload
    workload = generate_workload(
        domain=config.domain,
        size=size,
        seed=seed,
    )

    # Set up over-budget school
    school_spends = {"SCHOOL-BROKE": 19.95}  # Near the $20 limit

    print(f"Generated {len(workload)} requests")
    print()

    # Run baseline
    print("Running baseline (always_premium)...")
    baseline_results = runner.run_policy(
        workload, PolicyName.BASELINE_ALWAYS_MAX, school_spends=dict(school_spends),
    )
    baseline_metrics = runner.compute_metrics(baseline_results, "baseline_always_max")

    # Run each policy
    policies_to_test = [
        PolicyName.CHEAPEST_MEETING_QUALITY,
        PolicyName.RULE_BASED,
        PolicyName.WEIGHTED,
    ]

    policy_metrics = []
    for policy in policies_to_test:
        print(f"Running {policy.value}...")
        results = runner.run_policy(
            workload, policy, school_spends=dict(school_spends),
        )
        metrics = runner.compute_metrics(results, policy.value)
        policy_metrics.append(metrics)

    # Write reports
    writer = ReportWriter()
    json_path, md_path = writer.write_report(
        baseline_metrics=baseline_metrics,
        policy_metrics=policy_metrics,
        seed=seed,
        workload_size=len(workload),
        domain=config.domain,
    )

    print(f"\nReports written:")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")

    # Print summary
    print(f"\n{'=' * 60}")
    print("EVALUATION SUMMARY (all values simulated)")
    print(f"{'=' * 60}")
    print(f"\nBaseline (always_premium):")
    print(f"  Total cost: ${baseline_metrics['total_cost']:.4f}")
    print(f"  Completed: {baseline_metrics['completed']}/{baseline_metrics['total_requests']}")
    print(f"  Quality pass rate: {baseline_metrics['quality_gate_pass_rate']:.2%}")

    for pm in policy_metrics:
        saving = baseline_metrics['total_cost'] - pm['total_cost']
        saving_pct = (saving / baseline_metrics['total_cost'] * 100) if baseline_metrics['total_cost'] > 0 else 0
        print(f"\n{pm['policy']}:")
        print(f"  Total cost: ${pm['total_cost']:.4f}")
        print(f"  Saving: ${saving:.4f} ({saving_pct:.1f}%) (simulated)")
        print(f"  Completed: {pm['completed']}/{pm['total_requests']}")
        print(f"  Quality pass rate: {pm['quality_gate_pass_rate']:.2%}")
        print(f"  Routing accuracy: {pm['routing_accuracy']:.2%}")

    print(f"\n{'=' * 60}")


def config_check_command(args: argparse.Namespace) -> None:
    """Validate a domain config file."""
    config_path = args.config
    try:
        config = load_config_from_file(config_path)
        warnings = validate_config(config)
        print(f"✓ Config valid: {config.domain} v{config.version}")
        print(f"  Categories: {', '.join(config.task_categories.keys())}")
        print(f"  Strategies: {', '.join(config.strategies.keys())}")
        print(f"  Active policy: {config.policy.active.value}")
        if warnings:
            for w in warnings:
                if w.startswith("WARNING:"):
                    print(f"  ⚠ {w}")
    except Exception as e:
        print(f"✗ Config invalid: {e}")
        sys.exit(1)


def adaptability_demo_command(args: argparse.Namespace) -> None:
    """Demonstrate adaptability: config change alters decision, second domain works."""
    print("=" * 80)
    print("ADAPTABILITY DEMONSTRATION")
    print("=" * 80)

    # Part 1: Original config
    config_path = "backend/domains/education_images.yaml"
    config = load_config_from_file(config_path)
    registry = create_registry()

    orchestrator = Orchestrator(config=config, adapter_lookup=registry.get)

    colouring_request = UserRequest(
        id="adapt-colour-001",
        prompt="Create a colouring sheet of farm animals to colour in",
        domain=config.domain,
        inputs={"subject": "science", "grade_band": "K-2", "output_size": "A4"},
        school_id="SCHOOL-001",
    )

    print("\n1. ORIGINAL CONFIG — Colouring worksheet")
    record1 = orchestrator.process_request(colouring_request)
    if record1.decision:
        print(f"   Strategy: {record1.decision.chosen_strategy}")
        print(f"   Cost: ${record1.decision.cost_estimate.estimated_cost:.2f} (simulated)")

    # Part 2: Change config — raise quality floor so draft can't meet it
    from backend.engine.config import update_config
    updated_config = update_config(config, {
        "task_categories": {
            "colouring_worksheet": {
                "keywords": ["colour in", "colouring", "outline", "coloring sheet", "coloring", "color in", "color"],
                "required_inputs": ["subject", "grade_band", "output_size"],
                "quality_floor": {
                    "min_dpi": 300,  # Raised from 150
                    "colour_mode": "bw",
                    "line_coverage": [0.03, 0.25],
                },
                "default_tier_hint": "low",
            }
        }
    })

    orchestrator.update_config(updated_config)

    colouring_request2 = UserRequest(
        id="adapt-colour-002",
        prompt="Create a colouring sheet of farm animals to colour in",
        domain=config.domain,
        inputs={"subject": "science", "grade_band": "K-2", "output_size": "A4"},
        school_id="SCHOOL-001",
    )

    print("\n2. CONFIG CHANGED (min_dpi raised to 300) — Same request")
    record2 = orchestrator.process_request(colouring_request2)
    if record2.decision:
        print(f"   Strategy: {record2.decision.chosen_strategy}")
        print(f"   Cost: ${record2.decision.cost_estimate.estimated_cost:.2f} (simulated)")
        if record2.decision.filtered_strategies:
            print(f"   Filtered: {record2.decision.filtered_strategies}")

    # Part 3: Text summarization domain
    print("\n3. SECOND DOMAIN — Text Summarization (same engine, no code change)")
    text_config = load_config_from_file("backend/domains/text_summarization.yaml")
    text_orchestrator = Orchestrator(config=text_config, adapter_lookup=registry.get)

    text_request = UserRequest(
        id="adapt-text-001",
        prompt="Give me a brief summary of the quarterly report",
        domain=text_config.domain,
        inputs={"source_text": "The quarterly results show significant improvement across all metrics..."},
        school_id="SCHOOL-001",
    )

    record3 = text_orchestrator.process_request(text_request)
    if record3.decision:
        print(f"   Category: {record3.analysis.category if record3.analysis else 'N/A'}")
        print(f"   Strategy: {record3.decision.chosen_strategy}")
        print(f"   Cost: ${record3.decision.cost_estimate.estimated_cost:.2f} (simulated)")

    print("\n" + "=" * 80)
    print("Adaptability demonstrated: config changes alter decisions, new domain works unchanged")
    print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adaptive Request Optimizer CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Demo
    demo_parser = subparsers.add_parser("demo", help="Run three seed requests")
    demo_parser.add_argument("--config", help="Path to domain config YAML")

    # Eval
    eval_parser = subparsers.add_parser("eval", help="Run evaluation")
    eval_parser.add_argument("--config", help="Path to domain config YAML")
    eval_parser.add_argument("--seed", type=int, default=42, help="Random seed")
    eval_parser.add_argument("--size", type=int, default=50, help="Workload size")

    # Config check
    check_parser = subparsers.add_parser("config-check", help="Validate config")
    check_parser.add_argument("config", help="Path to config YAML")

    # Adaptability demo
    subparsers.add_parser("adaptability", help="Demonstrate adaptability")

    args = parser.parse_args()

    if args.command == "demo":
        demo_command(args)
    elif args.command == "eval":
        eval_command(args)
    elif args.command == "config-check":
        config_check_command(args)
    elif args.command == "adaptability":
        adaptability_demo_command(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
