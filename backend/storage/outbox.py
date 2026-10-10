"""
Local Outbox Queue for Offline Firebase Fallback.

Persists pending writes locally when Firebase is unreachable and replays
them idempotently when connectivity is restored.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
import time

OUTBOX_PATH = Path("data/outbox.json")


class OutboxQueue:
    """Manages queued writes for offline resilience."""

    def __init__(self, file_path: Optional[Path | str] = None, queue_file: Optional[Path | str] = None):
        target = file_path or queue_file or OUTBOX_PATH
        self.file_path = Path(target)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save_items([])

    def _load_items(self) -> list[dict[str, Any]]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_items(self, items: list[dict[str, Any]]) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)

    def peek(self) -> list[dict[str, Any]]:
        """Return list of queued items without modifying."""
        return self._load_items()

    def clear(self) -> None:
        """Clear all items in queue."""
        self._save_items([])

    def enqueue(self, item_type: str, payload: dict[str, Any]) -> None:
        """Enqueue an item for subsequent replay."""
        items = self._load_items()
        item_id = payload.get("id") or f"{item_type}-{int(time.time()*1000)}"
        # Idempotent deduplication: do not enqueue identical ID twice
        items = [i for i in items if i.get("id") != item_id]
        items.append({
            "id": item_id,
            "type": item_type,
            "payload": payload,
            "enqueued_at": time.time(),
        })
        self._save_items(items)

    def pending_count(self) -> int:
        return len(self._load_items())

    def drain(self, target_repo: Any) -> int:
        """
        Replay all queued items to the target repository.
        Removes items that succeed. Preserves items that fail.
        """
        items = self._load_items()
        if not items:
            return 0

        replayed = 0
        remaining = []
        for item in items:
            itype = item.get("type")
            payload = item.get("payload", {})
            try:
                if itype == "generation":
                    target_repo.save_generation(payload)
                elif itype == "feedback":
                    target_repo.save_feedback(payload)
                elif itype == "config_version":
                    target_repo.save_config_version(
                        payload.get("domain", "image_resource_optimizer"),
                        payload.get("version", 1),
                        payload.get("config_data", {}),
                        payload.get("author", "admin"),
                    )
                replayed += 1
            except Exception:
                remaining.append(item)

        self._save_items(remaining)
        return replayed
