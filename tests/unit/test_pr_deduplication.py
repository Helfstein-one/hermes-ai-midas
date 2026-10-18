"""Unit and boundary tests for PR deduplication engine and deterministic fingerprinting.

Tiers Covered:
- Tier 1: Feature Coverage (Fingerprint generation, deduplication status evaluation)
- Tier 2: Boundary & Corner Cases (Sorting anti-patterns, collision resistance, slugification)
- Tier 3: Cross-Feature State Management (CREATED -> SKIPPED_DEDUPLICATED -> UPDATED)
"""

from __future__ import annotations

import pytest

from hermes_midas.orchestrator.deduplication import (
    MockPR,
    PRAction,
    PRDeduplicationEngine,
    compute_deterministic_fingerprint,
    generate_branch_name,
)

# ============================================================================
# Tier 1: Feature Unit Tests
# ============================================================================

@pytest.mark.tier1
def test_deterministic_fingerprint_generation():
    """Tier 1: Verify SHA256 deterministic 16-character hexadecimal fingerprint."""
    fp = compute_deterministic_fingerprint(
        script_path="jobs/customer360_elt.py",
        engine="glue",
        anti_pattern_ids=["ORPHAN_ACTION", "LEGACY_UDF"],
    )
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


@pytest.mark.tier1
def test_deduplication_first_run_creates_pr():
    """Tier 1: When no PR exists, engine returns CREATED action."""
    engine = PRDeduplicationEngine(existing_prs=[])
    action, pr, fp = engine.evaluate(
        script_path="jobs/customer360_elt.py",
        engine="glue",
        anti_pattern_ids=["ORPHAN_ACTION"],
    )
    assert action == PRAction.CREATED
    assert pr is None
    assert len(fp) == 16


@pytest.mark.tier1
def test_deduplication_second_run_skips_pr():
    """Tier 1: When an open PR with matching fingerprint exists, engine returns SKIPPED_DEDUPLICATED."""
    script_path = "jobs/customer360_elt.py"
    engine_name = "glue"
    patterns = ["ORPHAN_ACTION", "LEGACY_UDF"]
    fp = compute_deterministic_fingerprint(script_path, engine_name, patterns)

    existing_pr = MockPR(
        id=101,
        title="[Midas FinOps] Optimize Workload: customer360_elt",
        body="PR Body",
        head_branch=generate_branch_name(script_path, fp),
        is_open=True,
        metadata={"fingerprint": fp, "script_path": script_path, "engine": engine_name},
    )

    engine = PRDeduplicationEngine(existing_prs=[existing_pr])
    action, matched_pr, calculated_fp = engine.evaluate(script_path, engine_name, patterns)

    assert action == PRAction.SKIPPED_DEDUPLICATED
    assert matched_pr is not None
    assert matched_pr.id == 101
    assert calculated_fp == fp


@pytest.mark.tier1
def test_deduplication_changed_patterns_updates_pr():
    """Tier 1: When script matches an open PR but anti-patterns changed, engine returns UPDATED."""
    script_path = "jobs/customer360_elt.py"
    engine_name = "glue"
    old_fp = compute_deterministic_fingerprint(script_path, engine_name, ["ORPHAN_ACTION"])

    existing_pr = MockPR(
        id=102,
        title="[Midas FinOps] Optimize Workload: customer360_elt",
        body="PR Body",
        head_branch=generate_branch_name(script_path, old_fp),
        is_open=True,
        metadata={"fingerprint": old_fp, "script_path": script_path, "engine": engine_name},
    )

    engine = PRDeduplicationEngine(existing_prs=[existing_pr])
    # New run discovered an additional pattern: UNBROADCASTED_JOIN
    new_patterns = ["ORPHAN_ACTION", "UNBROADCASTED_JOIN"]
    action, matched_pr, new_fp = engine.evaluate(script_path, engine_name, new_patterns)

    assert action == PRAction.UPDATED
    assert matched_pr is not None
    assert matched_pr.id == 102
    assert new_fp != old_fp


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================

@pytest.mark.tier2
def test_fingerprint_invariant_to_anti_pattern_order():
    """Tier 2: Fingerprint calculation must be strictly order-independent."""
    fp1 = compute_deterministic_fingerprint(
        "jobs/etl.py", "glue", ["ORPHAN_ACTION", "UNBROADCASTED_JOIN", "LEGACY_UDF"]
    )
    fp2 = compute_deterministic_fingerprint(
        "jobs/etl.py", "glue", ["LEGACY_UDF", "ORPHAN_ACTION", "UNBROADCASTED_JOIN"]
    )
    assert fp1 == fp2


@pytest.mark.tier2
def test_fingerprint_collision_resistance_on_different_scripts():
    """Tier 2: Different script paths produce distinct fingerprints."""
    fp_a = compute_deterministic_fingerprint("jobs/etl_a.py", "glue", ["ORPHAN_ACTION"])
    fp_b = compute_deterministic_fingerprint("jobs/etl_b.py", "glue", ["ORPHAN_ACTION"])
    assert fp_a != fp_b


@pytest.mark.tier2
def test_no_issues_skips_pr_creation():
    """Tier 2: When 0 anti-patterns are found, engine returns SKIPPED_NO_ISSUES."""
    engine = PRDeduplicationEngine(existing_prs=[])
    action, pr, fp = engine.evaluate("jobs/clean.py", "glue", [])
    assert action == PRAction.SKIPPED_NO_ISSUES
    assert pr is None
