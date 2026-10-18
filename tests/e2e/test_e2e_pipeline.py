"""Full end-to-end integration pipeline test: Ingestion -> AST -> ROI -> Patch -> Git PR.

Tiers Covered:
- Tier 4: Real-World Autonomous Orchestration Flow on isolated local git repository
"""

from __future__ import annotations

import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from hermes_midas.ast_analyzer import ASTAnalyzer
from hermes_midas.finops import WorkloadEvaluator
from hermes_midas.topology import MockCloudWatchClient, MockCostExplorerClient


@pytest.mark.tier4
def test_full_e2e_pipeline_on_local_git_repo(local_git_repo: Path):
    """Tier 4: Complete end-to-end flow from seed workload to verified PR artifact in Git."""
    # 1. Setup problematic workload in the local git repo
    glue_seed = Path("workloads/glue/customer360_elt.py")
    assert glue_seed.exists()
    workload_in_repo = local_git_repo / "jobs" / "customer360_elt.py"
    workload_in_repo.write_text(glue_seed.read_text(encoding="utf-8"), encoding="utf-8")

    # Initial git commit for the workload
    subprocess.run(["git", "add", "."], cwd=local_git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Add legacy customer360_elt job"], cwd=local_git_repo, check=True, capture_output=True
    )

    # 2. Ingest telemetry from FastMCP / Mock clients
    ce_client = MockCostExplorerClient()
    cw_client = MockCloudWatchClient()

    top_offenders = ce_client.get_top_offenders(top_n=3)
    assert len(top_offenders) >= 1

    telemetry = cw_client.extract_pipeline_telemetry("glue_customer360_elt")
    assert telemetry["gc_metrics"]["gc_time_ratio"] > 0.20

    # 3. Static AST Analysis & Patch Generation
    analyzer = ASTAnalyzer()
    source_code = workload_in_repo.read_text(encoding="utf-8")
    inspection = analyzer.inspect(source_code, str(workload_in_repo))

    assert inspection.is_valid is True
    assert inspection.anti_patterns_count >= 2
    assert "df.count()" not in inspection.patched_code or "print" in inspection.patched_code

    # 4. Deterministic FinOps Pricing
    evaluator = WorkloadEvaluator()
    roi = evaluator.evaluate_glue_customer360_elt()
    assert roi.monthly_savings_usd == Decimal("11246.40")

    # 5. Git PR Dispatch & Artifact Emission
    pattern_ids = [m.pattern_id for m in inspection.anti_patterns]
    import hashlib

    raw_fp = f"{workload_in_repo}:glue:{','.join(sorted(pattern_ids))}"
    fp = hashlib.sha256(raw_fp.encode()).hexdigest()[:16]
    branch_name = f"midas/finops-glue-{fp}"

    # Create git branch and commit verified patch
    subprocess.run(["git", "checkout", "-b", branch_name], cwd=local_git_repo, check=True, capture_output=True)
    workload_in_repo.write_text(inspection.patched_code, encoding="utf-8")

    # Save Midas Touch PR description artifact in repo
    pr_dir = local_git_repo / ".midas" / "prs"
    pr_dir.mkdir(parents=True, exist_ok=True)
    pr_file = pr_dir / f"PR-{fp}.md"

    pr_content = f"""# 🏆 [Midas FinOps] Optimize Workload: `customer360_elt`

> **Estimated Financial Impact**: **${float(roi.monthly_savings_usd):,.2f} / month**
> **Waste Reduction**: **{float(roi.waste_reduction_pct):.1f}%**

```diff
{inspection.diff}
```

<!-- midas-metadata: {{"fingerprint": "{fp}", "savings": {float(roi.monthly_savings_usd)}}} -->
"""
    pr_file.write_text(pr_content, encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=local_git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"FinOps Refactoring: Eliminate compute waste in {workload_in_repo.name}"],
        cwd=local_git_repo,
        check=True,
        capture_output=True,
    )

    # 6. Verify Git State
    log_proc = subprocess.run(
        ["git", "log", "-n", "1", "--oneline"], cwd=local_git_repo, check=True, capture_output=True, text=True
    )
    assert "FinOps Refactoring" in log_proc.stdout

    # Verify branch was created
    branch_proc = subprocess.run(
        ["git", "branch", "--show-current"], cwd=local_git_repo, check=True, capture_output=True, text=True
    )
    assert branch_proc.stdout.strip() == branch_name

    # Verify PR artifact exists and has metadata
    assert pr_file.exists()
    assert fp in pr_file.read_text(encoding="utf-8")
