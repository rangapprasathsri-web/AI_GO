"""
FastAPI application for Adaptive AI Request Optimizer.

Exposes REST endpoints for:
- Purpose capture and request routing
- Side-by-side decision preview (recommended vs next level up)
- Execution and quality gate verification
- Human ratings (1 to 5 stars)
- Role-based responses (requester vs admin)
- School quota tracking and showback report
- Live hot-reloading configuration management
- Workload evaluation with lever savings attribution
"""
from __future__ import annotations

import base64
import io
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.adapters.mock_image import MockImageAdapter
from backend.adapters.mock_text import MockTextAdapter
from backend.adapters.registry import AdapterRegistry
from backend.adapters.reuse_library import ReuseLibraryAdapter
from backend.adapters.template_outline import TemplateOutlineAdapter
from backend.engine.config import load_config_from_file, update_config
from backend.engine.moderation import ModerationHook
from backend.engine.models import (
    DomainConfig,
    PolicyName,
    RequestRecord,
    RequestStatus,
    UserRequest,
)
from backend.engine.orchestrator import Orchestrator
from backend.eval.runner import EvaluationRunner
from backend.eval.workload_generator import generate_workload, get_labelled_routing_dataset
from backend.storage.sqlite_storage import SQLiteStorage

app = FastAPI(
    title="Adaptive AI Request Optimizer",
    description="Intelligent decision layer matching purpose to cost-effective compute",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── State Initialization ──────────────────────────────────────────────
STORAGE = SQLiteStorage(db_path="data/optimizer.db")
REUSE_LIB = ReuseLibraryAdapter()

REGISTRY = AdapterRegistry()
REGISTRY.register(MockImageAdapter())
REGISTRY.register(MockTextAdapter())
REGISTRY.register(TemplateOutlineAdapter())
REGISTRY.register(REUSE_LIB)

DEFAULT_CONFIG_PATH = "backend/domains/education_images.yaml"
CURRENT_CONFIG = load_config_from_file(DEFAULT_CONFIG_PATH)


def get_school_spend(school_id: str) -> float:
    return STORAGE.get_school_spend(school_id)


def create_orchestrator(config: DomainConfig) -> Orchestrator:
    return Orchestrator(
        config=config,
        adapter_lookup=REGISTRY.get,
        school_spend_lookup=get_school_spend,
    )


ORCHESTRATOR = create_orchestrator(CURRENT_CONFIG)
MODERATION = ModerationHook()

# ── Request / Response Models ─────────────────────────────────────────

class RequestSubmission(BaseModel):
    prompt: str = ""
    purpose: Optional[str] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    school_id: str = "SCHOOL-101"
    role: str = "requester"  # "requester" or "admin"
    preferred_strategy: Optional[str] = None
    override_reason: Optional[str] = None
    auto_execute: bool = True


class RatingSubmission(BaseModel):
    request_id: str
    rating: int = Field(ge=1, le=5)


class ConfigUpdateRequest(BaseModel):
    updates: Dict[str, Any]
    author: str = "admin"


# ── Helper Functions ──────────────────────────────────────────────────

def image_to_base64(output_data: Any) -> Optional[str]:
    """Extract and base64-encode image data from execution output."""
    if not output_data or not isinstance(output_data, dict):
        return None
    raw_bytes = output_data.get("image_bytes")
    if raw_bytes and isinstance(raw_bytes, (bytes, bytearray)):
        return f"data:image/png;base64,{base64.b64encode(raw_bytes).decode('ascii')}"
    img_obj = output_data.get("image")
    if img_obj and hasattr(img_obj, "save"):
        buf = io.BytesIO()
        img_obj.save(buf, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    return None


def serialize_record(record: RequestRecord, role: str) -> Dict[str, Any]:
    """Serialize RequestRecord with role-appropriate redaction and image preview."""
    data = record.model_dump()
    is_requester = role == "requester"
    hide_currency = is_requester and CURRENT_CONFIG.policy.hide_currency_from_requester

    # Extract base64 image if available
    preview_url = None
    if record.execution and record.execution.output_data:
        preview_url = image_to_base64(record.execution.output_data)

    data["preview_image_url"] = preview_url
    if "execution" in data and data["execution"]:
        data["execution"]["output_data"] = None

    # Format user-facing cost labels
    if record.decision and record.decision.cost_estimate:
        est = record.decision.cost_estimate.estimated_cost
        if hide_currency:
            data["decision"]["display_cost"] = record.decision.explanation.display_cost
        else:
            data["decision"]["display_cost"] = f"${est:.4f} (simulated)"

    if record.cost:
        if hide_currency:
            data["cost"]["display_actual"] = "Low (Standard Tier)"
        else:
            data["cost"]["display_actual"] = f"${record.cost.actual_cost:.4f} (simulated)"

    return data


# ── Endpoints ─────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Adaptive AI Request Optimizer",
        "active_domain": CURRENT_CONFIG.domain,
        "version": CURRENT_CONFIG.version,
    }


@app.get("/api/config")
def get_config(role: str = Query(default="requester")):
    """Get active domain configuration."""
    cfg = CURRENT_CONFIG.model_dump()
    if role == "requester":
        # Requester view hides internal adapter pricing structures if configured
        if CURRENT_CONFIG.policy.hide_currency_from_requester:
            for s in cfg.get("strategies", {}).values():
                s["price_per_call"] = "(hidden)"
    return cfg


@app.put("/api/config")
def update_domain_config(req: ConfigUpdateRequest):
    """Admin updates configuration dynamically without restart."""
    global CURRENT_CONFIG, ORCHESTRATOR
    try:
        updated = update_config(CURRENT_CONFIG, req.updates)
        CURRENT_CONFIG = updated
        ORCHESTRATOR = create_orchestrator(CURRENT_CONFIG)
        STORAGE.save_config_version(
            domain=CURRENT_CONFIG.domain,
            version=CURRENT_CONFIG.version,
            config_data=CURRENT_CONFIG.model_dump(),
            author=req.author,
        )
        return {
            "success": True,
            "version": CURRENT_CONFIG.version,
            "message": f"Configuration successfully updated to version {CURRENT_CONFIG.version}",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/categories")
def get_categories():
    """Return task categories with display labels, defaults, and quality floors."""
    result = {}
    for cat_id, cat in CURRENT_CONFIG.task_categories.items():
        result[cat_id] = {
            "name": cat.name,
            "defaults": cat.defaults,
            "quality_floor": cat.quality_floor.model_dump() if cat.quality_floor else {},
            "allowed_strategies": cat.allowed_strategies,
            "required_inputs": cat.required_inputs,
        }
    return result


@app.post("/api/request")
def process_user_request(sub: RequestSubmission):
    """
    Main intake endpoint for user requests.
    Supports one-tap purpose selection, classification, quota checks,
    decision making, and execution with quality gate.
    """
    inputs = dict(sub.inputs)

    # 1. PII & Moderation check on prompt
    user_prompt = sub.prompt.strip()
    if not user_prompt and sub.purpose:
        user_prompt = f"Create a {sub.purpose.replace('_', ' ')} for {inputs.get('subject', 'general topic')}"

    req = UserRequest(
        prompt=user_prompt,
        domain=CURRENT_CONFIG.domain,
        inputs=inputs,
        school_id=sub.school_id,
        role=sub.role,
        preferred_strategy=sub.preferred_strategy,
        override_reason=sub.override_reason,
    )

    # Pre-moderation
    mod_check = MODERATION.check_prompt(req)
    if not mod_check.passed:
        return JSONResponse(
            status_code=400,
            content={
                "error": "moderation_blocked",
                "message": mod_check.blocked_reason,
                "flagged_terms": mod_check.flagged_terms,
            },
        )

    # 2. If purpose explicitly selected, inject into inputs
    if sub.purpose:
        req.inputs["_category"] = sub.purpose
        # Pre-fill category defaults if missing
        cat_obj = CURRENT_CONFIG.task_categories.get(sub.purpose)
        if cat_obj and cat_obj.defaults:
            for k, v in cat_obj.defaults.items():
                if k not in req.inputs:
                    req.inputs[k] = v

    # 3. Process via Orchestrator
    record = ORCHESTRATOR.process_request(req, auto_execute=sub.auto_execute)

    # 4. If execution succeeded and passed quality gate, store in reuse library if appropriate
    if (
        record.status == RequestStatus.COMPLETED
        and record.quality
        and record.quality.passed
        and record.execution
        and record.execution.output_data
    ):
        subject = req.inputs.get("subject", req.prompt)
        cat_name = record.decision.category if record.decision else ""
        REUSE_LIB.add_approved_item(
            item_id=f"reuse-{record.request.id}",
            prompt=req.prompt,
            subject=subject,
            category=cat_name,
            resolution=record.execution.metadata.get("resolution", 768),
            colour_mode="bw" if record.execution.metadata.get("is_bw") else "colour",
            output_data=record.execution.output_data,
            output_reference=record.execution.output_reference or f"reuse://{record.request.id}",
            tags=[cat_name] + [w.lower() for w in req.prompt.split() if len(w) > 3],
            approved=True,
        )

    # 5. Persist to storage
    STORAGE.save_request(record)

    # 6. Response packaging
    resp = serialize_record(record, sub.role)

    # Add school budget progress info
    current_spend = STORAGE.get_school_spend(sub.school_id)
    monthly_cap = CURRENT_CONFIG.policy.budgets.per_school_monthly
    pct_used = (current_spend / monthly_cap * 100) if monthly_cap > 0 else 0
    resp["school_budget"] = {
        "school_id": sub.school_id,
        "current_spend": current_spend,
        "monthly_cap": monthly_cap,
        "percentage": round(pct_used, 1),
        "is_alert": pct_used >= 80,
        "is_exceeded": pct_used >= 100,
        "source": "placeholder",
        "is_simulated": True,
    }

    return resp


@app.post("/api/preview")
def generate_decision_preview(sub: RequestSubmission):
    """
    Generate side-by-side decision preview (Recommended vs Next Level Up)
    including mock rendered visual previews without running full request.
    """
    inputs = dict(sub.inputs)
    user_prompt = sub.prompt.strip()
    if not user_prompt and sub.purpose:
        user_prompt = f"Create a {sub.purpose.replace('_', ' ')} for {inputs.get('subject', 'sample')}"

    req = UserRequest(
        prompt=user_prompt,
        domain=CURRENT_CONFIG.domain,
        inputs=inputs,
        school_id=sub.school_id,
        role=sub.role,
    )

    # Moderate
    mod = MODERATION.check_prompt(req)
    if not mod.passed:
        return JSONResponse(status_code=400, content={"error": mod.blocked_reason})

    if sub.purpose:
        req.inputs["_category"] = sub.purpose
        cat_obj = CURRENT_CONFIG.task_categories.get(sub.purpose)
        if cat_obj and cat_obj.defaults:
            for k, v in cat_obj.defaults.items():
                if k not in req.inputs:
                    req.inputs[k] = v

    # Dry-run decision
    analysis = ORCHESTRATOR._analyser.analyse(req, CURRENT_CONFIG)
    if not analysis.category and sub.purpose:
        analysis.category = sub.purpose

    decision = ORCHESTRATOR.make_decision(req, analysis)
    rec_strategy = CURRENT_CONFIG.strategies.get(decision.chosen_strategy)

    # Render mock preview for recommended tier
    rec_preview_b64 = None
    if rec_strategy:
        rec_adapter = REGISTRY.get(rec_strategy.adapter)
        if rec_adapter:
            dry_exec = rec_adapter.execute(rec_strategy, req)
            if dry_exec.output_data:
                rec_preview_b64 = image_to_base64(dry_exec.output_data)

    # Next tier
    next_alt = decision.explanation.alternatives[0] if decision.explanation.alternatives else None
    next_preview_b64 = None
    if next_alt:
        next_strategy = CURRENT_CONFIG.strategies.get(next_alt.strategy_name)
        if next_strategy:
            next_adapter = REGISTRY.get(next_strategy.adapter)
            if next_adapter:
                next_exec = next_adapter.execute(next_strategy, req)
                if next_exec.output_data:
                    next_preview_b64 = image_to_base64(next_exec.output_data)

    hide_curr = (sub.role == "requester") and CURRENT_CONFIG.policy.hide_currency_from_requester

    return {
        "analysis": analysis.model_dump(),
        "recommended": {
            "strategy_name": decision.chosen_strategy,
            "effort_level": rec_strategy.effort_level if rec_strategy else "Standard",
            "levers": rec_strategy.levers if rec_strategy else {},
            "display_cost": decision.explanation.display_cost,
            "estimated_cost": decision.cost_estimate.estimated_cost if not hide_curr else None,
            "reason": decision.explanation.reason,
            "preview_image": rec_preview_b64,
            "quality_status": "Meets all quality checks",
        },
        "next_tier": {
            "strategy_name": next_alt.strategy_name if next_alt else None,
            "effort_level": next_alt.effort_level if next_alt else None,
            "what_changes": next_alt.trade_off if next_alt else "Highest available tier",
            "tradeoff": next_alt.trade_off if next_alt else "Already at highest option",
            "display_cost": next_alt.display_cost if next_alt else "N/A",
            "cost_difference": (next_alt.estimated_cost - decision.cost_estimate.estimated_cost) if (next_alt and not hide_curr) else None,
            "preview_image": next_preview_b64,
            "requires_approval": (
                next_strategy.price_per_call > CURRENT_CONFIG.policy.approval_required_above_cost
                if next_alt and next_strategy else False
            ),
        } if next_alt else None,
        "is_simulated": True,
    }


@app.post("/api/rating")
def submit_rating(sub: RatingSubmission):
    """Store 1 to 5 star human rating for a generated output."""
    ok = STORAGE.set_human_rating(sub.request_id, sub.rating)
    if not ok:
        raise HTTPException(status_code=404, detail="Request ID not found")
    return {"success": True, "request_id": sub.request_id, "rating": sub.rating}


@app.get("/api/showback")
def get_showback():
    """Admin showback report table."""
    report = STORAGE.get_showback_report()
    cap = CURRENT_CONFIG.policy.budgets.per_school_monthly
    schools = []
    for s in report.get("by_school", []):
        spend = s.get("spend", 0.0)
        req_cnt = s.get("requests", 0)
        re_cnt = s.get("reuse_count", 0)
        schools.append({
            "school_id": s.get("school_id"),
            "requests_count": req_cnt,
            "total_spend": spend,
            "monthly_cap": cap,
            "percentage_of_cap": round((spend / cap * 100), 1) if cap > 0 else 0,
            "top_category": "colouring_worksheet",
            "reuse_rate": round(re_cnt / req_cnt, 4) if req_cnt > 0 else 0.0,
            "effort_mix": s.get("effort_mix", {}),
        })
    report["schools"] = schools
    return report


@app.get("/api/analytics")
def get_analytics():
    """Summary analytics for admin dashboard."""
    return STORAGE.get_analytics_summary(CURRENT_CONFIG.domain)


@app.post("/api/eval")
def run_evaluation(sample_size: int = Query(default=30, ge=10, le=100), seed: int = Query(default=42)):
    """
    Run evaluation comparing baseline against adaptive optimizer
    and calculate lever savings attribution.
    """
    from backend.eval.runner import attribute_savings_by_lever
    runner = EvaluationRunner(config=CURRENT_CONFIG, adapter_registry=REGISTRY)
    workload = generate_workload(domain=CURRENT_CONFIG.domain, size=sample_size, seed=seed)
    baseline_records = runner.run_policy(workload, PolicyName.BASELINE_ALWAYS_MAX)
    opt_records = runner.run_policy(workload, CURRENT_CONFIG.policy.active)
    b_metrics = runner.compute_metrics(baseline_records, "baseline_always_max")
    o_metrics = runner.compute_metrics(opt_records, CURRENT_CONFIG.policy.active.value)
    attribution = attribute_savings_by_lever(baseline_records, opt_records)
    savings = max(0.0, b_metrics["total_cost"] - o_metrics["total_cost"])
    savings_pct = (savings / b_metrics["total_cost"] * 100) if b_metrics["total_cost"] > 0 else 0.0
    return {
        "baseline_cost": b_metrics["total_cost"],
        "optimized_cost": o_metrics["total_cost"],
        "savings": savings,
        "savings_pct": savings_pct,
        "reuse_hit_rate": o_metrics.get("reuse_hit_rate", 0.0),
        "attribution": attribution,
        "baseline_metrics": b_metrics,
        "optimized_metrics": o_metrics,
    }


# ── Mount Static Frontend Files ───────────────────────────────────────
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
frontend_dir.mkdir(parents=True, exist_ok=True)

if (frontend_dir / "index.html").exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(str(frontend_dir / "index.html"))
