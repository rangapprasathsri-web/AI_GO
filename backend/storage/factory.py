"""
Storage Factory and Fallback Storage Wrapper.

Selects primary storage (Firebase RTDB) with automatic local fallback (SQLite).
Guarantees zero crashes if Firebase credentials are absent or network is down.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from backend.engine.models import RequestRecord
from backend.storage.base import StorageInterface
from backend.storage.outbox import OutboxQueue
from backend.storage.sqlite_storage import SQLiteStorage

logger = logging.getLogger(__name__)


class FallbackStorage(StorageInterface):
    """
    Transparent dual-repository manager.
    Authoritative writes to Firebase primary; automatically falls back to SQLite
    and enqueues writes to an outbox when Firebase is unreachable.
    """

    def __init__(
        self,
        primary: Optional[StorageInterface],
        fallback: SQLiteStorage,
        storage_mode: str = "firebase",
        outbox: Optional[OutboxQueue] = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.storage_mode = storage_mode
        self.outbox = outbox or OutboxQueue()
        self.last_write_target = "sqlite"

    @property
    def is_primary_active(self) -> bool:
        return bool(self.primary and self.primary.is_healthy())

    def get_status(self) -> dict[str, Any]:
        """Report active storage backend and reachability for health checks."""
        primary_ok = self.is_primary_active
        return {
            "configured_mode": self.storage_mode,
            "primary_backend": "firebase",
            "fallback_backend": "sqlite",
            "active_backend": "firebase" if primary_ok else "sqlite (fallback)",
            "primary_reachable": primary_ok,
            "fallback_reachable": self.fallback.is_healthy(),
            "outbox_pending_count": self.outbox.pending_count(),
            "notice": "connected to live Firebase RTDB" if primary_ok else "saving locally to SQLite fallback (no data loss)",
        }

    def is_healthy(self) -> bool:
        return self.is_primary_active or self.fallback.is_healthy()

    # ── Generations & Summaries ──────────────────────────────────────────────

    def save_generation(self, gen: dict[str, Any]) -> None:
        # 1. Always save to local fallback for instantaneous local consistency
        self.fallback.save_generation(gen)

        # 2. Attempt primary Firebase write
        if self.is_primary_active:
            try:
                self.primary.save_generation(gen)  # type: ignore
                self.last_write_target = "firebase"
                # Drain any backlog if outbox has items
                if self.outbox.pending_count() > 0:
                    self.outbox.drain(self.primary)
                return
            except Exception as e:
                logger.warning(f"Primary Firebase write failed: {e}. Enqueueing to outbox.")

        # If primary failed or not active, queue for replay
        self.outbox.enqueue("generation", gen)
        self.last_write_target = "sqlite (fallback)"

    def get_generation(self, gen_id: str) -> Optional[dict[str, Any]]:
        if self.is_primary_active:
            try:
                res = self.primary.get_generation(gen_id)  # type: ignore
                if res:
                    return res
            except Exception:
                pass
        return self.fallback.get_generation(gen_id)

    def list_generations(
        self,
        purpose: Optional[str] = None,
        tier: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self.is_primary_active:
            try:
                items = self.primary.list_generations(purpose=purpose, tier=tier, status=status, limit=limit)  # type: ignore
                if items:
                    return items
            except Exception:
                pass
        return self.fallback.list_generations(purpose=purpose, tier=tier, status=status, limit=limit)

    def get_generation_summary(self, uid: Optional[str] = None) -> dict[str, Any]:
        if self.is_primary_active:
            try:
                return self.primary.get_generation_summary(uid)  # type: ignore
            except Exception:
                pass
        return self.fallback.get_generation_summary()

    # ── Feedback ─────────────────────────────────────────────────────────────

    def save_feedback(self, feedback: dict[str, Any]) -> None:
        self.fallback.save_feedback(feedback)
        if self.is_primary_active:
            try:
                self.primary.save_feedback(feedback)  # type: ignore
                return
            except Exception:
                pass
        self.outbox.enqueue("feedback", feedback)

    def get_feedback(self, generation_id: str) -> Optional[dict[str, Any]]:
        if self.is_primary_active:
            try:
                fb = self.primary.get_feedback(generation_id)  # type: ignore
                if fb:
                    return fb
            except Exception:
                pass
        return self.fallback.get_feedback(generation_id)

    def list_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        if self.is_primary_active:
            try:
                items = self.primary.list_feedback(limit=limit)  # type: ignore
                if items:
                    return items
            except Exception:
                pass
        return self.fallback.list_feedback(limit=limit)

    # ── Config Versioning ────────────────────────────────────────────────────

    def save_config_version(self, domain: str, version: int, config_data: dict[str, Any], author: str) -> None:
        self.fallback.save_config_version(domain, version, config_data, author)
        if self.is_primary_active:
            try:
                self.primary.save_config_version(domain, version, config_data, author)  # type: ignore
                return
            except Exception:
                pass
        self.outbox.enqueue("config_version", {
            "domain": domain,
            "version": version,
            "config_data": config_data,
            "author": author,
        })

    def get_config_versions(self, domain: str) -> list[dict[str, Any]]:
        if self.is_primary_active:
            try:
                versions = self.primary.get_config_versions(domain)  # type: ignore
                if versions:
                    return versions
            except Exception:
                pass
        return self.fallback.get_config_versions(domain)

    # ── Legacy Requests Interface ────────────────────────────────────────────

    def save_request(self, record: RequestRecord) -> None:
        self.fallback.save_request(record)
        if self.is_primary_active:
            try:
                self.primary.save_request(record)  # type: ignore
            except Exception:
                pass

    def get_request(self, request_id: str) -> Optional[RequestRecord]:
        if self.is_primary_active:
            try:
                r = self.primary.get_request(request_id)  # type: ignore
                if r:
                    return r
            except Exception:
                pass
        return self.fallback.get_request(request_id)

    def list_requests(
        self,
        school_id: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RequestRecord]:
        if self.is_primary_active:
            try:
                reqs = self.primary.list_requests(school_id, category, status, limit, offset)  # type: ignore
                if reqs:
                    return reqs
            except Exception:
                pass
        return self.fallback.list_requests(school_id, category, status, limit, offset)

    def get_school_spend(self, school_id: str, month: Optional[str] = None) -> float:
        return self.fallback.get_school_spend(school_id, month)

    def get_analytics(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.fallback.get_analytics(filters)

    def get_analytics_summary(self, domain: Optional[str] = None) -> dict[str, Any]:
        return self.fallback.get_analytics()

    def set_human_rating(self, request_id: str, rating: int) -> bool:
        if self.is_primary_active:
            try:
                self.primary.set_human_rating(request_id, rating)  # type: ignore
            except Exception:
                pass
        return self.fallback.set_human_rating(request_id, rating)

    def get_showback_report(self) -> dict[str, Any]:
        return self.fallback.get_showback_report()


def create_storage(mode: Optional[str] = None, db_path: str = "data/optimizer.db") -> StorageInterface:
    """
    Factory creating configured storage repository.
    Handles STORAGE_MODE=sqlite/local or STORAGE_MODE=firebase.
    Defaults to SQLite.
    """
    selected_mode = mode or os.getenv("STORAGE_MODE", "sqlite").lower()
    fallback_sqlite = SQLiteStorage(db_path=db_path)

    if selected_mode in ("local", "sqlite"):
        logger.info("[STORAGE] Active storage backend: SQLite (mode: %s, db_path: %s)", selected_mode, db_path)
        return FallbackStorage(primary=None, fallback=fallback_sqlite, storage_mode="local")

    # Mode is firebase: attempt initialization of FirebaseRepository
    try:
        from backend.storage.firebase_repository import FirebaseRepository
        primary_firebase = FirebaseRepository()
        logger.info("[STORAGE] Active storage backend: Firebase RTDB (fallback: SQLite)")
        return FallbackStorage(primary=primary_firebase, fallback=fallback_sqlite, storage_mode="firebase")
    except Exception as e:
        logger.info(f"[STORAGE] Active storage backend: SQLite fallback (Firebase initialization skipped/failed: {e})")
        return FallbackStorage(primary=None, fallback=fallback_sqlite, storage_mode="firebase")
