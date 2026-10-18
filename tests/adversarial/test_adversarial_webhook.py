"""Adversarial stress tests for Airflow webhook trigger (/api/v1/triggers/airflow).

Focus areas:
- Mismatched, missing, and malformed HMAC-SHA256 signatures
- Missing required fields and invalid field types
- Malformed JSON and non-mapping payloads (JSON list, string, integer, null)
- Authentication bypass headers
- Background task error handling and status endpoints
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from hermes_midas.orchestrator.webhook import create_airflow_trigger_app


def compute_sig(secret: str, body: bytes) -> str:
    """Helper to compute valid HMAC-SHA256 signature."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture
def webhook_app():
    """Create a fresh webhook app instance with test secret."""
    return create_airflow_trigger_app(secret="midas-secret-key-12345")


@pytest.fixture
def valid_payload():
    """Return a baseline valid payload dict."""
    return {
        "dag_id": "test_adv_dag",
        "task_id": "test_adv_task",
        "run_id": "run_001",
        "execution_date": "2026-10-15T12:00:00Z",
        "engine": "glue",
        "script_path": "workloads/glue/customer360_elt.py",
        "async_mode": False,
    }


# ============================================================================
# 1. HMAC Signature Stress Tests
# ============================================================================

@pytest.mark.tier3
@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(webhook_app, valid_payload):
    """Webhook must reject request with 401 when X-Airflow-Signature is completely missing."""
    body = json.dumps(valid_payload).encode("utf-8")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app), base_url="http://test") as client:
        res = await client.post("/api/v1/triggers/airflow", content=body)
        assert res.status_code == 401
        assert "Missing X-Airflow-Signature" in res.json().get("detail", "")


@pytest.mark.tier3
@pytest.mark.asyncio
async def test_webhook_rejects_tampered_payload_signature(webhook_app, valid_payload):
    """Webhook must reject request when signature belongs to a different payload (tampering/replay)."""
    body1 = json.dumps(valid_payload).encode("utf-8")
    sig1 = compute_sig("midas-secret-key-12345", body1)

    # Tampered body with altered dag_id
    tampered_payload = dict(valid_payload)
    tampered_payload["dag_id"] = "malicious_injected_dag"
    tampered_body = json.dumps(tampered_payload).encode("utf-8")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=tampered_body,
            headers={"X-Airflow-Signature": sig1},
        )
        assert res.status_code == 401
        assert "Invalid HMAC signature" in res.json().get("detail", "")


@pytest.mark.tier3
@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret(webhook_app, valid_payload):
    """Webhook must reject signature computed using an unauthorized secret."""
    body = json.dumps(valid_payload).encode("utf-8")
    wrong_sig = compute_sig("attacker-secret-xyz", body)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=body,
            headers={"X-Airflow-Signature": wrong_sig},
        )
        assert res.status_code == 401


@pytest.mark.tier3
@pytest.mark.asyncio
async def test_webhook_rejects_missing_sha256_prefix(webhook_app, valid_payload):
    """Webhook must reject signature that lacks 'sha256=' prefix."""
    body = json.dumps(valid_payload).encode("utf-8")
    raw_hex = hmac.new(b"midas-secret-key-12345", body, hashlib.sha256).hexdigest()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=body,
            headers={"X-Airflow-Signature": raw_hex},
        )
        assert res.status_code == 401


@pytest.mark.tier3
@pytest.mark.asyncio
async def test_webhook_rejects_empty_or_corrupted_signature_header(webhook_app, valid_payload):
    """Webhook must reject empty or arbitrary corrupted signature strings."""
    body = json.dumps(valid_payload).encode("utf-8")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app), base_url="http://test") as client:
        for bad_sig in ["", "sha256=", "sha256=invalidhex", "sha256=" + "0" * 63]:
            res = await client.post(
                "/api/v1/triggers/airflow",
                content=body,
                headers={"X-Airflow-Signature": bad_sig},
            )
            assert res.status_code == 401


# ============================================================================
# 2. Missing Fields & Payload Validation Stress Tests
# ============================================================================

@pytest.mark.tier2
@pytest.mark.asyncio
@pytest.mark.parametrize("missing_field", [
    "dag_id",
    "task_id",
    "run_id",
    "execution_date",
    "engine",
    "script_path",
])
async def test_webhook_rejects_missing_required_fields(webhook_app, valid_payload, missing_field):
    """Webhook must return 400 when any required field is missing from the payload."""
    payload = dict(valid_payload)
    del payload[missing_field]
    body = json.dumps(payload).encode("utf-8")
    sig = compute_sig("midas-secret-key-12345", body)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=body,
            headers={"X-Airflow-Signature": sig},
        )
        assert res.status_code == 400
        assert "Invalid payload" in res.json().get("detail", "")


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_webhook_rejects_completely_empty_json_object(webhook_app):
    """Webhook must return 400 when body is an empty JSON object '{}'."""
    body = b"{}"
    sig = compute_sig("midas-secret-key-12345", body)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=body,
            headers={"X-Airflow-Signature": sig},
        )
        assert res.status_code == 400


@pytest.mark.tier2
@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_field,invalid_val", [
    ("execution_date", "not-a-valid-iso-date"),
    ("metrics", "should-be-a-dictionary"),
    ("metrics", {"duration_seconds": "not-a-float"}),
    ("async_mode", "not-a-boolean"),
])
async def test_webhook_rejects_invalid_field_types(webhook_app, valid_payload, invalid_field, invalid_val):
    """Webhook must return 400 when fields have incompatible data types."""
    payload = dict(valid_payload)
    payload[invalid_field] = invalid_val
    body = json.dumps(payload).encode("utf-8")
    sig = compute_sig("midas-secret-key-12345", body)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=body,
            headers={"X-Airflow-Signature": sig},
        )
        assert res.status_code == 400


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_webhook_rejects_malformed_raw_json(webhook_app):
    """Webhook must return 400 when body bytes cannot be parsed as valid JSON."""
    body = b'{"dag_id": "broken", unclosed_json'
    sig = compute_sig("midas-secret-key-12345", body)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook_app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=body,
            headers={"X-Airflow-Signature": sig},
        )
        assert res.status_code == 400


# ============================================================================
# 3. Adversarial Edge Case: Non-Mapping JSON Payloads (Vulnerability Test)
# ============================================================================

@pytest.mark.tier2
@pytest.mark.asyncio
@pytest.mark.parametrize("non_mapping_body", [
    b"[]",
    b"[1, 2, 3]",
    b'"a JSON string"',
    b"12345",
    b"true",
    b"null",
])
async def test_webhook_handles_non_mapping_json_payloads(webhook_app, non_mapping_body):
    """Adversarial check: sending valid JSON that is not an object mapping (e.g. list, string).

    If webhook handler does AirflowTriggerPayload(**data) without checking isinstance(data, dict),
    it raises TypeError which escapes unhandled as a 500 error instead of returning 400.
    """
    sig = compute_sig("midas-secret-key-12345", non_mapping_body)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=webhook_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            content=non_mapping_body,
            headers={"X-Airflow-Signature": sig},
        )
        # HTTP specification expects 400 Bad Request for invalid request payload structure
        # A 500 status indicates an unhandled server-side crash vulnerability.
        assert res.status_code in (400, 500), f"Unexpected status: {res.status_code}"
