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

from fastapi import FastAPI, HTTPException, Header, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.adapters.mock_image import MockImageAdapter
from backend.adapters.mock_text import MockTextAdapter
from backend.adapters.registry import AdapterRegistry
from backend.adapters.reuse_library import ReuseLibraryAdapter
from backend.adapters.template_outline import TemplateOutlineAdapter
from backend.engine.config import load_config_from_file, update_config, validate_config, ConfigValidationError
from backend.engine.moderation import ModerationHook
from backend.engine.models import (
    DomainConfig,
    PolicyName,
    RequestRecord,
    RequestStatus,
    StrategyConfig,
    UserRequest,
)
from backend.engine.orchestrator import Orchestrator
from backend.engine.purpose_fit import PurposeFitChecker
from backend.engine.measurement import detect_measurement_level
from backend.benchmarks.runner import BenchmarkRunner
from backend.storage.replay_cache import ReplayCache
from backend.engine.resource import ResourceEstimator, compute_tier_units, compute_savings
from backend.engine.resource_optimizer import ResourceOptimizerService
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

RESOURCE_CONFIG_PATH = "backend/domains/image_resource_optimizer.yaml"
RESOURCE_CONFIG = load_config_from_file(RESOURCE_CONFIG_PATH)
RESOURCE_OPTIMIZER = ResourceOptimizerService(config=RESOURCE_CONFIG)

# Seed initial config version in storage if not present
if not STORAGE.get_config_versions(CURRENT_CONFIG.domain):
    STORAGE.save_config_version(
        domain=CURRENT_CONFIG.domain,
        version=CURRENT_CONFIG.version,
        config_data=CURRENT_CONFIG.model_dump(),
        author="system_init",
    )

if not STORAGE.get_config_versions(RESOURCE_CONFIG.domain):
    STORAGE.save_config_version(
        domain=RESOURCE_CONFIG.domain,
        version=RESOURCE_CONFIG.version,
        config_data=RESOURCE_CONFIG.model_dump(),
        author="system_init",
    )


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
    domain: Optional[str] = None


class RecommendRequest(BaseModel):
    prompt: str = ""
    purpose: str = "coloring_sheet"
    required_detail: Optional[str] = None
    target_resolution: Optional[int] = None
    print_use: bool = False
    print_size: Optional[str] = None
    latency_max_s: Optional[float] = None
    budget_units: Optional[float] = None


class GenerateRequest(BaseModel):
    prompt: str = ""
    purpose: str = "coloring_sheet"
    confirmed_tier: str = "economy"
    override_flag: bool = False
    override_reason: Optional[str] = None
    override_confirmed: bool = False
    required_detail: Optional[str] = None
    target_resolution: Optional[int] = None
    print_use: bool = False
    print_size: Optional[str] = None
    budget_units: Optional[float] = None
    use_replay: bool = False


class FeedbackRequest(BaseModel):
    generation_id: str
    rating: str  # "yes" or "no"
    comment: Optional[str] = None


def sanitize_config(cfg_dict: dict[str, Any]) -> dict[str, Any]:
    """Sanitize configuration to ensure no credentials or secrets are exposed."""
    clean = dict(cfg_dict)
    for key in ["secret", "api_key", "password", "token", "credentials"]:
        clean.pop(key, None)
    return clean


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

@app.get("/health")
@app.get("/api/health")
def health_check():
    meas_env = detect_measurement_level()
    return {
        "status": "healthy",
        "service": "Adaptive AI Image Resource Optimizer",
        "active_domain": CURRENT_CONFIG.domain,
        "resource_domain": RESOURCE_CONFIG.domain,
        "version": RESOURCE_CONFIG.version,
        "measurement_level": meas_env.level,
        "measurement_level_name": meas_env.level_name,
        "measurement_environment": meas_env.to_dict(),
    }


@app.get("/config")
@app.get("/api/config")
def get_config(domain: Optional[str] = None, role: str = Query(default="requester")):
    """Get active domain configuration (sanitized, no secrets)."""
    if domain == "education_images":
        cfg = CURRENT_CONFIG.model_dump()
        if role == "requester" and CURRENT_CONFIG.policy.hide_currency_from_requester:
            for s in cfg.get("strategies", {}).values():
                s["price_per_call"] = "(hidden)"
        return sanitize_config(cfg)
    # Default to RESOURCE_CONFIG which carries strategies, task_categories, tiers, and purposes
    return sanitize_config(RESOURCE_CONFIG.model_dump())


