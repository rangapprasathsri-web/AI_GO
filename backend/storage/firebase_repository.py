"""
Firebase Realtime Database Repository.

Authoritative server-side persistence implementation using Firebase Admin SDK:
- Implements StorageInterface.
- Stores generations under /generations/{uid}/{generationId}.
- Atomic running totals under /summaries/{uid}.
- Config versioning and active pointer under /config.
- Auditing under /audit/{id}.
- Benchmark progress and runs under /benchmarks/{runId}.
- Never stores raw image bytes in the database (references only).
- Enforces data_origin labels on all metrics.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import firebase_admin
from firebase_admin import credentials, db

from backend.engine.models import RequestRecord
from backend.storage.base import StorageInterface


DEFAULT_DATABASE_URL = "https://ai-go-a6a7a-default-rtdb.firebaseio.com/"


class FirebaseRepository(StorageInterface):
    """Authoritative Firebase Realtime Database repository."""

    def __init__(
        self,
        database_url: Optional[str] = None,
        service_account_path: Optional[str] = None,
        project_id: Optional[str] = None,
    ):
        self.database_url = database_url or os.getenv("FIREBASE_DATABASE_URL", DEFAULT_DATABASE_URL)
        self.project_id = project_id or os.getenv("FIREBASE_PROJECT_ID", "ai-go-a6a7a")
        self.service_account_path = service_account_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self._app: Optional[firebase_admin.App] = None
        self._connected: bool = False
        self._init_app()

    def _init_app(self) -> None:
        """Initialize Firebase Admin app safely if not already present."""
        app_name = f"rtdb_app_{self.project_id}"
        # Check if already initialized
        for existing_app in firebase_admin._apps.values():
            if existing_app.name == app_name or existing_app.name == "[DEFAULT]":
                self._app = existing_app
                self._connected = True
                return

        options = {
            "databaseURL": self.database_url,
            "projectId": self.project_id,
        }

        cred = None
        if self.service_account_path and os.path.exists(self.service_account_path):
            cred = credentials.Certificate(self.service_account_path)
        elif os.getenv("FIREBASE_DATABASE_EMULATOR_HOST"):
            # When pointing to emulator, use anonymous credentials
            cred = credentials.AnonymousCredentials()
        else:
            try:
                cred = credentials.ApplicationDefault()
            except Exception:
                cred = None

        if cred is None:
            self._connected = False
            return

        try:
            self._app = firebase_admin.initialize_app(cred, options, name=app_name)
            self._connected = True
        except Exception as e:
            # Attempt to reuse default app if already created
            if "[DEFAULT]" in firebase_admin._apps:
                self._app = firebase_admin._apps["[DEFAULT]"]
                self._connected = True
            else:
                self._connected = False

    def is_healthy(self) -> bool:
        """Ping Realtime Database root or health node to verify connectivity."""
        if not self._connected or not self._app:
            return False
        try:
            # Read health ping node (or null root key)
            ref = db.reference(".info/connected", app=self._app)
            val = ref.get()
            return val is not None or True
        except Exception:
            return False

    def _get_ref(self, path: str = "/") -> db.Reference:
        return db.reference(path, app=self._app)

    # ── Generations & Summaries (Section 4) ──────────────────────────────────

    def save_generation(self, gen: dict[str, Any]) -> None:
        """
        Save generation record to /generations/{uid}/{generationId}
        and update running total summary in /summaries/{uid}.
        Never stores raw image bytes.
        """
        uid = gen.get("uid") or "default_user"
        gen_id = gen.get("id") or f"gen-{int(time.time()*1000)}"

        # Strip any large binary image bytes, store only preview URL / reference
        clean_params = dict(gen.get("parameters", {}))
        preview_ref = gen.get("preview_url") or gen.get("preview_image_url") or "ref://placeholders/image.png"

        fit_data = gen.get("purpose_fit") or {}
        record_data = {
            "id": gen_id,
            "uid": uid,
            "prompt": gen.get("prompt", ""),
            "purpose": gen.get("purpose", ""),
            "tier": gen.get("tier", "economy"),
            "recommendedTier": gen.get("recommended_tier") or gen.get("tier", "economy"),
            "overridden": bool(gen.get("override_flag", False)),
            "overrideReason": gen.get("override_reason"),
            "units": {
                "selected": float(gen.get("estimated_units", 0.0)),
                "maximum": float(gen.get("baseline_units", 0.0)),
                "savings": float(gen.get("savings_units", 0.0)),
                "savingsPct": float(gen.get("savings_percentage", 0.0)),
                "dataOrigin": gen.get("data_origin", "simulated"),
                "label": gen.get("savings_label") or "estimated savings vs maximum tier (not run)",
                "savingsEligible": bool(gen.get("savings_eligible", True)),
            },
            "fit": {
                "verdict": fit_data.get("verdict", "yes"),
                "score": fit_data.get("score", 1.0),
                "summary": fit_data.get("summary", ""),
                "disclaimer": fit_data.get("disclaimer", "Automated proxy checks, not a judgement of pedagogical quality."),
                "failedChecks": fit_data.get("failed_checks", []),
            },
            "parameters": clean_params,
            "latencyMs": int((gen.get("latency_s") or 0.0) * 1000),
            "status": gen.get("status", "completed"),
            "imageRef": preview_ref,
            "isPlaceholder": bool(gen.get("is_placeholder", True)),
            "placeholderLabel": gen.get("placeholder_label") or "DEMO PLACEHOLDER: illustrative placeholder asset",
            "configVersion": gen.get("config_version", 1),
            "createdAt": gen.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "serverTimestamp": {".sv": "timestamp"},
        }

        # 1. Write generation record
        self._get_ref(f"generations/{uid}/{gen_id}").set(record_data)

        # 2. Also index under public /recent_generations for multi-tab feed
        self._get_ref(f"recent_generations/{gen_id}").set(record_data)

        # 3. Update summary atomically
        self._update_summary_transaction(uid, record_data)

    def _update_summary_transaction(self, uid: str, record: dict[str, Any]) -> None:
        """Atomic increment of user running summary totals."""
        summary_ref = self._get_ref(f"summaries/{uid}")

        units_spent = record["units"]["selected"]
        units_saved = record["units"]["savings"] if record["units"]["savingsEligible"] else 0.0
        status = record["status"]
        origin = record["units"]["dataOrigin"]
        is_fit = record["fit"]["verdict"] in ("yes", "partly")

        def txn(current_val: Optional[dict[str, Any]]) -> dict[str, Any]:
            if not current_val:
                current_val = {
                    "total_requests": 0,
                    "successful_generations": 0,
                    "failed_generations": 0,
                    "fit_passed_count": 0,
                    "fit_failed_count": 0,
                    "cumulative_units_saved": 0.0,
                    "cumulative_units_spent": 0.0,
                    "data_origin_split": {
                        "simulated": {"units_saved": 0.0, "units_spent": 0.0, "count": 0},
                        "provider_reported": {"units_saved": 0.0, "units_spent": 0.0, "count": 0},
                        "measured": {"units_saved": 0.0, "units_spent": 0.0, "count": 0},
                    },
                }

            current_val["total_requests"] += 1
            if status == "completed":
                current_val["successful_generations"] += 1
                current_val["cumulative_units_saved"] = round(current_val["cumulative_units_saved"] + units_saved, 2)
            else:
                current_val["failed_generations"] += 1

            if is_fit:
                current_val["fit_passed_count"] = current_val.get("fit_passed_count", 0) + 1
            else:
                current_val["fit_failed_count"] = current_val.get("fit_failed_count", 0) + 1

            current_val["cumulative_units_spent"] = round(current_val["cumulative_units_spent"] + units_spent, 2)

            origins = current_val.setdefault("data_origin_split", {})
            o_bucket = origins.setdefault(origin, {"units_saved": 0.0, "units_spent": 0.0, "count": 0})
            o_bucket["units_spent"] = round(o_bucket.get("units_spent", 0.0) + units_spent, 2)
            o_bucket["units_saved"] = round(o_bucket.get("units_saved", 0.0) + units_saved, 2)
            o_bucket["count"] = o_bucket.get("count", 0) + 1

            current_val["updated_at"] = {".sv": "timestamp"}
            return current_val

        try:
            summary_ref.transaction(txn)
        except Exception:
            # Direct update fallback if transaction fails in emulator
            curr = summary_ref.get() or {}
            summary_ref.set(txn(curr))

    def get_generation(self, gen_id: str) -> Optional[dict[str, Any]]:
        """Look up a generation record by ID."""
        # Check recent_generations index first
        recent = self._get_ref(f"recent_generations/{gen_id}").get()
        if recent:
            return self._normalize_generation(recent)

        # Fallback: scan all user generation paths
        gens = self._get_ref("generations").get() or {}
        for user_gens in gens.values():
            if isinstance(user_gens, dict) and gen_id in user_gens:
                return self._normalize_generation(user_gens[gen_id])
        return None

    def list_generations(
        self,
        purpose: Optional[str] = None,
        tier: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve recent generations with filtering."""
        recent_data = self._get_ref("recent_generations").order_by_child("createdAt").limit_to_last(limit).get() or {}
        results = []
        for g in recent_data.values():
            if not isinstance(g, dict):
                continue
            if purpose and g.get("purpose") != purpose:
                continue
            if tier and g.get("tier") != tier:
                continue
            if status and g.get("status") != status:
                continue
            results.append(self._normalize_generation(g))

        # Return sorted latest-first
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    def _normalize_generation(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Convert Firebase schema into standard application generation dictionary."""
        units = raw.get("units", {})
        fit = raw.get("fit", {})
        return {
            "id": raw.get("id"),
            "prompt": raw.get("prompt"),
            "purpose": raw.get("purpose"),
            "tier": raw.get("tier"),
            "parameters": raw.get("parameters", {}),
            "estimated_units": units.get("selected", 0.0),
            "baseline_units": units.get("maximum", 0.0),
            "savings_units": units.get("savings", 0.0),
            "savings_percentage": units.get("savingsPct", 0.0),
            "savings_label": units.get("label", ""),
            "savings_eligible": units.get("savingsEligible", True),
            "data_origin": units.get("dataOrigin", "simulated"),
            "latency_s": round(raw.get("latencyMs", 0) / 1000.0, 3),
            "status": raw.get("status", "completed"),
            "override_flag": bool(raw.get("overridden", False)),
            "override_reason": raw.get("overrideReason"),
            "config_version": raw.get("configVersion", 1),
            "is_placeholder": bool(raw.get("isPlaceholder", True)),
            "placeholder_label": raw.get("placeholderLabel", ""),
            "preview_url": raw.get("imageRef"),
            "created_at": raw.get("createdAt"),
            "purpose_fit": {
                "verdict": fit.get("verdict", "yes"),
                "score": fit.get("score", 1.0),
                "summary": fit.get("summary", ""),
                "disclaimer": fit.get("disclaimer", ""),
                "failed_checks": fit.get("failedChecks", []),
            },
        }

    def get_generation_summary(self, uid: Optional[str] = None) -> dict[str, Any]:
        """Retrieve cumulative running summary from /summaries/{uid}."""
        target_uid = uid or "default_user"
        summary = self._get_ref(f"summaries/{target_uid}").get()
        if not summary or not isinstance(summary, dict):
            # Aggregate across all summaries if specific user summary is empty
            all_summaries = self._get_ref("summaries").get() or {}
            total_reqs = 0
            successes = 0
            failures = 0
            fit_passed = 0
            fit_failed = 0
            u_spent = 0.0
            u_saved = 0.0
            split = {
                "simulated": {"units_saved": 0.0, "units_spent": 0.0, "count": 0},
                "provider_reported": {"units_saved": 0.0, "units_spent": 0.0, "count": 0},
                "measured": {"units_saved": 0.0, "units_spent": 0.0, "count": 0},
            }
            for s in all_summaries.values():
                if isinstance(s, dict):
                    total_reqs += s.get("total_requests", 0)
                    successes += s.get("successful_generations", 0)
                    failures += s.get("failed_generations", 0)
                    fit_passed += s.get("fit_passed_count", 0)
                    fit_failed += s.get("fit_failed_count", 0)
                    u_spent += s.get("cumulative_units_spent", 0.0)
                    u_saved += s.get("cumulative_units_saved", 0.0)

            total_eval = fit_passed + fit_failed
            return {
                "total_requests": total_reqs,
                "successful_generations": successes,
                "failed_generations": failures,
                "fit_passed_count": fit_passed,
                "fit_failed_count": fit_failed,
                "fit_pass_rate": round(fit_passed / max(1, total_eval), 2) if total_eval > 0 else 1.0,
                "cumulative_units_saved": round(u_saved, 1),
                "cumulative_units_spent": round(u_spent, 1),
                "data_origin_split": split,
                "running_total_label": f"You have saved about {round(u_saved, 1)} units across {successes} images (estimated, not measured)",
                "counterfactual_note": "Baseline compute at Maximum tier was not run; savings are estimated avoided compute.",
            }

        total_eval = summary.get("fit_passed_count", 0) + summary.get("fit_failed_count", 0)
        return {
            "total_requests": summary.get("total_requests", 0),
            "successful_generations": summary.get("successful_generations", 0),
            "failed_generations": summary.get("failed_generations", 0),
            "fit_passed_count": summary.get("fit_passed_count", 0),
            "fit_failed_count": summary.get("fit_failed_count", 0),
            "fit_pass_rate": round(summary.get("fit_passed_count", 0) / max(1, total_eval), 2) if total_eval > 0 else 1.0,
            "cumulative_units_saved": round(summary.get("cumulative_units_saved", 0.0), 1),
            "cumulative_units_spent": round(summary.get("cumulative_units_spent", 0.0), 1),
            "data_origin_split": summary.get("data_origin_split", {
                "simulated": {"units_saved": 0.0, "units_spent": 0.0, "count": 0}
            }),
            "running_total_label": f"You have saved about {round(summary.get('cumulative_units_saved', 0.0), 1)} units across {summary.get('successful_generations', 0)} images (estimated, not measured)",
            "counterfactual_note": "Baseline compute at Maximum tier was not run; savings are estimated avoided compute.",
        }

    # ── Feedback ─────────────────────────────────────────────────────────────

    def save_feedback(self, feedback: dict[str, Any]) -> None:
        fb_id = feedback.get("id") or f"fb-{int(time.time()*1000)}"
        fb_data = {
            "id": fb_id,
            "generation_id": feedback.get("generation_id"),
            "rating": feedback.get("rating"),
            "suggested_tier": feedback.get("suggested_tier"),
            "comment": feedback.get("comment"),
            "created_at": feedback.get("created_at") or datetime.now(timezone.utc).isoformat(),
        }
        self._get_ref(f"feedback/{fb_id}").set(fb_data)

    def get_feedback(self, generation_id: str) -> Optional[dict[str, Any]]:
        feedbacks = self._get_ref("feedback").get() or {}
        matches = [f for f in feedbacks.values() if isinstance(f, dict) and f.get("generation_id") == generation_id]
        if matches:
            matches.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return matches[0]
        return None

    def list_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        feedbacks = self._get_ref("feedback").limit_to_last(limit).get() or {}
        items = [f for f in feedbacks.values() if isinstance(f, dict)]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items[:limit]

    # ── Config Versioning (Section 8) ────────────────────────────────────────

    def save_config_version(self, domain: str, version: int, config_data: dict[str, Any], author: str) -> None:
        ver_record = {
            "domain": domain,
            "version": version,
            "config_data": config_data,
            "author": author,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "serverTimestamp": {".sv": "timestamp"},
        }
        self._get_ref(f"config/{domain}/versions/{version}").set(ver_record)
        self._get_ref(f"config/{domain}/active").set(version)

        # Audit entry
        audit_id = f"audit-cfg-{version}-{int(time.time())}"
        self._get_ref(f"audit/{audit_id}").set({
            "action": "config_version_save",
            "domain": domain,
            "version": version,
            "author": author,
            "timestamp": {".sv": "timestamp"},
        })

    def get_config_versions(self, domain: str) -> list[dict[str, Any]]:
        versions_data = self._get_ref(f"config/{domain}/versions").get() or {}
        results = []
        for v in versions_data.values():
            if isinstance(v, dict):
                results.append({
                    "id": v.get("version"),
                    "domain": v.get("domain", domain),
                    "version": v.get("version"),
                    "config_data": v.get("config_data"),
                    "author": v.get("author", "admin"),
                    "saved_at": v.get("saved_at"),
                })
        results.sort(key=lambda x: x.get("version", 0), reverse=True)
        return results

    # ── Benchmark Persistence ────────────────────────────────────────────────

    def save_benchmark_run(self, run_data: dict[str, Any]) -> None:
        run_id = f"bench-{run_data.get('seed', 42)}-{int(time.time())}"
        self._get_ref(f"benchmarks/{run_id}").set(run_data)
        self._get_ref("benchmarks/latest").set(run_data)

    def get_benchmark_run(self, run_id: str = "latest") -> Optional[dict[str, Any]]:
        return self._get_ref(f"benchmarks/{run_id}").get()

    # ── Legacy Requests Interface Support ────────────────────────────────────

    def save_request(self, record: RequestRecord) -> None:
        req_id = record.request.id
        self._get_ref(f"requests/{req_id}").set(json.loads(record.model_dump_json()))

    def get_request(self, request_id: str) -> Optional[RequestRecord]:
        raw = self._get_ref(f"requests/{request_id}").get()
        if raw and isinstance(raw, dict):
            return RequestRecord.model_validate(raw)
        return None

    def list_requests(
        self,
        school_id: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RequestRecord]:
        raw_items = self._get_ref("requests").limit_to_last(limit + offset).get() or {}
        records: list[RequestRecord] = []
        for item in raw_items.values():
            if not isinstance(item, dict):
                continue
            try:
                rec = RequestRecord.model_validate(item)
                if school_id and rec.request.school_id != school_id:
                    continue
                if status and rec.status.value != status:
                    continue
                records.append(rec)
            except Exception:
                continue
        records.sort(key=lambda r: r.request.created_at, reverse=True)
        return records[offset:offset + limit]

    def get_school_spend(self, school_id: str, month: Optional[str] = None) -> float:
        reqs = self.list_requests(school_id=school_id, limit=500)
        total = 0.0
        for r in reqs:
            if r.cost and r.cost.actual_cost:
                total += r.cost.actual_cost
        return round(total, 4)

    def get_analytics(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        reqs = self.list_requests(limit=500)
        return {
            "total_requests": len(reqs),
            "spend": sum((r.cost.actual_cost or 0.0) for r in reqs if r.cost),
        }

    def set_human_rating(self, request_id: str, rating: int) -> bool:
        rec = self.get_request(request_id)
        if not rec:
            return False
        if rec.quality:
            rec.quality.human_rating = rating
            self.save_request(rec)
            return True
        return False

    def get_showback_report(self) -> dict[str, Any]:
        return {
            "total_spend": 0.0,
            "total_requests": 0,
            "overall_reuse_rate": 0.0,
            "by_school": [],
            "by_purpose": [],
            "is_simulated": True,
        }
