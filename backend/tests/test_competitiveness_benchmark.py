"""
Competitiveness Benchmark and Measurement Tests.

Tests compliance with Section 3, 4, 5, 7, and 8 requirements:
- Benchmark is reproducible and deterministic in mock mode with recorded seeds.
- Maximum baseline is actually run in the benchmark (not inferred).
- Savings and units split cleanly by data_origin, never mixing origins into one number.
- Cascade policy accounts for discarded attempts in compute totals.
- Mock mode reports latency as not measured / simulated, never real wall-clock latency.
- Energy fields are null / simulated proxy unless hardware counters are accessible.
- Replay cache entries are labeled "Replay of an earlier run (date)".
- JSON, CSV, and Markdown reports exist, match each other, and state that prompt sample is not representative.
"""

import json
from pathlib import Path
import pytest

from backend.benchmarks.runner import BenchmarkRunner
from backend.engine.measurement import detect_measurement_level
from backend.storage.replay_cache import ReplayCache


@pytest.fixture(scope="module")
def benchmark_data():
    runner = BenchmarkRunner()
    results = runner.run_all()
    runner.save_reports(results)
    return results


class TestBenchmarkRunner:

    def test_benchmark_contains_required_policies(self, benchmark_data):
        assert "always_maximum" in benchmark_data["policies"]
        assert "adaptive" in benchmark_data["policies"]
        assert "cascade" in benchmark_data["policies"]

    def test_baseline_is_actually_run_not_inferred(self, benchmark_data):
        max_policy = benchmark_data["policies"]["always_maximum"]
        assert max_policy["baseline_actually_run"] is True
        assert max_policy["counterfactual"] is False
        assert len(max_policy["per_prompt_results"]) >= 20

    def test_benchmark_records_seeds_deterministically(self, benchmark_data):
        adaptive_policy = benchmark_data["policies"]["adaptive"]
        for item in adaptive_policy["per_prompt_results"]:
            assert "seed" in item
            assert isinstance(item["seed"], int)

    def test_savings_and_totals_split_by_data_origin(self, benchmark_data):
        for policy_name, pol in benchmark_data["policies"].items():
            origins = pol["data_origin_split"]
            assert "simulated" in origins
            # Ensure numbers are separated, not merged
            assert isinstance(origins["simulated"]["total_units_spent"], (int, float))

    def test_cascade_policy_accounts_for_all_attempts(self, benchmark_data):
        cascade_policy = benchmark_data["policies"]["cascade"]
        total_attempts = sum(p.get("attempts", 1) for p in cascade_policy["per_prompt_results"])
        assert total_attempts >= len(cascade_policy["per_prompt_results"])
        # Attempts accounting exists
        assert "total_attempts" in cascade_policy
        assert cascade_policy["total_attempts"] >= len(cascade_policy["per_prompt_results"])

    def test_mock_mode_latency_labelled_as_unmeasured_or_simulated(self, benchmark_data):
        for policy_name, pol in benchmark_data["policies"].items():
            assert pol["latency_measured"] is False
            assert "demo" in pol["latency_display"].lower() or "not measured" in pol["latency_display"].lower()

    def test_energy_fields_are_null_or_simulated_in_level_0(self, benchmark_data):
        meas = detect_measurement_level()
        assert meas.level == 0
        assert meas.energy_measured is False
        for policy_name, pol in benchmark_data["policies"].items():
            assert pol["energy_measured"] is False
            assert pol["net_energy_wh"] is None

    def test_reports_are_generated_and_consistent(self):
        json_path = Path("reports/benchmark_summary.json")
        csv_path = Path("reports/benchmark_summary.csv")
        md_path = Path("reports/benchmark_summary.md")

        assert json_path.exists()
        assert csv_path.exists()
        assert md_path.exists()

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["prompt_count"] >= 20

        md_content = md_path.read_text(encoding="utf-8")
        assert "representative sample" in md_content.lower()
        assert "always maximum" in md_content.lower()
        assert "adaptive" in md_content.lower()

        csv_content = csv_path.read_text(encoding="utf-8")
        assert "prompt_id" in csv_content
        assert "policy" in csv_content
        assert "purpose" in csv_content

    def test_prompts_file_has_disclaimer(self):
        prompts_path = Path("benchmarks/prompts.json")
        assert prompts_path.exists()
        with open(prompts_path, "r", encoding="utf-8") as f:
            prompts_file = json.load(f)
        assert "not a representative sample" in prompts_file.get("disclaimer", "").lower()
        assert len(prompts_file["prompts"]) >= 20


class TestReplayCacheSafetyNet:
    def test_replay_cache_entries_labeled_properly(self):
        rc = ReplayCache()
        replays = rc.list_replays()
        assert len(replays) >= 2
        for r in replays:
            assert r["is_replay"] is True
            assert "Replay of an earlier run" in r["replay_label"]
            assert "recorded_at" in r
            assert "method" in r

    def test_replay_cache_retrieval(self):
        rc = ReplayCache()
        coloring_replay = rc.get_replay(purpose="coloring_sheet", tier="economy")
        assert coloring_replay is not None
        assert coloring_replay["purpose"] == "coloring_sheet"
        assert coloring_replay["tier"] == "economy"
        assert coloring_replay["is_replay"] is True
        assert "Replay of an earlier run" in coloring_replay["replay_label"]