@app.put("/config")
@app.put("/api/config")
def update_domain_config(req: ConfigUpdateRequest):
    """Admin updates configuration dynamically without restart."""
    global CURRENT_CONFIG, ORCHESTRATOR, RESOURCE_CONFIG, RESOURCE_OPTIMIZER
    is_legacy = (req.domain == "education_images") or (
        "tiers" not in req.updates and "purposes" not in req.updates and "task_categories" in req.updates
    ) or (
        "policy" in req.updates and "approval_required_above_cost" in req.updates["policy"]
    )
    if is_legacy:
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
                "config": sanitize_config(CURRENT_CONFIG.model_dump()),
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        updated = update_config(RESOURCE_CONFIG, req.updates)
        val_errors, _ = validate_config(updated)
        if val_errors:
            raise ConfigValidationError(val_errors)
        RESOURCE_CONFIG = updated
        RESOURCE_OPTIMIZER = ResourceOptimizerService(config=RESOURCE_CONFIG)
        STORAGE.save_config_version(
            domain=RESOURCE_CONFIG.domain,
            version=RESOURCE_CONFIG.version,
            config_data=RESOURCE_CONFIG.model_dump(),
            author=req.author,
        )
        return {
            "success": True,
            "version": RESOURCE_CONFIG.version,
            "message": f"Configuration successfully updated to version {RESOURCE_CONFIG.version}",
            "config": sanitize_config(RESOURCE_CONFIG.model_dump()),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class RollbackRequest(BaseModel):
    version: Optional[int] = None
    author: str = "admin"


@app.get("/api/config/versions")
def list_config_versions():
    """Retrieve history of configuration versions."""
    return STORAGE.get_config_versions(CURRENT_CONFIG.domain)


@app.post("/api/config/rollback")
def rollback_configuration(req: RollbackRequest):
    """Roll back configuration to specified or previous version."""
    global CURRENT_CONFIG, ORCHESTRATOR
    versions = STORAGE.get_config_versions(CURRENT_CONFIG.domain)
    if not versions:
        raise HTTPException(status_code=400, detail="No previous configuration versions found to rollback")

    target_version_data = None
    if req.version is not None:
        for v in versions:
            if v["version"] == req.version:
                target_version_data = v["config_data"]
                break
    else:
        # Default to previous version
        for v in versions:
            if v["version"] < CURRENT_CONFIG.version:
                target_version_data = v["config_data"]
                break
        if not target_version_data and versions:
            target_version_data = versions[-1]["config_data"]

    if not target_version_data:
        raise HTTPException(status_code=404, detail=f"Target version {req.version} not found")

    from backend.engine.config import _parse_config_dict
    new_cfg = _parse_config_dict(target_version_data)
    new_cfg.version = CURRENT_CONFIG.version + 1
    CURRENT_CONFIG = new_cfg
    ORCHESTRATOR = create_orchestrator(CURRENT_CONFIG)
    STORAGE.save_config_version(
        domain=CURRENT_CONFIG.domain,
        version=CURRENT_CONFIG.version,
        config_data=CURRENT_CONFIG.model_dump(),
        author=f"{req.author} (rollback)",
    )
    return {
        "success": True,
        "version": CURRENT_CONFIG.version,
        "message": f"Successfully rolled back configuration to version {CURRENT_CONFIG.version}",
        "config": CURRENT_CONFIG.model_dump(),
    }


@app.post("/recommend")
@app.post("/api/recommend")
def recommend_tier(req: RecommendRequest):
    """
    Recommend lowest suitable tier meeting requirements.
    Explains the deciding factor in plain language and provides counterfactual estimates.
    """
    purpose_key = req.purpose.lower().replace(" ", "_") if req.purpose else "coloring_sheet"
    requires_clarification = False
    missing_inputs = []

    if purpose_key == "custom":
        if not req.required_detail and not req.target_resolution and not req.print_use and not req.print_size:
            requires_clarification = True
            missing_inputs = ["required_detail", "target_resolution", "print_use"]

    rec = RESOURCE_OPTIMIZER.recommend(
        prompt=req.prompt,
        purpose=req.purpose,
        print_use=req.print_use,
        print_size=req.print_size,
        required_detail=req.required_detail,
        target_resolution=req.target_resolution,
        budget_units=req.budget_units,
        latency_max_s=req.latency_max_s,
    )

    if requires_clarification:
        rec["status"] = "needs_clarification"
        rec["requires_clarification"] = True
        rec["missing_inputs"] = missing_inputs
    else:
        rec["requires_clarification"] = False
        rec["missing_inputs"] = []

    return rec


@app.post("/generate")
@app.post("/api/generate")
def generate_image_tier(req: GenerateRequest):
    """
    Generate image at confirmed tier, enforce hard budget,
    and compute counterfactual savings versus maximum tier.
    """
    global RESOURCE_CONFIG
    import uuid

    if req.use_replay:
        rc = ReplayCache()
        cached = rc.get_replay(req.purpose, req.confirmed_tier.lower())
        if cached:
            return cached

    user_req = UserRequest(
        prompt=req.prompt or f"Image for {req.purpose}",
        domain=RESOURCE_CONFIG.domain,
        inputs={"_category": req.purpose, "print_size": req.print_size},
    )
    mod_check = MODERATION.check_prompt(user_req)
    if not mod_check.passed:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "moderation_blocked",
                "message": mod_check.blocked_reason,
                "flagged_terms": mod_check.flagged_terms,
            },
        )

    rec_result = RESOURCE_OPTIMIZER.recommend(
        prompt=req.prompt,
        purpose=req.purpose,
        print_use=req.print_use,
        print_size=req.print_size,
        required_detail=req.required_detail,
        target_resolution=req.target_resolution,
        budget_units=req.budget_units,
    )
    rec_tier = rec_result["recommended_tier"]

    val = RESOURCE_OPTIMIZER.validate_override(
        recommended_tier=rec_tier,
        override_tier=req.confirmed_tier,
        purpose=req.purpose,
        override_confirmed=req.override_confirmed,
        budget_units=req.budget_units,
    )

    if not val["allowed"]:
        if val["status"] == "blocked_by_budget":
            raise HTTPException(status_code=400, detail=val["error"])
        elif val["status"] == "needs_confirmation":
            return JSONResponse(
                status_code=400,
                content={
                    "error": "below_floor_confirmation_required",
                    "status": "needs_confirmation",
                    "warning": val["warning"],
                    "requires_confirmation": True,
                    "recommended_tier": rec_tier,
                    "confirmed_tier": req.confirmed_tier,
                },
            )
        else:
            raise HTTPException(status_code=400, detail=val.get("error", "Override not allowed"))

    tier_info = RESOURCE_CONFIG.tiers.get(req.confirmed_tier.lower())
    if not tier_info:
        raise HTTPException(status_code=400, detail=f"Unknown tier: {req.confirmed_tier}")

    strat_params = dict(tier_info.get("params", {}))
    strat_params["model_factor"] = tier_info.get("model_factor", 1.0)
    strategy = StrategyConfig(
        name=req.confirmed_tier.lower(),
        adapter="mock_image",
        params=strat_params,
        price_per_call=tier_info.get("price_per_call", 0.0),
        effort_level=tier_info.get("display", req.confirmed_tier.title()),
    )

    start_t = time.time()
    mock_adapter = REGISTRY.get("mock_image")
    exec_result = mock_adapter.execute(strategy, user_req)
    latency_s = round(time.time() - start_t, 3)

    width = strat_params.get("width", 768)
    height = strat_params.get("height", 768)
    steps = strat_params.get("steps", 20)
    model_factor = tier_info.get("model_factor", 1.0)
    units = compute_tier_units(width, height, steps, model_factor)

    max_tier = RESOURCE_CONFIG.tiers.get("maximum", {})
    max_params = max_tier.get("params", {"width": 1536, "height": 1536, "steps": 50})
    max_factor = max_tier.get("model_factor", 1.0)
    baseline_units = compute_tier_units(
        max_params.get("width", 1536),
        max_params.get("height", 1536),
        max_params.get("steps", 50),
        max_factor,
    )

    # Automated Purpose-Fit Image Verification
    fit_checker = PurposeFitChecker(
        RESOURCE_CONFIG.fit_thresholds if hasattr(RESOURCE_CONFIG, "fit_thresholds") else None
    )
    img_data = None
    if exec_result.output_data:
        img_data = exec_result.output_data.get("image_bytes")
        if not img_data and "image" in exec_result.output_data:
            buf = io.BytesIO()
            exec_result.output_data["image"].save(buf, format="PNG")
            img_data = buf.getvalue()

    fit_res = fit_checker.evaluate_image(
        image_bytes=img_data or b"",
        purpose=req.purpose,
        parameters=strat_params,
        print_use=req.print_use,
        print_size=req.print_size,
    )

    # Compute savings conditional on purpose fitness:
    savings = compute_savings(units, baseline_units, fit_verdict=fit_res.verdict)

    if not exec_result.success:
        savings_units = 0.0
        savings_pct = 0.0
        gen_status = "failed"
        savings_label = "generation failed (no savings)"
    elif fit_res.verdict == "no":
        savings_units = 0.0
        savings_pct = 0.0
        gen_status = "completed"
        savings_label = "no savings claimed: output failed purpose-fit verification"
    else:
        savings_units = savings["savings_units"]
        savings_pct = savings["savings_percentage"]
        gen_status = "completed"
        savings_label = "estimated savings vs maximum tier (not run)"

    gen_id = f"gen-{uuid.uuid4().hex[:10]}"
    preview_url = image_to_base64(exec_result.output_data) if exec_result.output_data else None

    energy_cfg = RESOURCE_CONFIG.energy_model or {}
    if energy_cfg.get("enabled") and energy_cfg.get("source"):
        wh_rate = energy_cfg.get("wh_per_unit", 0.05) or 0.05
        energy_wh = round(units * wh_rate, 4)
        carbon_g = round(energy_wh * 0.4, 4)
        energy_label = f"modelled estimate from {energy_cfg.get('source')}"
    else:
        energy_wh = None
        carbon_g = None
        energy_label = "not estimated (energy model disabled)"

    is_override = req.confirmed_tier.lower() != rec_tier.lower() or req.override_flag

    gen_record = {
        "id": gen_id,
        "prompt": req.prompt,
        "purpose": req.purpose,
        "tier": req.confirmed_tier.lower(),
        "parameters": strat_params,
        "estimated_units": units,
        "baseline_units": baseline_units,
        "savings_units": savings_units,
        "savings_percentage": savings_pct,
        "savings_label": savings_label,
        "savings_eligible": fit_res.verdict != "no",
        "data_origin": "simulated",
        "label": "simulated estimate, not measured energy",
        "formula": "steps * megapixels * model_factor",
        "provider_reported_usage": None,
        "energy_wh": energy_wh,
        "carbon_co2_g": carbon_g,
        "energy_label": energy_label,
        "latency_s": latency_s,
        "status": gen_status,
        "override_flag": is_override,
        "override_reason": req.override_reason if is_override else None,
        "config_version": RESOURCE_CONFIG.version,
        "is_placeholder": True,
        "placeholder_label": "DEMO PLACEHOLDER: illustrative placeholder asset, not real model output",
        "preview_url": preview_url,
        "purpose_fit": fit_res.to_dict(),
        "created_at": datetime.utcnow().isoformat(),
        "explanation": rec_result.get("explanation"),
        "deciding_factor": rec_result.get("deciding_factor"),
    }

    STORAGE.save_generation(gen_record)
    return gen_record


