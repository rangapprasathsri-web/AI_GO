"""
Storage Contract Tests.

Verifies that SQLiteStorage, FallbackStorage, and OutboxQueue conform
to the StorageInterface contract for generations, summaries, and configs.
"""
import pytest
from pathlib import Path

from backend.storage.sqlite_storage import SQLiteStorage
from backend.storage.factory import FallbackStorage, create_storage
from backend.storage.outbox import OutboxQueue


@pytest.fixture
def temp_storage(tmp_path):
    db_file = str(tmp_path / "test_opt.db")
    storage = create_storage(mode="local", db_path=db_file)
    return storage


def test_generation_lifecycle_contract(temp_storage):
    gen_data = {
        "generation_id": "gen-test-101",
        "user_id": "test-user-alpha",
        "purpose": "thumbnail",
        "prompt": "Solar system diagram",
        "tier": "tier_1_fast",
        "status": "completed",
        "simulated": True,
        "energy_joules": 45.0,
        "compute_units": 0.05,
        "avoided_units": 0.95,
        "compute_ratio_vs_max": 0.05,
        "data_origin": "simulated",
    }
    temp_storage.save_generation(gen_data)

    retrieved = temp_storage.get_generation("gen-test-101")
    assert retrieved is not None
    assert retrieved["generation_id"] == "gen-test-101"
    assert retrieved["purpose"] == "thumbnail"
    assert retrieved["tier"] == "tier_1_fast"

    listed = temp_storage.list_generations(purpose="thumbnail")
    assert len(listed) >= 1
    assert any(g["generation_id"] == "gen-test-101" for g in listed)

    summary = temp_storage.get_generation_summary("test-user-alpha")
    assert summary["total_generations"] >= 1
    assert summary["avoided_units"] >= 0.95


def test_outbox_queue_contract(tmp_path):
    outbox_file = str(tmp_path / "outbox.json")
    queue = OutboxQueue(queue_file=outbox_file)

    assert queue.pending_count() == 0
    queue.enqueue("generation", {"generation_id": "outbox-gen-1"})
    queue.enqueue("feedback", {"generation_id": "outbox-gen-1", "rating": 5})

    assert queue.pending_count() == 2

    # Verify peek preserves items
    items = queue.peek()
    assert len(items) == 2

    # Clear
    queue.clear()
    assert queue.pending_count() == 0


def test_config_versioning_contract(temp_storage):
    domain = "test_domain"
    temp_storage.save_config_version(
        domain=domain,
        version=1,
        config_data={"version": 1, "strategies": {}},
        author="tester",
    )
    versions = temp_storage.get_config_versions(domain)
    assert len(versions) >= 1
    assert versions[0]["version"] == 1
    assert versions[0]["author"] == "tester"
