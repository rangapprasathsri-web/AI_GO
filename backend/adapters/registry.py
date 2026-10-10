"""
Adapter registry.

Allows adapters to be registered and looked up by name.
Adding a new adapter requires registering it here — no engine changes needed.
"""
from __future__ import annotations

from typing import Optional

from backend.adapters.base import BaseAdapter


class AdapterRegistry:
    """Registry for adapter instances."""

    def __init__(self):
        self._adapters: dict[str, BaseAdapter] = {}

    def register(self, adapter: BaseAdapter) -> None:
        """Register an adapter instance."""
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> Optional[BaseAdapter]:
        """Get an adapter by name."""
        return self._adapters.get(name)

    def list_adapters(self) -> list[str]:
        """List all registered adapter names."""
        return list(self._adapters.keys())

    def has(self, name: str) -> bool:
        """Check if an adapter is registered."""
        return name in self._adapters


# Global registry instance
_global_registry = AdapterRegistry()


def get_global_registry() -> AdapterRegistry:
    """Get the global adapter registry."""
    return _global_registry


def register_adapter(adapter: BaseAdapter) -> None:
    """Register an adapter in the global registry."""
    _global_registry.register(adapter)


def get_adapter(name: str) -> Optional[BaseAdapter]:
    """Get an adapter from the global registry."""
    return _global_registry.get(name)
