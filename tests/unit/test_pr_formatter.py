"""Unit and boundary tests for the Midas Touch PR Formatter.

Tiers Covered:
- Tier 1: Feature Coverage (Midas Touch markdown generation, FinOps table, Diff block, Hidden JSON metadata)
- Tier 2: Boundary & Corner Cases (Metadata extraction, Special characters in script names, Zero savings formatting)
"""

from __future__ import annotations

import pytest

from hermes_midas.orchestrator.pr_formatter import MidasTouchFormatter

# ============================================================================
# Tier 1: Feature Unit Tests
# ============================================================================

@pytest.mark.tier1
def test_midas_touch_formatter_contains_required_sections():
    """Tier 1: Verify PR markdown contains all required headings, ROI, diff, and checklist."""
    formatter = MidasTouchFormatter()
    pr_body = formatter.format_pr(
        workload_name="customer360_elt",
        script_path="jobs/customer360_elt.py",
        engine="glue",
        fingerprint="a1b2c3d4e5f67890",
        monthly_savings=11246.40,
        annual_savings=134956.80,
        waste_reduction_pct=94.7,
        anti_patterns=[
            {
                "pattern_id": "ORPHAN_ACTION",
                "pattern_name": "Orphan Action Invocations",
                "description": "df.count() executed in bare expression",
                "remediation_strategy": "Removed redundant action.",
            }
        ],
        diff="--- a/jobs/orders.py\n+++ b/jobs/orders.py\n@@ -1 +1 @@\n-df.count()\n",
    )

    assert "# 🏆 [Midas FinOps] Optimize Workload: `customer360_elt`" in pr_body
    assert "$11,246.40 / month" in pr_body
    assert "94.7%" in pr_body
    assert "### 📋 Executive Summary" in pr_body
    assert "### 💰 FinOps Impact & Deterministic ROI" in pr_body
    assert "### 🔍 Detected Anti-Patterns & Waste Mechanisms" in pr_body
    assert "```diff" in pr_body
    assert "### 🛡️ Safety & AST Verification Checklist" in pr_body
    assert "<!-- midas-metadata:" in pr_body


@pytest.mark.tier1
def test_midas_touch_metadata_extraction():
    """Tier 1: Verify hidden automation metadata is accurately extracted from PR body."""
    formatter = MidasTouchFormatter()
    pr_body = formatter.format_pr(
        workload_name="clickstream_attribution",
        script_path="jobs/clickstream.py",
        engine="emr_serverless",
        fingerprint="fedcba9876543210",
        monthly_savings=303.64,
        annual_savings=3643.68,
        waste_reduction_pct=95.8,
        anti_patterns=[{"pattern_id": "UNBROADCASTED_JOIN"}],
        diff="--- a/clickstream.py\n+++ b/clickstream.py\n",
    )

    metadata = formatter.extract_metadata(pr_body)
    assert metadata is not None
    assert metadata["fingerprint"] == "fedcba9876543210"
    assert metadata["engine"] == "emr_serverless"
    assert metadata["monthly_savings"] == 303.64
    assert "UNBROADCASTED_JOIN" in metadata["anti_patterns"]


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================

@pytest.mark.tier2
def test_formatter_handles_empty_diff_and_no_patterns():
    """Tier 2: Formatter renders cleanly even with empty anti-patterns or diff."""
    formatter = MidasTouchFormatter()
    pr_body = formatter.format_pr(
        workload_name="test_workload",
        script_path="jobs/test.py",
        engine="databricks",
        fingerprint="0000000000000000",
        monthly_savings=0.0,
        annual_savings=0.0,
        waste_reduction_pct=0.0,
        anti_patterns=[],
        diff="",
    )
    assert "test_workload" in pr_body
    assert "$0.00 / month" in pr_body
    metadata = formatter.extract_metadata(pr_body)
    assert metadata is not None
    assert metadata["anti_patterns"] == []


@pytest.mark.tier2
def test_extract_metadata_returns_none_when_tag_missing():
    """Tier 2: Extracting metadata from arbitrary markdown returns None."""
    formatter = MidasTouchFormatter()
    assert formatter.extract_metadata("Just a regular PR text without metadata tag") is None
