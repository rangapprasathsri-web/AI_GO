"""
Storage base interface (repository pattern).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from backend.engine.models import RequestRecord


class StorageInterface(ABC):
    """Abstract storage interface using repository pattern."""

    @abstractmethod
    def save_request(self, record: RequestRecord) -> None:
        """Save or update a request record."""
        ...

    @abstractmethod
    def get_request(self, request_id: str) -> Optional[RequestRecord]:
        """Get a request record by ID."""
        ...

    @abstractmethod
    def list_requests(
        self,
        school_id: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RequestRecord]:
        """List request records with optional filters."""
        ...

    @abstractmethod
    def get_school_spend(
        self,
        school_id: str,
        month: Optional[str] = None,
    ) -> float:
        """Get total spend for a school in a given month."""
        ...

    @abstractmethod
    def get_analytics(
        self,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get analytics data with optional filters."""
        ...

    @abstractmethod
    def save_config_version(
        self, domain: str, version: int, config_data: dict[str, Any], author: str
    ) -> None:
        """Save a config version."""
        ...

    @abstractmethod
    def get_config_versions(self, domain: str) -> list[dict[str, Any]]:
        """Get all config versions for a domain."""
        ...

    @abstractmethod
    def set_human_rating(self, request_id: str, rating: int) -> bool:
        """Store optional 1 to 5 human rating for a request result."""
        ...

    @abstractmethod
    def get_showback_report(self) -> dict[str, Any]:
        """Get showback report by school and by purpose."""
        ...

    @abstractmethod
    def save_generation(self, gen: dict[str, Any]) -> None:
        """Save a resource generation record."""
        ...

    @abstractmethod
    def get_generation(self, gen_id: str) -> Optional[dict[str, Any]]:
        """Get a generation record by ID."""
        ...

    @abstractmethod
    def list_generations(
        self,
        purpose: Optional[str] = None,
        tier: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List generation records with optional filters."""
        ...

    @abstractmethod
    def get_generation_summary(self, uid: Optional[str] = None) -> dict[str, Any]:
        """Get running cumulative summary of resource generations and savings."""
        ...

    @abstractmethod
    def save_feedback(self, feedback: dict[str, Any]) -> None:
        """Save user feedback on a generation."""
        ...

    @abstractmethod
    def get_feedback(self, generation_id: str) -> Optional[dict[str, Any]]:
        """Get latest user feedback for a generation ID."""
        ...

    @abstractmethod
    def list_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        """List recent user feedback records."""
        ...

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if storage repository is reachable and healthy."""
        ...
