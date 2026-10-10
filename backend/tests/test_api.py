"""
Tests for FastAPI application endpoints.
"""
from fastapi.testclient import TestClient
import pytest
from backend.api.main import app

client = TestClient(app)

def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["active_domain"] == "education_images"

def test_api_config():
    res = client.get("/api/config?role=admin")
    assert res.status_code == 200
    data = res.json()
    assert "strategies" in data
    assert "task_categories" in data

def test_api_categories():
    res = client.get("/api/categories")
    assert res.status_code == 200
    data = res.json()
    assert "colouring_worksheet" in data
    assert "flashcard" in data

def test_api_preview():
    res = client.post("/api/preview", json={
        "prompt": "Farm animals for grade 2",
        "purpose": "colouring_worksheet",
        "inputs": {"subject": "farm animals", "output_size": "A4"},
        "school_id": "SCHOOL-101",
        "role": "requester"
    })
    assert res.status_code == 200
    data = res.json()
    assert "recommended" in data
    assert "strategy_name" in data["recommended"]
    assert "preview_image" in data["recommended"]

def test_api_request_execution():
    res = client.post("/api/request", json={
        "prompt": "Farm animals for grade 2",
        "purpose": "colouring_worksheet",
        "inputs": {"subject": "farm animals", "output_size": "A4"},
        "school_id": "SCHOOL-101",
        "role": "requester",
        "auto_execute": True
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert data["preview_image_url"] is not None
    assert "quality" in data
    assert data["quality"]["passed"] is True

    # Test rating
    req_id = data["request"]["id"]
    rate_res = client.post("/api/rating", json={"request_id": req_id, "rating": 5})
    assert rate_res.status_code == 200
    assert rate_res.json()["success"] is True

def test_api_moderation_blocked():
    res = client.post("/api/request", json={
        "prompt": "student: Alice phone 555-0199 personal data",
        "purpose": "colouring_worksheet",
        "inputs": {},
        "school_id": "SCHOOL-101",
        "role": "requester"
    })
    assert res.status_code == 400
    assert "moderation_blocked" in res.json().get("error", "")

def test_api_showback():
    res = client.get("/api/showback")
    assert res.status_code == 200
    data = res.json()
    assert "schools" in data

def test_api_eval():
    res = client.post("/api/eval?sample_size=10&seed=42")
    assert res.status_code == 200
    data = res.json()
    assert "baseline_cost" in data
    assert "optimized_cost" in data
    assert "attribution" in data
    assert "total_savings" in data["attribution"]

def test_api_history():
    res = client.get("/api/history?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)

def test_api_config_rollback():
    # 1. Update config
    up_res = client.put("/api/config", json={
        "updates": {"policy": {"approval_required_above_cost": 0.25}},
        "author": "tester"
    })
    assert up_res.status_code == 200
    new_version = up_res.json()["version"]

    # 2. Check versions list
    ver_res = client.get("/api/config/versions")
    assert ver_res.status_code == 200
    assert len(ver_res.json()) >= 1

    # 3. Rollback
    rb_res = client.post("/api/config/rollback", json={"author": "admin"})
    assert rb_res.status_code == 200
    assert rb_res.json()["success"] is True
    assert rb_res.json()["version"] > new_version

