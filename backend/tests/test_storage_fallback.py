"""
Storage Fallback & Reconnection Tests.

Verifies transparent fallback to SQLite and outbox queuing
when primary Firebase is offline or unconfigured.
"""
import pytest
from backend.storage.factory import FallbackStorage
from backend.storage.sqlite_storage import SQLiteStorage
from backend.storage.base import StorageInterface


class MockFailingPrimary(StorageInterface):
    """Simulates a disconnected primary store."""
    def is_healthy(self) -> bool:
        return False

    def save_generation(self, gen):
        raise ConnectionError("Primary RTDB unreachable")

    def get_generation(self, gen_id):
        return None

    def list_generations(self, **kwargs):
        return []

    def get_generation_summary(self, uid=None):
        return {}

    def save_feedback(self, feedback):
        pass

    def get_feedback(self, generation_id):
        return None

    def list_feedback(self, limit=100):
        return []

    def save_config_version(self, domain, version, config_data, author):
        pass

    def get_config_versions(self, domain):
        return []

    def save_request(self, record):
        pass

    def get_request(self, request_id):
        return None

    def list_requests(self, *args, **kwargs):
        return []

    def get_school_spend(self, school_id, month=None):
        return 0.0

    def get_analytics(self, filters=None):
        return {}

    def set_human_rating(self, request_id, rating):
        return False

    def get_showback_report(self):
        return {}


from backend.storage.outbox import OutboxQueue


def test_fallback_storage_reports_status(tmp_path):
    sqlite = SQLiteStorage(db_path=str(tmp_path / "fallback.db"))
    failing = MockFailingPrimary()
    outbox = OutboxQueue(queue_file=tmp_path / "outbox_status.json")
    storage = FallbackStorage(primary=failing, fallback=sqlite, storage_mode="firebase", outbox=outbox)

    status = storage.get_status()
    assert status["configured_mode"] == "firebase"
    assert status["active_backend"] == "sqlite (fallback)"
    assert status["primary_reachable"] is False
    assert status["fallback_reachable"] is True
    assert status["outbox_pending_count"] == 0


def test_fallback_writes_to_sqlite_and_enqueues_outbox(tmp_path):
    sqlite = SQLiteStorage(db_path=str(tmp_path / "fallback.db"))
    failing = MockFailingPrimary()
    outbox = OutboxQueue(queue_file=tmp_path / "outbox.json")
    storage = FallbackStorage(primary=failing, fallback=sqlite, storage_mode="firebase", outbox=outbox)

    gen = {
        "generation_id": "gen-fallback-1",
        "user_id": "user-offline",
        "purpose": "draft",
        "prompt": "Diagram",
        "tier": "tier_1_fast",
        "status": "completed",
        "simulated": True,
        "energy_joules": 10.0,
        "compute_units": 0.05,
        "avoided_units": 0.95,
        "compute_ratio_vs_max": 0.05,
        "data_origin": "simulated",
    }

    # Should not raise exception
    storage.save_generation(gen)

    # Local SQLite has the record
    retrieved = storage.get_generation("gen-fallback-1")
    assert retrieved is not None
    assert retrieved["generation_id"] == "gen-fallback-1"

    # Outbox has the pending write
    assert storage.outbox.pending_count() == 1
    pending = storage.outbox.peek()
    assert pending[0]["type"] == "generation"
    assert pending[0]["payload"]["generation_id"] == "gen-fallback-1"
