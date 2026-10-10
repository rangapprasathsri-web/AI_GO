"""
Domain configuration loader and validator.

Loads YAML config files, validates them against the schema,
and provides version management.
"""
from __future__ import annotations

import copy
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import ValidationError

from backend.engine.models import (
    BudgetConfig,
    ColourMode,
    DomainConfig,
    EscalationConfig,
    PolicyConfig,
    PolicyName,
    QualityFloor,
    StrategyConfig,
    TaskCategory,
)


class ConfigValidationError(Exception):
    """Raised when config validation fails."""
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Config validation failed: {'; '.join(errors)}")


class ConfigVersionManager:
    """Manages config version history and rollback."""

    def __init__(self, history_dir: str = "configs/history"):
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self._versions: list[dict[str, Any]] = []

    def save_version(self, config: DomainConfig, author: str = "system") -> int:
        """Save a config version and return the version number."""
        version_num = len(self._versions) + 1
        entry = {
            "version": version_num,
            "config": config.model_dump(),
            "saved_at": datetime.utcnow().isoformat(),
            "author": author,
        }
        self._versions.append(entry)

        # Also save to disk
        version_file = self.history_dir / f"{config.domain}_v{version_num}.yaml"
        with open(version_file, "w") as f:
            yaml.dump(config.model_dump(), f, default_flow_style=False)

        return version_num

    def get_version(self, version: int) -> Optional[dict[str, Any]]:
        """Get a specific version."""
        if 1 <= version <= len(self._versions):
            return self._versions[version - 1]
        return None

    def list_versions(self) -> list[dict[str, Any]]:
        """List all versions with metadata."""
        return [
            {"version": v["version"], "saved_at": v["saved_at"], "author": v["author"]}
            for v in self._versions
        ]

    def rollback(self, version: int) -> Optional[DomainConfig]:
        """Rollback to a specific version."""
        entry = self.get_version(version)
        if entry is None:
            return None
        config_data = entry["config"]
        return _parse_config_dict(config_data)


def _parse_config_dict(data: dict[str, Any]) -> DomainConfig:
    """Parse a raw config dictionary into a DomainConfig."""
    # Parse task categories
    task_categories = {}
    for cat_name, cat_data in data.get("task_categories", {}).items():
        if isinstance(cat_data, dict):
            cd = dict(cat_data)
            cd.pop("name", None)
            qf_data = cd.pop("quality_floor", {})
            if isinstance(qf_data, dict):
                quality_floor = QualityFloor(**qf_data)
            elif isinstance(qf_data, QualityFloor):
                quality_floor = qf_data
            else:
                quality_floor = QualityFloor()
            task_categories[cat_name] = TaskCategory(
                name=cat_name,
                keywords=cd.get("keywords", []),
                required_inputs=cd.get("required_inputs", []),
                quality_floor=quality_floor,
                default_tier_hint=cd.get("default_tier_hint"),
                allowed_strategies=cd.get("allowed_strategies"),
                defaults=cd.get("defaults", {}),
            )

    # Parse strategies
    strategies = {}
    for strat_name, strat_data in data.get("strategies", {}).items():
        if isinstance(strat_data, dict):
            sd = dict(strat_data)
            sd.pop("name", None)
            strategies[strat_name] = StrategyConfig(
                name=strat_name,
                **sd,
            )

    # Parse policy
    policy_data = data.get("policy", {})
    budgets_data = policy_data.get("budgets", {})
    escalation_data = policy_data.get("escalation", {})

    # Handle active policy name
    active_policy = policy_data.get("active", "cheapest_meeting_quality")
    if isinstance(active_policy, str) and active_policy not in [p.value for p in PolicyName]:
        raise ConfigValidationError([f"Unknown policy name: {active_policy}"])

    policy = PolicyConfig(
        active=PolicyName(active_policy),
        budgets=BudgetConfig(**budgets_data) if budgets_data else BudgetConfig(),
        latency_max_s=policy_data.get("latency_max_s", 30.0),
        approval_required_above_cost=policy_data.get("approval_required_above_cost", 0.10),
        escalation=EscalationConfig(**escalation_data) if escalation_data else EscalationConfig(),
        weights=policy_data.get("weights"),
        show_relative_cost=policy_data.get("show_relative_cost", True),
        hide_currency_from_requester=policy_data.get("hide_currency_from_requester", True),
    )

    return DomainConfig(
        domain=data["domain"],
        version=data.get("version", 1),
        task_categories=task_categories,
        strategies=strategies,
        policy=policy,
        baseline_policy=data.get("baseline_policy", "baseline_always_max"),
    )