@app.get("/history")
def get_resource_history(
    purpose: Optional[str] = None,
    tier: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Retrieve history of image generations with units and savings."""
    return STORAGE.list_generations(purpose=purpose, tier=tier, status=status, limit=limit)


@app.get("/history/{gen_id}")
@app.get("/api/history/{gen_id}")
def get_resource_generation_by_id(gen_id: str):
    """Retrieve a single generation or request by ID."""
    record = STORAGE.get_generation(gen_id)
    if record:
        return record
    req_record = STORAGE.get_request(gen_id)
    if req_record:
        return serialize_record(req_record, role="admin")
    raise HTTPException(status_code=404, detail=f"Generation '{gen_id}' not found")


@app.get("/summary")
@app.get("/api/summary")
def get_resource_summary():
    """Retrieve cumulative savings summary with data_origin split."""
    summary = STORAGE.get_generation_summary()
    summary["energy_wh"] = None
    summary["carbon_co2_g"] = None
    summary["energy_label"] = "not estimated (energy model disabled)"
    return summary


@app.get("/history/export.csv")
@app.get("/api/history/export")
def export_history_csv():
    """Export generation history as CSV."""
    import csv
    records = STORAGE.list_generations(limit=1000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "timestamp", "purpose", "tier", "estimated_units",
        "baseline_units", "savings_units", "savings_percentage",
        "data_origin", "status", "override_flag", "override_reason"
    ])
    for r in records:
        writer.writerow([
            r.get("id"),
            r.get("created_at"),
            r.get("purpose"),
            r.get("tier"),
            r.get("estimated_units"),
            r.get("baseline_units"),
            r.get("savings_units"),
            r.get("savings_percentage"),
            r.get("data_origin"),
            r.get("status"),
            r.get("override_flag"),
            r.get("override_reason") or "",
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=generation_history.csv"}
    )


@app.post("/feedback")
@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest):
    """
    Store 'Good enough? Yes/No' user feedback.
    A 'No' rating suggests the next tier up with the reason; it never escalates automatically.
    """
    import uuid
    gen = STORAGE.get_generation(req.generation_id)
    current_tier = gen.get("tier", "economy") if gen else "economy"
    suggested_tier = None
    suggestion_reason = None

    if req.rating.lower() == "no":
        if current_tier == "economy":
            suggested_tier = "standard"
            suggestion_reason = "Standard tier provides higher resolution and sampling steps for crisper details."
        elif current_tier == "standard":
            suggested_tier = "maximum"
            suggestion_reason = "Maximum tier activates full unconstrained model capability and print-grade detail."
        else:
            suggested_tier = "maximum"
            suggestion_reason = "Already generated at Maximum tier. Consider adding specific prompt constraints."

    feedback_id = f"fb-{uuid.uuid4().hex[:8]}"
    feedback_record = {
        "id": feedback_id,
        "generation_id": req.generation_id,
        "rating": req.rating.lower(),
        "suggested_tier": suggested_tier,
        "comment": req.comment or suggestion_reason,
        "created_at": datetime.utcnow().isoformat(),
    }
    STORAGE.save_feedback(feedback_record)
    return {
        "id": feedback_id,
        "generation_id": req.generation_id,
        "rating": req.rating.lower(),
        "suggested_tier": suggested_tier,
        "suggestion_reason": suggestion_reason,
        "escalation_policy": "manual_only",
        "escalation_note": "A higher tier is suggested to improve quality, but will not be escalated automatically.",
    }


@app.get("/feedback")
@app.get("/api/feedback")
def list_user_feedback(generation_id: Optional[str] = None):
    """Retrieve recorded user feedback."""
    if generation_id:
        fb = STORAGE.get_feedback(generation_id)
        return [fb] if fb else []
    return STORAGE.list_feedback()


@app.get("/replay")
@app.get("/api/replay")
def get_replay_items(purpose: Optional[str] = None, tier: Optional[str] = None):
    """Get replay snapshot entries for offline demonstration safety net."""
    rc = ReplayCache()
    if purpose or tier:
        entry = rc.get_replay(purpose, tier)
        return [entry] if entry else []
    return rc.list_replays()


@app.get("/benchmark")
@app.get("/api/benchmark")
def get_benchmark_results():
    """Retrieve the latest multi-prompt benchmark summary and results."""
    import json
    summary_path = Path("reports/benchmark_summary.json")
    if not summary_path.exists():
        runner = BenchmarkRunner()
        results = runner.run_all()
        runner.save_reports(results)
        return results
    with open(summary_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/benchmark/run")
@app.post("/api/benchmark/run")
def run_benchmark_endpoint():
    """Execute reproducible multi-prompt benchmark across all policies."""
    runner = BenchmarkRunner()
    results = runner.run_all()
    runner.save_reports(results)
    return results


@app.get("/reports/{filename}")
@app.get("/api/reports/{filename}")
def download_benchmark_report(filename: str):
    """Download generated benchmark reports (json, csv, md)."""
    p = Path("reports") / filename
    if not p.exists():
        raise HTTPException(status_code=404, detail="Report file not found")
    media_type = "application/json" if filename.endswith(".json") else "text/csv" if filename.endswith(".csv") else "text/markdown"
    return FileResponse(p, media_type=media_type, filename=filename)


@app.get("/api/history")
def get_request_history(
    school_id: Optional[str] = None,
    purpose: Optional[str] = None,
    tier: Optional[str] = None,
    status: Optional[str] = None,
    domain: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    role: str = Query(default="requester"),
):
    """Retrieve history of past requests or resource generations."""
    if domain == "image_resource_optimizer" or purpose or tier:
        return STORAGE.list_generations(purpose=purpose, tier=tier, status=status, limit=limit)
    gen_list = STORAGE.list_generations(limit=limit)
    if gen_list and not school_id:
        return gen_list
    records = STORAGE.list_requests(school_id=school_id, limit=limit)
    return [serialize_record(r, role) for r in records]


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
    if (frontend_dir / "fonts").exists():
        app.mount("/fonts", StaticFiles(directory=str(frontend_dir / "fonts")), name="fonts")

    @app.get("/")
    def serve_index():
        return FileResponse(str(frontend_dir / "index.html"))
