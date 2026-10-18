"""End-to-end test suite for Airflow Webhook Trigger endpoint (/api/v1/triggers/airflow).

Tiers Covered:
- Tier 3: Cross-Feature HMAC Signature Verification & Auth Rejection
- Tier 4: Real-World Webhook Inbound Dispatch -> AST Analysis -> FinOps ROI -> PR Creation
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from hermes_midas.orchestrator.webhook import (
    create_airflow_trigger_app,
)

# ============================================================================
# Tier 3: HMAC Signature Tests
# ============================================================================


@pytest.mark.tier3
@pytest.mark.asyncio
async def test_airflow_trigger_rejects_missing_or_bad_signature():
    """Tier 3: Webhook rejects requests with missing or tampered HMAC signature with 401."""
    app = create_airflow_trigger_app()
    payload = {
        "dag_id": "test_dag",
        "task_id": "test_task",
        "run_id": "run_1",
        "execution_date": "2026-10-15T12:00:00Z",
        "engine": "glue",
        "script_path": "workloads/glue/customer360_elt.py",
    }
    body = json.dumps(payload).encode()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Missing signature -> 401
        res = await client.post("/api/v1/triggers/airflow", content=body)
        assert res.status_code == 401

        # 2. Invalid signature -> 401
        bad_headers = {"X-Airflow-Signature": "sha256=invalid_hex_string"}
        res2 = await client.post("/api/v1/triggers/airflow", content=body, headers=bad_headers)
        assert res2.status_code == 401

        # 3. Bypass header -> 200
        bypass_headers = {"X-Midas-Bypass-Auth": "1"}
        res3 = await client.post("/api/v1/triggers/airflow", content=body, headers=bypass_headers)
        assert res3.status_code == 200


# ============================================================================
# Tier 4: Real-World Webhook Inbound Dispatch E2E
# ============================================================================


@pytest.mark.tier4
@pytest.mark.asyncio
async def test_airflow_trigger_e2e_synchronous_flow():
    """Tier 4: Airflow webhook executes full synchronous analysis and PR dispatch."""
    app = create_airflow_trigger_app()
    secret = "test-secret"
    payload = {
        "dag_id": "customer_orders_elt",
        "task_id": "pyspark_step",
        "run_id": "run_20261015",
        "execution_date": "2026-10-15T12:00:00Z",
        "engine": "glue",
        "script_path": "workloads/glue/customer360_elt.py",
        "async_mode": False,
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # First call -> PR CREATED
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=body,
            headers={"X-Airflow-Signature": sig},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUCCESS"
        assert data["pr_action"] == "CREATED"
        assert data["estimated_monthly_savings"] == 11246.40
        assert data["anti_patterns_count"] >= 2
        assert data["branch_name"].startswith("midas/finops-")
        assert "glue" in data["branch_name"]

        # Second identical call -> PR SKIPPED_DEDUPLICATED
        res2 = await client.post(
            "/api/v1/triggers/airflow",
            content=body,
            headers={"X-Airflow-Signature": sig},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["pr_action"] == "SKIPPED_DEDUPLICATED"


@pytest.mark.tier4
@pytest.mark.asyncio
async def test_airflow_trigger_e2e_asynchronous_flow():
    """Tier 4: Airflow webhook with async_mode=True returns 202 and completes background task."""
    app = create_airflow_trigger_app()
    secret = "test-secret"
    payload = {
        "dag_id": "emr_attribution_dag",
        "task_id": "spark_submit",
        "run_id": "async_run_1",
        "execution_date": "2026-10-15T12:00:00Z",
        "engine": "emr_serverless",
        "script_path": "workloads/emr/clickstream_attribution.py",
        "async_mode": True,
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=body,
            headers={"X-Airflow-Signature": sig},
        )
        assert res.status_code == 202
        data = res.json()
        assert data["status"] == "ACCEPTED"
        data["job_id"]
        status_url = data["status_url"]

        # Poll status
        await asyncio.sleep(0.05)
        task_res = await client.get(status_url)
        assert task_res.status_code == 200
        task_data = task_res.json()
        assert task_data["status"] == "SUCCESS"
        assert task_data["result"]["pr_action"] == "CREATED"
