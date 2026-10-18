"""Scheduled Cron Auditor background watchdog traversing repositories for compute waste."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hermes_midas.ast_analyzer import ASTAnalyzer
from hermes_midas.finops import WorkloadEvaluator
from hermes_midas.orchestrator.deduplication import (
    compute_deterministic_fingerprint,
    generate_branch_name,
)
from hermes_midas.topology import MockCostExplorerClient


class AuditWorkloadResult(BaseModel):
    """Audit result for a single scanned workload file."""

    file_path: str
    engine: str
    anti_patterns_count: int
    monthly_savings_usd: float
    waste_reduction_pct: float
    pr_action: str
    pr_branch: str | None = None


class AuditRunReport(BaseModel):
    """Aggregate summary report from an audit sweep."""

    scanned_workloads_count: int
    offending_workloads_count: int
    total_potential_monthly_savings: float
    total_potential_annual_savings: float
    prs_created: int
    prs_skipped: int
    workloads: list[AuditWorkloadResult] = Field(default_factory=list)


class ScheduledCronAuditor:
    """Proactive background FinOps watchdog traversing repositories for compute waste."""

    def __init__(self, min_savings_threshold: float = 20.00) -> None:
        self.min_savings_threshold = min_savings_threshold
        self.analyzer = ASTAnalyzer()
        self.evaluator = WorkloadEvaluator()
        self.ce_client = MockCostExplorerClient()
        self._open_prs: dict[str, str] = {}  # file_path -> fingerprint

    def scan_repository(self, repo_dir: Path | str) -> AuditRunReport:
        """Scan repository directory for PySpark compute waste and anti-patterns."""
        repo_path = Path(repo_dir)
        py_files = list(repo_path.rglob("*.py"))
        scanned_count = 0
        offending_count = 0
        total_monthly_savings = 0.0
        prs_created = 0
        prs_skipped = 0
        workload_results: list[AuditWorkloadResult] = []

        for f in py_files:
            # Skip test files or caches
            if f.name.startswith("test_") or "__pycache__" in str(f):
                continue

            try:
                content = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Quick check if PySpark script
            if "spark" not in content.lower() and "pyspark" not in content.lower():
                continue

            scanned_count += 1
            inspection = self.analyzer.inspect(content, str(f))

            if inspection.anti_patterns_count == 0:
                continue

            # Determine engine
            engine = "glue"
            if "emr" in str(f).lower():
                engine = "emr_serverless"
            elif "databricks" in str(f).lower():
                engine = "databricks"

            # Compute FinOps ROI
            try:
                roi = self.evaluator.evaluate_workload(str(f))
                monthly_savings = float(roi.monthly_savings_usd)
                waste_pct = float(roi.waste_reduction_pct)
            except (ValueError, KeyError, OSError, RuntimeError):
                monthly_savings = 100.0
                waste_pct = 50.0

            # Threshold check
            if monthly_savings < self.min_savings_threshold:
                continue

            offending_count += 1
            total_monthly_savings += monthly_savings

            # Deduplication
            pattern_ids = [m.pattern_id for m in inspection.anti_patterns]
            fp = compute_deterministic_fingerprint(str(f), engine, pattern_ids)
            branch = generate_branch_name(str(f), fp)

            if str(f) in self._open_prs and self._open_prs[str(f)] == fp:
                pr_action = "SKIPPED_DEDUPLICATED"
                prs_skipped += 1
            else:
                pr_action = "CREATED"
                self._open_prs[str(f)] = fp
                prs_created += 1

            workload_results.append(
                AuditWorkloadResult(
                    file_path=str(f),
                    engine=engine,
                    anti_patterns_count=inspection.anti_patterns_count,
                    monthly_savings_usd=monthly_savings,
                    waste_reduction_pct=waste_pct,
                    pr_action=pr_action,
                    pr_branch=branch,
                )
            )

        return AuditRunReport(
            scanned_workloads_count=scanned_count,
            offending_workloads_count=offending_count,
            total_potential_monthly_savings=round(total_monthly_savings, 2),
            total_potential_annual_savings=round(total_monthly_savings * 12.0, 2),
            prs_created=prs_created,
            prs_skipped=prs_skipped,
            workloads=workload_results,
        )

    def start_scheduler(
        self,
        repo_dir: Path | str,
        cron_expr: str = "0 2 * * *",
        callback: Callable[[AuditRunReport], None] | None = None,
    ) -> Any:
        """Start background cron scheduler using APScheduler."""
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler()
        trigger = CronTrigger.from_crontab(cron_expr)

        def job():
            report = self.scan_repository(repo_dir)
            if callback:
                callback(report)

        scheduler.add_job(job, trigger)
        scheduler.start()
        return scheduler
