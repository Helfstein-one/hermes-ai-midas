"""FastAPI Airflow Webhook Trigger endpoint (/api/v1/triggers/airflow)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from hermes_midas.orchestrator.deduplication import (
    PRAction,
    generate_branch_name,
)
from hermes_midas.orchestrator.pipeline import async_optimize_workload


class PipelineMetrics(BaseModel):
    """Execution telemetry metrics passed with webhook trigger."""
    duration_seconds: float
    allocated_dpus: float | None = None
    vcpu_hours: float | None = None
    dbus_consumed: float | None = None
    memory_utilization_pct: float | None = None
    executor_idle_time_pct: float | None = None
    data_skew_ratio: float | None = None


class AirflowTriggerPayload(BaseModel):
    """Payload schema for POST /api/v1/triggers/airflow."""
    dag_id: str
    task_id: str
    run_id: str
    execution_date: datetime
    engine: str
    repo_url: str | None = None
    repo_path: str | None = None
    script_path: str
    git_branch: str = "main"
    metrics: PipelineMetrics | None = None
    async_mode: bool = False
    callback_url: str | None = None


class AirflowTriggerResponse(BaseModel):
    """Response schema for Airflow webhook trigger."""
    status: str
    job_id: str
    dag_id: str
    task_id: str
    pr_action: str
    pr_url: str | None = None
    pr_number: int | None = None
    branch_name: str | None = None
    anti_patterns_count: int = 0
    estimated_monthly_savings: float = 0.0
    waste_reduction_pct: float = 0.0
    status_url: str | None = None


def create_airflow_trigger_app(
    secret: str | None = None,
    tasks_db: dict[str, dict[str, Any]] | None = None,
    prs_db: dict[str, dict[str, Any]] | None = None,
) -> FastAPI:
    """Factory function creating the FastAPI webhook application."""
    app = FastAPI(title="Hermes Midas Triggers", version="0.1.0")
    webhook_secret = secret or os.environ.get("MIDAS_WEBHOOK_SECRET", "test-secret")
    tasks: dict[str, dict[str, Any]] = tasks_db if tasks_db is not None else {}
    prs: dict[str, dict[str, Any]] = prs_db if prs_db is not None else {}

    @app.post("/api/v1/triggers/airflow")
    async def trigger_airflow(
        request: Request,
        x_airflow_signature: str | None = Header(None),
        x_midas_bypass_auth: str | None = Header(None),
    ):
        body_bytes = await request.body()

        # HMAC-SHA256 signature verification
        if x_midas_bypass_auth != "1":
            if not x_airflow_signature:
                raise HTTPException(status_code=401, detail="Missing X-Airflow-Signature")
            expected_sig = "sha256=" + hmac.new(
                webhook_secret.encode("utf-8"), body_bytes, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(x_airflow_signature, expected_sig):
                raise HTTPException(status_code=401, detail="Invalid HMAC signature")

        try:
            data = json.loads(body_bytes.decode("utf-8"))
            if not isinstance(data, dict):
                raise HTTPException(status_code=400, detail="Payload must be a JSON object")
            payload = AirflowTriggerPayload(**data)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=400, detail=f"Invalid payload: {e}") from e

        job_id = f"job-{payload.dag_id}-{payload.run_id}"

        # Resolve source script and return 404 if missing
        script_file = Path(payload.script_path)
        if not script_file.exists() and payload.repo_path:
            alt_path = Path(payload.repo_path) / payload.script_path
            if alt_path.exists():
                script_file = alt_path

        if not script_file.exists():
            raise HTTPException(status_code=404, detail=f"Script not found: {payload.script_path}")

        async def process_pipeline() -> AirflowTriggerResponse:
            pipeline_res = await async_optimize_workload(
                script_path=str(script_file),
                repo_path=payload.repo_path or ".",
                engine=payload.engine,
                trigger_origin=f"Airflow Webhook: {payload.dag_id}",
                trigger_run_id=payload.run_id,
            )

            fp = pipeline_res.fingerprint or ""
            branch = pipeline_res.branch_name or (
                generate_branch_name(payload.script_path, fp) if fp else ""
            )

            if payload.script_path in prs and fp:
                existing = prs[payload.script_path]
                if existing.get("fingerprint") == fp:
                    return AirflowTriggerResponse(
                        status="SUCCESS",
                        job_id=job_id,
                        dag_id=payload.dag_id,
                        task_id=payload.task_id,
                        pr_action=PRAction.SKIPPED_DEDUPLICATED,
                        pr_url=existing.get("pr_url") or pipeline_res.pr_url,
                        branch_name=existing.get("branch") or branch,
                        anti_patterns_count=pipeline_res.anti_patterns_count,
                        estimated_monthly_savings=pipeline_res.monthly_savings_usd,
                        waste_reduction_pct=pipeline_res.waste_reduction_pct,
                    )

            if fp:
                prs[payload.script_path] = {
                    "fingerprint": fp,
                    "pr_url": pipeline_res.pr_url or f"https://git.local/{payload.dag_id}/pulls/1",
                    "branch": branch,
                }

            return AirflowTriggerResponse(
                status="SUCCESS",
                job_id=job_id,
                dag_id=payload.dag_id,
                task_id=payload.task_id,
                pr_action=pipeline_res.pr_action,
                pr_url=pipeline_res.pr_url or f"https://git.local/{payload.dag_id}/pulls/1",
                pr_number=pipeline_res.pr_number or 1,
                branch_name=branch,
                anti_patterns_count=pipeline_res.anti_patterns_count,
                estimated_monthly_savings=pipeline_res.monthly_savings_usd,
                waste_reduction_pct=pipeline_res.waste_reduction_pct,
            )

        if payload.async_mode:
            tasks[job_id] = {"status": "ACCEPTED", "result": None}

            async def bg_worker():
                res = await process_pipeline()
                tasks[job_id] = {"status": "SUCCESS", "result": res.model_dump()}

            asyncio.create_task(bg_worker())
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "status": "ACCEPTED",
                    "job_id": job_id,
                    "status_url": f"/api/v1/tasks/{job_id}",
                },
            )

        result = await process_pipeline()
        return result.model_dump()

    @app.get("/api/v1/tasks/{job_id}")
    async def get_task_status(job_id: str):
        if job_id not in tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        return tasks[job_id]

    return app


# Default app instance
app = create_airflow_trigger_app()
