"""
Adapter base interface.

Every adapter must implement this interface. Adding a new adapter
requires only adding one file — no changes to the engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from backend.engine.models import CostEstimate, ExecutionResult, StrategyConfig, UserRequest


class AdapterCapability:
    """Declares what an adapter can do."""

    def __init__(
        self,
        task_categories: list[str],
        output_types: list[str],
        parameter_limits: dict[str, Any] | None = None,
    ):
        self.task_categories = task_categories
        self.output_types = output_types
        self.parameter_limits = parameter_limits or {}


class AdapterPricing:
    """Pricing information with source tracking."""

    def __init__(
        self,
        method: str = "per_call",
        values: dict[str, float] | None = None,
        source: str = "placeholder",
        source_updated_at: str = "2026-10-01",
        data_origin: str = "simulated",
    ):
        self.method = method
        self.values = values or {}
        self.source = source
        self.source_updated_at = source_updated_at
        self.data_origin = data_origin


class BaseAdapter(ABC):
    """
    Base adapter interface.
    
    Every provider adapter must implement this interface.
    The engine calls adapters through this interface only.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique adapter name."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapability:
        """What this adapter can do."""
        ...

    @property
    @abstractmethod
    def pricing(self) -> AdapterPricing:
        """Pricing information."""
        ...

    @property
    def available(self) -> bool:
        """Whether this adapter is currently available."""
        return True

    @abstractmethod
    def estimate_cost(self, strategy: StrategyConfig, request: UserRequest) -> CostEstimate:
        """Estimate cost for a request with a given strategy."""
        ...

    @abstractmethod
    def execute(self, strategy: StrategyConfig, request: UserRequest) -> ExecutionResult:
        """
        Execute a request.
        Returns ExecutionResult with actual cost, latency, output reference, and errors.
        """
        ...