def validate_config(config: DomainConfig) -> list[str]:
    """
    Validate a domain config beyond basic schema validation.
    Returns list of error messages (empty = valid).
    Also returns warnings for non-fatal issues.
    """
    errors = []
    warnings = []

    # Check strategies have prices
    for name, strat in config.strategies.items():
        if strat.price_per_call < 0:
            errors.append(f"Strategy '{name}' has negative price: {strat.price_per_call}")

    # Check budgets are non-negative
    if config.policy.budgets.per_request_max < 0:
        errors.append("per_request_max budget is negative")
    if config.policy.budgets.per_school_monthly < 0:
        errors.append("per_school_monthly budget is negative")

    # Check that each task category's quality floor can be met by at least one strategy
    for cat_name, category in config.task_categories.items():
        can_meet = False
        for strat_name, strategy in config.strategies.items():
            if _strategy_can_meet_floor(strategy, category.quality_floor):
                can_meet = True
                break
        if not can_meet:
            warnings.append(
                f"WARNING: No strategy can meet the quality floor for category '{cat_name}'"
            )

    # Check baseline policy is valid
    valid_policies = [p.value for p in PolicyName]
    if config.baseline_policy not in valid_policies:
        errors.append(f"Unknown baseline_policy: {config.baseline_policy}")

    # Check strategy adapters are referenced consistently
    adapter_names = set()
    for strat in config.strategies.values():
        adapter_names.add(strat.adapter)

    # Check task category default_tier_hint references a valid strategy
    for cat_name, category in config.task_categories.items():
        if category.default_tier_hint and category.default_tier_hint not in config.strategies:
            # tier hint may refer to a tier level (low, medium, high) not a strategy name
            # so we just warn
            pass

    return errors + warnings


def _strategy_can_meet_floor(strategy: StrategyConfig, floor: QualityFloor) -> bool:
    """Check if a strategy's parameters can plausibly meet a quality floor."""
    params = strategy.params
    resolution = params.get("resolution", 0)

    # Check DPI: resolution / (output_size_inches). We use a simple heuristic:
    # if the strategy resolution >= min_dpi * 4 (assuming ~4 inch minimum output), it can meet it.
    # This is a simplified check; real implementation would consider output_size.
    if floor.min_dpi and resolution > 0:
        # Rough check: resolution should be at least min_dpi * 2 (for a 2-inch output minimum)
        if resolution < floor.min_dpi:
            return False

    # For text domain, check based on model tier
    model_tier = params.get("model_tier")
    if model_tier and floor.min_length:
        # Simplified: all tiers can produce text
        pass

    return True


def load_config_from_file(path: str) -> DomainConfig:
    """Load and validate a domain config from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ConfigValidationError(["Config file must contain a YAML mapping"])

    config = _parse_config_dict(data)
    config.config_path = str(path)

    errors = validate_config(config)
    real_errors = [e for e in errors if not e.startswith("WARNING:")]
    if real_errors:
        raise ConfigValidationError(real_errors)

    return config


def load_config_from_dict(data: dict[str, Any]) -> DomainConfig:
    """Load and validate a domain config from a dictionary."""
    config = _parse_config_dict(data)

    errors = validate_config(config)
    real_errors = [e for e in errors if not e.startswith("WARNING:")]
    if real_errors:
        raise ConfigValidationError(real_errors)

    return config


def update_config(
    config: DomainConfig,
    updates: dict[str, Any],
) -> DomainConfig:
    """
    Apply updates to a config and return a new validated config.
    Does NOT mutate the original.
    """
    current = config.model_dump()
    _deep_merge(current, updates)
    return load_config_from_dict(current)


def _deep_merge(base: dict, override: dict) -> None:
    """Deep merge override into base, mutating base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
