"""End-to-end test suite for Scheduled Cron Auditor background watchdog.

Tiers Covered:
- Tier 3: Workload Discovery, Telemetry Correlation & Savings Threshold Filter
- Tier 4: Background Sweep, Deduplicated Local PR Artifact Generation & Audit Summary Emission
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_midas.orchestrator.cron_auditor import (
    ScheduledCronAuditor,
)

# ============================================================================
# Tier 3 & Tier 4: Cron Auditor Tests
# ============================================================================

@pytest.mark.tier3
def test_cron_auditor_savings_threshold_filtering(tmp_path: Path):
    """Tier 3: Workloads with savings below minimum threshold ($20/mo) are suppressed."""
    repo_dir = tmp_path / "low_savings_repo"
    repo_dir.mkdir()
    clean_file = repo_dir / "clean_job.py"
    clean_file.write_text("from pyspark.sql import SparkSession\nspark = SparkSession.builder.getOrCreate()\n")

    auditor = ScheduledCronAuditor(min_savings_threshold=20.00)
    report = auditor.scan_repository(repo_dir)

    assert report.scanned_workloads_count == 1
    assert report.offending_workloads_count == 0
    assert report.prs_created == 0


@pytest.mark.tier4
def test_cron_auditor_full_repository_sweep_and_deduplication():
    """Tier 4: Background sweep discovers seed workloads, opens PRs, and deduplicates next run."""
    workloads_dir = Path("workloads")
    auditor = ScheduledCronAuditor(min_savings_threshold=20.00)

    # First audit sweep
    report1 = auditor.scan_repository(workloads_dir)

    assert report1.scanned_workloads_count >= 3
    assert report1.offending_workloads_count >= 2
    assert report1.prs_created >= 2
    assert report1.prs_skipped == 0
    assert report1.total_potential_monthly_savings > 10000.0

    # Second immediate audit sweep -> all candidates deduplicated
    report2 = auditor.scan_repository(workloads_dir)

    assert report2.prs_created == 0
    assert report2.prs_skipped == report1.prs_created
