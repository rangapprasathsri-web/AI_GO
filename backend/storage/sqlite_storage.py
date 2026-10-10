"""
SQLite storage implementation.

Persists requests, decisions, executions, costs, and quality results.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from backend.engine.models import (
    AnalysisResult,
    CostEstimate,
    CostRecord,
    Decision,
    DecisionExplanation,
    ExecutionResult,
    QualityGateResult,
    RequestRecord,
    RequestStatus,
    UserRequest,
)
from backend.storage.base import StorageInterface


class SQLiteStorage(StorageInterface):
    """SQLite implementation of the storage interface."""

    def __init__(self, db_path: str = "data/optimizer.db"):
        if os.getenv("VERCEL") and db_path == "data/optimizer.db":
            db_path = "/tmp/optimizer.db"
        self.db_path = db_path
        try:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._init_db()

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    inputs TEXT,
                    school_id TEXT,
                    requester_id TEXT,
                    preferred_strategy TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS analyses (
                    request_id TEXT PRIMARY KEY,
                    category TEXT,
                    confidence REAL,
                    matched_keywords TEXT,
                    is_ambiguous INTEGER,
                    clarification_question TEXT,
                    missing_inputs TEXT,
                    alternative_categories TEXT,
                    FOREIGN KEY (request_id) REFERENCES requests(id)
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    request_id TEXT PRIMARY KEY,
                    category TEXT,
                    chosen_strategy TEXT,
                    cost_estimate TEXT,
                    explanation TEXT,
                    requires_approval INTEGER,
                    policy_used TEXT,
                    filtered_strategies TEXT,
                    created_at TEXT,
                    FOREIGN KEY (request_id) REFERENCES requests(id)
                );

                CREATE TABLE IF NOT EXISTS executions (
                    request_id TEXT PRIMARY KEY,
                    strategy_name TEXT,
                    success INTEGER,
                    output_reference TEXT,
                    actual_cost REAL,
                    latency_s REAL,
                    is_simulated INTEGER,
                    error TEXT,
                    metadata TEXT,
                    FOREIGN KEY (request_id) REFERENCES requests(id)
                );

                CREATE TABLE IF NOT EXISTS costs (
                    request_id TEXT PRIMARY KEY,
                    strategy_name TEXT,
                    estimated_cost REAL,
                    actual_cost REAL,
                    currency TEXT,
                    source TEXT,
                    is_simulated INTEGER,
                    attempts INTEGER,
                    includes_retries INTEGER,
                    breakdown TEXT,
                    FOREIGN KEY (request_id) REFERENCES requests(id)
                );

                CREATE TABLE IF NOT EXISTS quality_results (
                    request_id TEXT PRIMARY KEY,
                    passed INTEGER,
                    checks TEXT,
                    human_rating INTEGER,
                    is_automated_proxy INTEGER,
                    disclaimer TEXT,
                    FOREIGN KEY (request_id) REFERENCES requests(id)
                );

                CREATE TABLE IF NOT EXISTS config_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    config_data TEXT NOT NULL,
                    author TEXT,
                    saved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS resource_generations (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    parameters TEXT,
                    estimated_units REAL,
                    baseline_units REAL,
                    savings_units REAL,
                    savings_percentage REAL,
                    savings_label TEXT,
                    data_origin TEXT,
                    provider_reported_usage TEXT,
                    latency_s REAL,
                    status TEXT NOT NULL,
                    override_flag INTEGER,
                    override_reason TEXT,
                    config_version INTEGER,
                    is_placeholder INTEGER,
                    placeholder_label TEXT,
                    preview_url TEXT,
                    created_at TEXT,
                    purpose_fit TEXT
                );

                CREATE TABLE IF NOT EXISTS user_feedback (
                    id TEXT PRIMARY KEY,
                    generation_id TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    suggested_tier TEXT,
                    comment TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_requests_school ON requests(school_id);
                CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
                CREATE INDEX IF NOT EXISTS idx_requests_domain ON requests(domain);
                CREATE INDEX IF NOT EXISTS idx_generations_status ON resource_generations(status);
                CREATE INDEX IF NOT EXISTS idx_generations_purpose ON resource_generations(purpose);
                CREATE INDEX IF NOT EXISTS idx_feedback_gen ON user_feedback(generation_id);
            """)

            try:
                conn.execute("ALTER TABLE resource_generations ADD COLUMN purpose_fit TEXT")
            except Exception:
                pass

            try:
                conn.execute("ALTER TABLE resource_generations ADD COLUMN colour_ready TEXT")
            except Exception:
                pass

    def save_request(self, record: RequestRecord) -> None:
        with self._get_conn() as conn:
            req = record.request
            conn.execute("""
                INSERT OR REPLACE INTO requests
                (id, domain, prompt, inputs, school_id, requester_id,
                 preferred_strategy, status, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req.id, req.domain, req.prompt,
                json.dumps(req.inputs), req.school_id, req.requester_id,
                req.preferred_strategy, record.status.value,
                req.created_at.isoformat(), record.updated_at.isoformat(),
                json.dumps(req.metadata),
            ))

            if record.analysis:
                a = record.analysis
                conn.execute("""
                    INSERT OR REPLACE INTO analyses
                    (request_id, category, confidence, matched_keywords,
                     is_ambiguous, clarification_question, missing_inputs,
                     alternative_categories)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    req.id, a.category, a.confidence,
                    json.dumps(a.matched_keywords), int(a.is_ambiguous),
                    a.clarification_question, json.dumps(a.missing_inputs),
                    json.dumps(a.alternative_categories),
                ))

            if record.decision:
                d = record.decision
                conn.execute("""
                    INSERT OR REPLACE INTO decisions
                    (request_id, category, chosen_strategy, cost_estimate,
                     explanation, requires_approval, policy_used,
                     filtered_strategies, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    req.id, d.category, d.chosen_strategy,
                    json.dumps(d.cost_estimate.model_dump()),
                    json.dumps(d.explanation.model_dump()),
                    int(d.requires_approval), d.policy_used,
                    json.dumps(d.filtered_strategies),
                    d.created_at.isoformat(),
                ))

            if record.execution:
                e = record.execution
                conn.execute("""
                    INSERT OR REPLACE INTO executions
                    (request_id, strategy_name, success, output_reference,
                     actual_cost, latency_s, is_simulated, error, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    req.id, e.strategy_name, int(e.success),
                    e.output_reference, e.actual_cost, e.latency_s,
                    int(e.is_simulated), e.error,
                    json.dumps(e.metadata),
                ))

            if record.cost:
                c = record.cost
                conn.execute("""
                    INSERT OR REPLACE INTO costs
                    (request_id, strategy_name, estimated_cost, actual_cost,
                     currency, source, is_simulated, attempts,
                     includes_retries, breakdown)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    req.id, c.strategy_name, c.estimated_cost, c.actual_cost,
                    c.currency, c.source, int(c.is_simulated), c.attempts,
                    int(c.includes_retries), json.dumps(c.breakdown),
                ))

            if record.quality:
                q = record.quality
                conn.execute("""
                    INSERT OR REPLACE INTO quality_results
                    (request_id, passed, checks, human_rating,
                     is_automated_proxy, disclaimer)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    req.id, int(q.passed),
                    json.dumps([c.model_dump() for c in q.checks]),
                    q.human_rating, int(q.is_automated_proxy), q.disclaimer,
                ))

    def get_request(self, request_id: str) -> Optional[RequestRecord]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM requests WHERE id = ?", (request_id,)
            ).fetchone()
            if not row:
                return None

            request = UserRequest(
                id=row["id"],
                prompt=row["prompt"],
                domain=row["domain"],
                inputs=json.loads(row["inputs"] or "{}"),
                school_id=row["school_id"],
                requester_id=row["requester_id"],
                preferred_strategy=row["preferred_strategy"],
                metadata=json.loads(row["metadata"] or "{}"),
            )

            record = RequestRecord(
                request=request,
                status=RequestStatus(row["status"]),
            )

            # Load analysis
            a_row = conn.execute(
                "SELECT * FROM analyses WHERE request_id = ?", (request_id,)
            ).fetchone()
            if a_row:
                record.analysis = AnalysisResult(
                    category=a_row["category"],
                    confidence=a_row["confidence"],
                    matched_keywords=json.loads(a_row["matched_keywords"] or "[]"),
                    is_ambiguous=bool(a_row["is_ambiguous"]),
                    clarification_question=a_row["clarification_question"],
                    missing_inputs=json.loads(a_row["missing_inputs"] or "[]"),
                    alternative_categories=json.loads(a_row["alternative_categories"] or "[]"),
                )

            # Load decision
            d_row = conn.execute(
                "SELECT * FROM decisions WHERE request_id = ?", (request_id,)
            ).fetchone()
            if d_row:
                cost_est_data = json.loads(d_row["cost_estimate"])
                expl_data = json.loads(d_row["explanation"])
                record.decision = Decision(
                    request_id=request_id,
                    category=d_row["category"],
                    chosen_strategy=d_row["chosen_strategy"],
                    cost_estimate=CostEstimate(**cost_est_data),
                    explanation=DecisionExplanation(**expl_data),
                    requires_approval=bool(d_row["requires_approval"]),
                    policy_used=d_row["policy_used"],
                    filtered_strategies=json.loads(d_row["filtered_strategies"] or "{}"),
                )

            # Load execution
            e_row = conn.execute(
                "SELECT * FROM executions WHERE request_id = ?", (request_id,)
            ).fetchone()
            if e_row:
                record.execution = ExecutionResult(
                    request_id=request_id,
                    strategy_name=e_row["strategy_name"],
                    success=bool(e_row["success"]),
                    output_reference=e_row["output_reference"],
                    actual_cost=e_row["actual_cost"],
                    latency_s=e_row["latency_s"],
                    is_simulated=bool(e_row["is_simulated"]),
                    error=e_row["error"],
                    metadata=json.loads(e_row["metadata"] or "{}"),
                )

            # Load cost
            c_row = conn.execute(
                "SELECT * FROM costs WHERE request_id = ?", (request_id,)
            ).fetchone()
            if c_row:
                record.cost = CostRecord(
                    strategy_name=c_row["strategy_name"],
                    estimated_cost=c_row["estimated_cost"],
                    actual_cost=c_row["actual_cost"],
                    currency=c_row["currency"],
                    source=c_row["source"],
                    is_simulated=bool(c_row["is_simulated"]),
                    attempts=c_row["attempts"],
                    includes_retries=bool(c_row["includes_retries"]),
                    breakdown=json.loads(c_row["breakdown"] or "{}"),
                )

            # Load quality
            q_row = conn.execute(
                "SELECT * FROM quality_results WHERE request_id = ?", (request_id,)
            ).fetchone()
            if q_row:
                from backend.engine.models import QualityCheckResult
                checks_data = json.loads(q_row["checks"] or "[]")
                record.quality = QualityGateResult(
                    passed=bool(q_row["passed"]),
                    checks=[QualityCheckResult(**c) for c in checks_data],
                    human_rating=q_row["human_rating"],
                    is_automated_proxy=bool(q_row["is_automated_proxy"]),
                    disclaimer=q_row["disclaimer"],
                )

            return record

    def list_requests(
        self,
        school_id: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RequestRecord]:
        conditions = []
        params: list[Any] = []

        if school_id:
            conditions.append("r.school_id = ?")
            params.append(school_id)
        if status:
            conditions.append("r.status = ?")
            params.append(status)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        with self._get_conn() as conn:
            rows = conn.execute(f"""
                SELECT r.id FROM requests r {where}
                ORDER BY r.created_at DESC
                LIMIT ? OFFSET ?
            """, params + [limit, offset]).fetchall()

        records = []
        for row in rows:
            record = self.get_request(row["id"])
            if record:
                if category and record.analysis and record.analysis.category != category:
                    continue
                records.append(record)
        return records

    def get_school_spend(
        self,
        school_id: str,
        month: Optional[str] = None,
    ) -> float:
        with self._get_conn() as conn:
            if month:
                row = conn.execute("""
                    SELECT COALESCE(SUM(c.actual_cost), 0) as total
                    FROM costs c
                    JOIN requests r ON c.request_id = r.id
                    WHERE r.school_id = ?
                    AND r.created_at LIKE ?
                """, (school_id, f"{month}%")).fetchone()
            else:
                row = conn.execute("""
                    SELECT COALESCE(SUM(c.actual_cost), 0) as total
                    FROM costs c
                    JOIN requests r ON c.request_id = r.id
                    WHERE r.school_id = ?
                """, (school_id,)).fetchone()
            return float(row["total"]) if row else 0.0

    def get_analytics(
        self,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        filters = filters or {}

        with self._get_conn() as conn:
            # Total requests
            total = conn.execute("SELECT COUNT(*) as cnt FROM requests").fetchone()["cnt"]

            # Total estimated vs actual cost
            costs_row = conn.execute("""
                SELECT
                    COALESCE(SUM(estimated_cost), 0) as total_estimated,
                    COALESCE(SUM(actual_cost), 0) as total_actual,
                    COUNT(*) as cost_records
                FROM costs
            """).fetchone()

            # Successful requests
            successful = conn.execute(
                "SELECT COUNT(*) as cnt FROM requests WHERE status = 'completed'"
            ).fetchone()["cnt"]

            # Average latency
            avg_lat = conn.execute(
                "SELECT AVG(latency_s) as avg_lat FROM executions WHERE success = 1"
            ).fetchone()["avg_lat"] or 0.0

            # Failure rate
            total_executions = conn.execute(
                "SELECT COUNT(*) as cnt FROM executions"
            ).fetchone()["cnt"]
            failed_executions = conn.execute(
                "SELECT COUNT(*) as cnt FROM executions WHERE success = 0"
            ).fetchone()["cnt"]

            # Quality gate pass rate
            total_quality = conn.execute(
                "SELECT COUNT(*) as cnt FROM quality_results"
            ).fetchone()["cnt"]
            passed_quality = conn.execute(
                "SELECT COUNT(*) as cnt FROM quality_results WHERE passed = 1"
            ).fetchone()["cnt"]

            # By strategy
            by_strategy = conn.execute("""
                SELECT strategy_name,
                    COUNT(*) as count,
                    SUM(actual_cost) as total_cost,
                    AVG(actual_cost) as avg_cost
                FROM costs
                GROUP BY strategy_name
            """).fetchall()

            # By school
            by_school = conn.execute("""
                SELECT r.school_id,
                    COUNT(*) as count,
                    COALESCE(SUM(c.actual_cost), 0) as total_cost
                FROM requests r
                LEFT JOIN costs c ON r.id = c.request_id
                WHERE r.school_id IS NOT NULL
                GROUP BY r.school_id
            """).fetchall()

            return {
                "total_requests": total,
                "successful_requests": successful,
                "total_estimated_cost": costs_row["total_estimated"],
                "total_actual_cost": costs_row["total_actual"],
                "cost_per_successful_request": (
                    costs_row["total_actual"] / successful if successful > 0 else 0
                ),
                "average_latency_s": round(avg_lat, 3),
                "failure_rate": (
                    failed_executions / total_executions if total_executions > 0 else 0
                ),
                "quality_gate_pass_rate": (
                    passed_quality / total_quality if total_quality > 0 else 0
                ),
                "by_strategy": [
                    {
                        "strategy": r["strategy_name"],
                        "count": r["count"],
                        "total_cost": r["total_cost"],
                        "avg_cost": r["avg_cost"],
                    }
                    for r in by_strategy
                ],
                "by_school": [
                    {
                        "school_id": r["school_id"],
                        "count": r["count"],
                        "total_cost": r["total_cost"],
                    }
                    for r in by_school
                ],
                "all_values_simulated": True,
            }

    def get_analytics_summary(self, domain: Optional[str] = None) -> dict[str, Any]:
        """Backward compatible summary alias."""
        return self.get_analytics()

    def save_config_version(
        self, domain: str, version: int, config_data: dict[str, Any], author: str
    ) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO config_versions (domain, version, config_data, author, saved_at)
                VALUES (?, ?, ?, ?, ?)
            """, (domain, version, json.dumps(config_data), author, datetime.now(timezone.utc).isoformat()))

    def get_config_versions(self, domain: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM config_versions
                WHERE domain = ?
                ORDER BY version DESC
            """, (domain,)).fetchall()
            return [
                {
                    "id": r["id"],
                    "domain": r["domain"],
                    "version": r["version"],
                    "config_data": json.loads(r["config_data"]),
                    "author": r["author"],
                    "saved_at": r["saved_at"],
                }
                for r in rows
            ]

    def set_human_rating(self, request_id: str, rating: int) -> bool:
        """Store optional 1 to 5 human rating for a request result."""
        if not (1 <= rating <= 5):
            raise ValueError("Rating must be between 1 and 5")
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE quality_results SET human_rating = ? WHERE request_id = ?",
                (rating, request_id)
            )
            return cur.rowcount > 0

    def get_showback_report(self) -> dict[str, Any]:
        """
        Generate showback report: spend, requests, reuse rate, and effort mix
        by school and by purpose.
        """
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    r.school_id,
                    d.category,
                    d.chosen_strategy,
                    COALESCE(c.actual_cost, 0.0) as actual_cost,
                    e.metadata
                FROM requests r
                LEFT JOIN decisions d ON r.id = d.request_id
                LEFT JOIN costs c ON r.id = c.request_id
                LEFT JOIN executions e ON r.id = e.request_id
            """).fetchall()

            strategy_effort = {
                "reuse": "Reuse",
                "template_outline": "Quick",
                "draft": "Quick",
                "standard": "Standard",
                "premium": "Print-quality",
            }

            by_school: dict[str, dict[str, Any]] = {}
            by_purpose: dict[str, dict[str, Any]] = {}
            total_spend = 0.0
            total_requests = len(rows)
            total_reuse = 0

            for r in rows:
                sid = r["school_id"] or "SCHOOL-001"
                cat = r["category"] or "general"
                strat = r["chosen_strategy"] or "standard"
                cost = float(r["actual_cost"])
                meta = json.loads(r["metadata"]) if r["metadata"] else {}
                is_reuse = meta.get("reused", False) or strat == "reuse"
                effort = strategy_effort.get(strat, "Standard")

                total_spend += cost
                if is_reuse:
                    total_reuse += 1

                # By School
                if sid not in by_school:
                    by_school[sid] = {
                        "school_id": sid,
                        "spend": 0.0,
                        "requests": 0,
                        "reuse_count": 0,
                        "effort_mix": {"Reuse": 0, "Quick": 0, "Standard": 0, "Print-quality": 0},
                    }
                by_school[sid]["spend"] = round(by_school[sid]["spend"] + cost, 4)
                by_school[sid]["requests"] += 1
                if is_reuse:
                    by_school[sid]["reuse_count"] += 1
                by_school[sid]["effort_mix"][effort] = by_school[sid]["effort_mix"].get(effort, 0) + 1

                # By Purpose
                if cat not in by_purpose:
                    by_purpose[cat] = {
                        "category": cat,
                        "spend": 0.0,
                        "requests": 0,
                        "reuse_count": 0,
                        "effort_mix": {"Reuse": 0, "Quick": 0, "Standard": 0, "Print-quality": 0},
                    }
                by_purpose[cat]["spend"] = round(by_purpose[cat]["spend"] + cost, 4)
                by_purpose[cat]["requests"] += 1
                if is_reuse:
                    by_purpose[cat]["reuse_count"] += 1
                by_purpose[cat]["effort_mix"][effort] = by_purpose[cat]["effort_mix"].get(effort, 0) + 1

            for s in by_school.values():
                s["reuse_rate"] = round(s["reuse_count"] / s["requests"], 3) if s["requests"] > 0 else 0.0

            for p in by_purpose.values():
                p["reuse_rate"] = round(p["reuse_count"] / p["requests"], 3) if p["requests"] > 0 else 0.0

            return {
                "total_spend": round(total_spend, 4),
                "total_requests": total_requests,
                "overall_reuse_rate": round(total_reuse / total_requests, 3) if total_requests > 0 else 0.0,
                "by_school": list(by_school.values()),
                "by_purpose": list(by_purpose.values()),
                "is_simulated": True,
            }

    def save_generation(self, gen: dict[str, Any]) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO resource_generations
                (id, prompt, purpose, tier, parameters, estimated_units,
                 baseline_units, savings_units, savings_percentage, savings_label,
                 data_origin, provider_reported_usage, latency_s, status,
                 override_flag, override_reason, config_version, is_placeholder,
                 placeholder_label, preview_url, created_at, purpose_fit, colour_ready)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                gen.get("id") or gen.get("generation_id"),
                gen.get("prompt", ""),
                gen.get("purpose", ""),
                gen.get("tier", ""),
                json.dumps(gen.get("parameters", {})),
                gen.get("estimated_units") or gen.get("compute_units") or 0.0,
                gen.get("baseline_units") or 1.0,
                gen.get("savings_units") or gen.get("avoided_units") or 0.0,
                gen.get("savings_percentage", 0.0),
                gen.get("savings_label", ""),
                gen.get("data_origin", "simulated"),
                json.dumps(gen.get("provider_reported_usage")) if gen.get("provider_reported_usage") is not None else None,
                gen.get("latency_s", 0.0),
                gen.get("status", "completed"),
                1 if gen.get("override_flag") else 0,
                gen.get("override_reason"),
                gen.get("config_version", 1),
                1 if gen.get("is_placeholder", True) else 0,
                gen.get("placeholder_label", ""),
                gen.get("preview_url") or gen.get("preview_image_url"),
                gen.get("created_at") or datetime.now(timezone.utc).isoformat(),
                json.dumps(gen.get("purpose_fit")) if gen.get("purpose_fit") is not None else None,
                json.dumps(gen.get("colour_ready")) if gen.get("colour_ready") is not None else None,
            ))

    def get_generation(self, gen_id: str) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM resource_generations WHERE id = ?", (gen_id,)).fetchone()
            if not row:
                return None
            return self._row_to_generation(row)

    def list_generations(
        self,
        purpose: Optional[str] = None,
        tier: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM resource_generations WHERE 1=1"
        params: list[Any] = []
        if purpose:
            query += " AND purpose = ?"
            params.append(purpose)
        if tier:
            query += " AND tier = ?"
            params.append(tier)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_generation(r) for r in rows]

    def _row_to_generation(self, row: sqlite3.Row) -> dict[str, Any]:
        purpose_fit_raw = row["purpose_fit"] if "purpose_fit" in row.keys() else None
        purpose_fit = json.loads(purpose_fit_raw) if purpose_fit_raw else None
        colour_ready_raw = row["colour_ready"] if "colour_ready" in row.keys() else None
        colour_ready = json.loads(colour_ready_raw) if colour_ready_raw else None
        return {
            "id": row["id"],
            "generation_id": row["id"],
            "prompt": row["prompt"],
            "purpose": row["purpose"],
            "tier": row["tier"],
            "parameters": json.loads(row["parameters"] or "{}"),
            "estimated_units": row["estimated_units"],
            "baseline_units": row["baseline_units"],
            "savings_units": row["savings_units"],
            "savings_percentage": row["savings_percentage"],
            "savings_label": row["savings_label"],
            "data_origin": row["data_origin"],
            "provider_reported_usage": json.loads(row["provider_reported_usage"]) if row["provider_reported_usage"] else None,
            "latency_s": row["latency_s"],
            "status": row["status"],
            "override_flag": bool(row["override_flag"]),
            "override_reason": row["override_reason"],
            "config_version": row["config_version"],
            "is_placeholder": bool(row["is_placeholder"]),
            "placeholder_label": row["placeholder_label"],
            "preview_url": row["preview_url"],
            "created_at": row["created_at"],
            "purpose_fit": purpose_fit,
            "colour_ready": colour_ready,
        }

    def save_feedback(self, feedback: dict[str, Any]) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO user_feedback
                (id, generation_id, rating, suggested_tier, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                feedback.get("id"),
                feedback.get("generation_id"),
                feedback.get("rating"),
                feedback.get("suggested_tier"),
                feedback.get("comment"),
                feedback.get("created_at") or datetime.now(timezone.utc).isoformat(),
            ))

    def get_feedback(self, generation_id: str) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM user_feedback WHERE generation_id = ? ORDER BY created_at DESC LIMIT 1",
                (generation_id,),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    def list_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM user_feedback ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_generation_summary(self) -> dict[str, Any]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM resource_generations").fetchall()
            total_requests = len(rows)
            success_count = 0
            failed_count = 0
            cumulative_units_saved = 0.0
            cumulative_units_spent = 0.0

            origin_split: dict[str, dict[str, Any]] = {
                "simulated": {"units_saved": 0.0, "units_spent": 0.0, "count": 0},
                "provider_reported": {"units_saved": 0.0, "units_spent": 0.0, "count": 0},
                "measured": {"units_saved": 0.0, "units_spent": 0.0, "count": 0},
            }

            fit_passed_count = 0
            fit_failed_count = 0

            for r in rows:
                status = r["status"]
                origin = r["data_origin"] or "simulated"
                if origin not in origin_split:
                    origin_split[origin] = {"units_saved": 0.0, "units_spent": 0.0, "count": 0}

                units = float(r["estimated_units"] or 0.0)
                savings = float(r["savings_units"] or 0.0)

                cumulative_units_spent += units
                origin_split[origin]["units_spent"] = round(origin_split[origin]["units_spent"] + units, 2)
                origin_split[origin]["count"] += 1

                if "purpose_fit" in r.keys() and r["purpose_fit"]:
                    try:
                        pf = json.loads(r["purpose_fit"])
                        if pf.get("verdict") in ("yes", "partly"):
                            fit_passed_count += 1
                        else:
                            fit_failed_count += 1
                    except Exception:
                        pass

                if status == "completed":
                    success_count += 1
                    if savings > 0:
                        cumulative_units_saved += savings
                        origin_split[origin]["units_saved"] = round(origin_split[origin]["units_saved"] + savings, 2)
                else:
                    failed_count += 1

            saved_rounded = round(cumulative_units_saved, 2)
            total_evaluated_fit = fit_passed_count + fit_failed_count
            fit_pass_rate = round(fit_passed_count / max(1, total_evaluated_fit), 2) if total_evaluated_fit > 0 else 1.0

            return {
                "total_requests": total_requests,
                "total_generations": total_requests,
                "successful_generations": success_count,
                "failed_generations": failed_count,
                "fit_passed_count": fit_passed_count,
                "fit_failed_count": fit_failed_count,
                "fit_pass_rate": fit_pass_rate,
                "cumulative_units_saved": saved_rounded,
                "avoided_units": saved_rounded,
                "cumulative_units_spent": round(cumulative_units_spent, 1),
                "compute_units": round(cumulative_units_spent, 1),
                "data_origin_split": origin_split,
                "running_total_label": f"You have saved about {saved_rounded} units across {success_count} images (estimated, not measured)",
                "counterfactual_note": "Baseline compute at Maximum tier was not run; savings are estimated avoided compute.",
            }

    def is_healthy(self) -> bool:
        try:
            with self._get_conn() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False
