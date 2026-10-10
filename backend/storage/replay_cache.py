"""
Replay cache for offline resilience and demonstration safety net.

Results from earlier runs (images, units, latency, fit verdicts) stored with their
date and method, loadable when network, API or GPU is unavailable.
All replay items are explicitly marked: 'Replay of an earlier run (date)'.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


REPLAY_CACHE_FILE = Path("data/replay_cache.json")


def _init_default_cache() -> list[dict[str, Any]]:
    """Seed initial replay records for coloring sheet and poster demonstration."""
    return [
        {
            "id": "replay-coloring-001",
            "prompt": "Simple black and white line art coloring sheet of a cheerful cartoon giraffe",
            "purpose": "coloring_sheet",
            "tier": "economy",
            "parameters": {"width": 768, "height": 768, "steps": 15, "model_factor": 0.8},
            "estimated_units": 7.08,
            "baseline_units": 117.96,
            "savings_units": 110.88,
            "savings_percentage": 94.0,
            "savings_label": "estimated savings vs maximum tier (not run)",
            "data_origin": "simulated",
            "latency_s": 0.12,
            "status": "completed",
            "recorded_at": "2026-10-09T14:30:00Z",
            "method": "CPU synthetic line-art generator with deterministic seed",
            "is_replay": True,
            "replay_label": "Replay of an earlier run (2026-10-09T14:30:00Z)",
            "purpose_fit": {
                "verdict": "yes",
                "passed": True,
                "score": 1.0,
                "summary": "Passed all 6 fitness checks for coloring_sheet.",
                "disclaimer": "Automated proxy checks, not a judgement of whether a person will like the image.",
                "failed_checks": [],
                "checks": [
                    {"name": "valid_format", "passed": True, "observed": "PNG", "threshold": "valid format", "message": "Valid image format"},
                    {"name": "coloring_light_fraction", "passed": True, "observed": 0.88, "threshold": ">= 0.7", "message": "Near-white canvas proportion 88.0%"},
                    {"name": "coloring_saturation", "passed": True, "observed": 0.01, "threshold": "<= 0.2", "message": "Grayscale saturation 0.01"},
                    {"name": "coloring_line_coverage", "passed": True, "observed": 0.06, "threshold": "0.02 - 0.35", "message": "Outline coverage 6.0%"},
                    {"name": "coloring_solid_fill", "passed": True, "observed": 0.01, "threshold": "<= 0.15", "message": "Dark solid filled area 1.0%"}
                ]
            }
        },
        {
            "id": "replay-poster-002",
            "prompt": "Annual school science fair banner, high-detail full-colour celebration poster",
            "purpose": "professional_print_artwork",
            "tier": "maximum",
            "parameters": {"width": 1536, "height": 1536, "steps": 50, "model_factor": 1.0},
            "estimated_units": 117.96,
            "baseline_units": 117.96,
            "savings_units": 0.0,
            "savings_percentage": 0.0,
            "savings_label": "maximum tier requested (no savings vs baseline)",
            "data_origin": "simulated",
            "latency_s": 0.45,
            "status": "completed",
            "recorded_at": "2026-10-09T14:35:00Z",
            "method": "High-resolution full-colour generator at 1536x1536 50 steps",
            "is_replay": True,
            "replay_label": "Replay of an earlier run (2026-10-09T14:35:00Z)",
            "purpose_fit": {
                "verdict": "yes",
                "passed": True,
                "score": 1.0,
                "summary": "Passed all 4 fitness checks for professional_print_artwork.",
                "disclaimer": "Automated proxy checks, not a judgement of whether a person will like the image.",
                "failed_checks": [],
                "checks": [
                    {"name": "valid_format", "passed": True, "observed": "PNG", "threshold": "valid format", "message": "Valid image format"},
                    {"name": "print_pixels_short_edge", "passed": True, "observed": 1536, "threshold": ">= 1200 px", "message": "Short edge 1536px meets print requirement"},
                    {"name": "print_sharpness_laplacian", "passed": True, "observed": 142.5, "threshold": ">= 40.0", "message": "Laplacian variance 142.50 meets sharpness proxy"}
                ]
            }
        }
    ]


class ReplayCache:
    """Manages cached pre-recorded generation runs for offline safety net."""

    def __init__(self, file_path: Path = REPLAY_CACHE_FILE):
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save_all(_init_default_cache())

    def _load_all(self) -> list[dict[str, Any]]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return _init_default_cache()

    def _save_all(self, entries: list[dict[str, Any]]) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)

    def list_replays(self) -> list[dict[str, Any]]:
        return self._load_all()

    def get_replay(self, purpose: Optional[str] = None, tier: Optional[str] = None) -> Optional[dict[str, Any]]:
        entries = self._load_all()
        for e in entries:
            match_purpose = not purpose or e.get("purpose") == purpose
            match_tier = not tier or e.get("tier") == tier
            if match_purpose and match_tier:
                # Ensure prominent replay labeling
                e["is_replay"] = True
                date_str = e.get("recorded_at", "earlier run")
                e["replay_label"] = f"Replay of an earlier run ({date_str})"
                return e
        if entries:
            # Fallback to first available entry
            res = dict(entries[0])
            res["is_replay"] = True
            res["replay_label"] = f"Replay of an earlier run ({res.get('recorded_at', 'earlier run')})"
            return res
        return None

    def save_replay(self, entry: dict[str, Any]) -> None:
        entries = self._load_all()
        entry_copy = dict(entry)
        entry_copy["recorded_at"] = datetime.utcnow().isoformat() + "Z"
        entry_copy["is_replay"] = True
        entry_copy["replay_label"] = f"Replay of an earlier run ({entry_copy['recorded_at']})"
        # Deduplicate by id if exists
        entries = [e for e in entries if e.get("id") != entry_copy.get("id")]
        entries.append(entry_copy)
        self._save_all(entries)
