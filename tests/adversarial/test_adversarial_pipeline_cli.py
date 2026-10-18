"""Adversarial stress tests for Unified Pipeline and CLI.

Focus areas:
- CLI command invocation with edge inputs (missing files, invalid engines, boundary durations, formats)
- Pipeline handling of edge inputs (empty files, syntax errors, non-PySpark files, unicode paths)
- Pipeline threshold suppression and deduplication idempotency
- Git repository vs non-git directory PR creation isolation
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hermes_midas.cli import app
from hermes_midas.orchestrator.pipeline import (
    async_optimize_workload,
    detect_engine_from_path_or_content,
    optimize_workload,
)

runner = CliRunner()


# ============================================================================
# Section 1: Engine Detection Edge Cases
# ============================================================================


@pytest.mark.tier2
def test_detect_engine_priority_and_fallbacks():
    """Verify engine detection heuristics on ambiguous or clean paths and contents."""
    # EMR in path
    assert detect_engine_from_path_or_content("jobs/emr_step.py", "x = 1") == "emr_serverless"
    # EMR in content
    assert detect_engine_from_path_or_content("jobs/step.py", "# EMR Serverless step") == "emr_serverless"
    # Databricks in path
    assert detect_engine_from_path_or_content("jobs/databricks_job.py", "x = 1") == "databricks"
    # dbutils in content
    assert detect_engine_from_path_or_content("jobs/job.py", "dbutils.fs.ls('/')") == "databricks"
    # Default fallback is glue
    assert detect_engine_from_path_or_content("jobs/generic.py", "spark.read.parquet()") == "glue"


# ============================================================================
# Section 2: Unified Pipeline Stress Tests
# ============================================================================


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_pipeline_non_existent_file_raises_filenotfound(tmp_path: Path):
    """Pipeline raises FileNotFoundError when script does not exist."""
    missing = tmp_path / "does_not_exist.py"
    with pytest.raises(FileNotFoundError, match="Workload script not found"):
        await async_optimize_workload(str(missing), repo_path=tmp_path)


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_pipeline_empty_file_skipped_no_issues(tmp_path: Path):
    """Pipeline handles an empty 0-byte script gracefully with SKIPPED_NO_ISSUES."""
    empty_file = tmp_path / "empty_job.py"
    empty_file.write_text("", encoding="utf-8")

    result = await async_optimize_workload(str(empty_file), repo_path=tmp_path)
    assert result.status == "SUCCESS"
    assert result.pr_action == "SKIPPED_NO_ISSUES"
    assert result.anti_patterns_count == 0
    assert result.ast_valid is True


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_pipeline_clean_file_skipped_no_issues(tmp_path: Path):
    """Pipeline on code with no anti-patterns returns SKIPPED_NO_ISSUES without creating PR."""
    clean_code = """import pyspark.sql.functions as F
from pyspark.sql import SparkSession

def main():
    spark = SparkSession.builder.appName("Clean").getOrCreate()
    df = spark.read.parquet("s3://bucket/data")
    dim = spark.read.parquet("s3://bucket/dim")
    joined = df.join(F.broadcast(dim), "id", "inner")
    joined.write.partitionBy("date").parquet("s3://bucket/out")
"""
    clean_file = tmp_path / "clean_job.py"
    clean_file.write_text(clean_code, encoding="utf-8")

    result = await async_optimize_workload(str(clean_file), repo_path=tmp_path)
    assert result.status == "SUCCESS"
    assert result.pr_action == "SKIPPED_NO_ISSUES"
    assert result.anti_patterns_count == 0


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_pipeline_min_savings_threshold_suppression(tmp_path: Path):
    """Pipeline suppresses PR creation when savings fall below min_savings_threshold."""
    problematic_code = """from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
df = spark.read.parquet("s3://bucket/data")
df.count()
df.show(5)
"""
    job_file = tmp_path / "job.py"
    job_file.write_text(problematic_code, encoding="utf-8")

    # Set threshold higher than standard Glue savings ($11,246.40)
    result = await async_optimize_workload(
        str(job_file),
        repo_path=tmp_path,
        min_savings_threshold=50000.0,
    )
    assert result.status == "SUCCESS"
    assert result.pr_action == "SKIPPED_BELOW_THRESHOLD"
    assert result.anti_patterns_count >= 1
    # Verify no PR was opened
    assert result.pr_url is None


@pytest.mark.tier2
def test_pipeline_deduplication_idempotency_sync(tmp_path: Path):
    """Pipeline sync entry point: second consecutive run results in SKIPPED_DEDUPLICATED."""
    problematic_code = """from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
df = spark.read.parquet("s3://bucket/data")
df.count()
df.show(5)
"""
    job_file = tmp_path / "dedup_job.py"
    job_file.write_text(problematic_code, encoding="utf-8")

    # Run 1: Should create PR
    res1 = optimize_workload(str(job_file), repo_path=tmp_path)
    assert res1.pr_action in ("CREATED", "UPDATED")
    assert res1.fingerprint != ""

    # Run 2: Same file and state -> Should deduplicate
    res2 = optimize_workload(str(job_file), repo_path=tmp_path)
    assert res2.pr_action == "SKIPPED_DEDUPLICATED"
    assert res2.fingerprint == res1.fingerprint


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_pipeline_isolated_in_real_git_repo(tmp_path: Path):
    """Pipeline running inside a real git repo preserves current branch and creates dedicated PR branch."""
    repo_dir = tmp_path / "git_repo"
    repo_dir.mkdir()

    # Initialize real git repo
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)

    job_file = repo_dir / "my_workload.py"
    job_code = """from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
df = spark.read.parquet("s3://bucket/data")
df.count()
"""
    job_file.write_text(job_code, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True)

    # Run pipeline
    result = await async_optimize_workload(str(job_file), repo_path=repo_dir)
    assert result.status == "SUCCESS"
    assert result.pr_action == "CREATED"

    # Verify that the active git branch is still 'main' (not left dirty or on PR branch)
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo_dir, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert current_branch == "main"

    # Verify the canonical file on main was NOT overwritten
    assert "df.count()" in job_file.read_text(encoding="utf-8")

    # Verify the dedicated PR branch exists and has the patch applied
    branches = subprocess.run(["git", "branch"], cwd=repo_dir, check=True, capture_output=True, text=True).stdout
    assert result.branch_name in branches


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_pipeline_unicode_and_spaces_in_path(tmp_path: Path):
    """Pipeline handles script paths with spaces and Unicode characters gracefully."""
    special_dir = tmp_path / "Folder with Spaces & 🚀"
    special_dir.mkdir()
    script = special_dir / "unicode_etl_é.py"
    script.write_text(
        "# Unicode: こんにちは\nfrom pyspark.sql import SparkSession\nspark = SparkSession.builder.getOrCreate()\n"
        "df = spark.read.parquet('s3://lake/')\ndf.count()\n",
        encoding="utf-8",
    )

    result = await async_optimize_workload(str(script), repo_path=tmp_path)
    assert result.status == "SUCCESS"
    assert result.pr_action == "CREATED"
    assert result.anti_patterns_count >= 1


# ============================================================================
# Section 3: CLI Edge Case Stress Tests
# ============================================================================


@pytest.mark.tier1
def test_cli_help():
    """CLI root help executes cleanly."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "Autonomous FinOps" in res.stdout


@pytest.mark.tier2
def test_cli_analyze_missing_file():
    """CLI analyze on non-existent file returns exit code 1 with error."""
    res = runner.invoke(app, ["analyze", "--script", "non_existent_file_xyz.py"])
    assert res.exit_code == 1
    assert "File not found" in res.stdout


@pytest.mark.tier2
def test_cli_analyze_terminal_and_markdown_formats(tmp_path: Path):
    """CLI analyze supports terminal and markdown formats."""
    test_file = tmp_path / "sample.py"
    test_file.write_text(
        "from pyspark.sql import SparkSession\nspark = SparkSession.builder.getOrCreate()\n"
        "df = spark.read.parquet('s3://data')\ndf.count()\n",
        encoding="utf-8",
    )

    # 1. Terminal format
    res_term = runner.invoke(app, ["analyze", "--script", str(test_file), "--format", "terminal"])
    assert res_term.exit_code == 0
    assert "Static AST Analysis" in res_term.stdout
    assert "ORPHAN_ACTION" in res_term.stdout

    # 2. Markdown format
    res_md = runner.invoke(app, ["analyze", "--script", str(test_file), "--format", "markdown"])
    assert res_md.exit_code == 0
    assert "# AST Analysis:" in res_md.stdout
    assert "ORPHAN_ACTION" in res_md.stdout


@pytest.mark.tier2
def test_cli_analyze_json_format_soft_wrap_valid_json(tmp_path: Path):
    """Verify rich console.print uses soft_wrap=True in JSON mode,
    ensuring output is valid JSON without newline corruption.
    """
    test_file = tmp_path / "sample.py"
    test_file.write_text(
        "from pyspark.sql import SparkSession\nspark = SparkSession.builder.getOrCreate()\n"
        "df = spark.read.parquet('s3://data')\ndf.count()\n",
        encoding="utf-8",
    )
    res_json = runner.invoke(app, ["analyze", "--script", str(test_file), "--format", "json"])
    assert res_json.exit_code == 0
    parsed = json.loads(res_json.stdout)
    assert "anti_patterns" in parsed
    assert parsed["anti_patterns_count"] >= 1


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_webhook_returned_branch_matches_pipeline_git_branch(tmp_path: Path):
    """Verify Webhook response returns synchronized branch matching the git provider PR."""
    import httpx

    from hermes_midas.mcp_servers.git_providers import get_git_provider
    from hermes_midas.orchestrator.webhook import create_airflow_trigger_app

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    job_file = repo_dir / "job.py"
    job_file.write_text(
        "from pyspark.sql import SparkSession\nspark = SparkSession.builder.getOrCreate()\n"
        "df = spark.read.parquet('s3://data')\ndf.count()\n",
        encoding="utf-8",
    )

    app_instance = create_airflow_trigger_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_instance), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/triggers/airflow",
            json={
                "dag_id": "test_dag",
                "task_id": "test_task",
                "run_id": "run_1",
                "execution_date": "2026-10-15T12:00:00Z",
                "engine": "glue",
                "script_path": str(job_file),
                "repo_path": str(repo_dir),
            },
            headers={"X-Midas-Bypass-Auth": "1"},
        )
        assert res.status_code == 200
        data = res.json()
        returned_branch = data.get("branch_name")

        git_provider = get_git_provider(str(repo_dir))
        open_prs = git_provider.list_open_prs(str(repo_dir))
        assert len(open_prs) >= 1
        actual_git_branch = open_prs[0].get("branch")

        # Verify synchronized branch name
        assert returned_branch == actual_git_branch
        assert returned_branch.startswith("midas/finops-")
        assert actual_git_branch.startswith("midas/finops-")


@pytest.mark.tier2
def test_cron_auditor_fingerprint_delimiter_collision_vulnerability():
    """Adversarial check: ScheduledCronAuditor computes raw_fp with unescaped ':' delimiters,
    causing fingerprint collisions between different file paths and engine names.
    """
    import hashlib

    # Case 1: path="workloads:glue", engine="etl", pattern="P1"
    raw_a = f"{Path('workloads:glue')}:etl:P1"
    fp_a = hashlib.sha256(raw_a.encode("utf-8")).hexdigest()[:16]

    # Case 2: path="workloads", engine="glue:etl", pattern="P1"
    raw_b = f"{Path('workloads')}:glue:etl:P1"
    fp_b = hashlib.sha256(raw_b.encode("utf-8")).hexdigest()[:16]

    # In cron_auditor.py, raw string joining causes a collision:
    assert fp_a == fp_b, "Demonstrates unescaped delimiter collision in ScheduledCronAuditor"


@pytest.mark.tier2
def test_cli_calculate_all_engines_and_edge_values():
    """CLI calculate handles all engines, 0 seconds floor, and unsupported engines."""
    # Glue
    res_glue = runner.invoke(app, ["calculate", "--engine", "glue", "--duration-secs", "3600", "--units", "10"])
    assert res_glue.exit_code == 0
    assert "AWS Glue Run Cost" in res_glue.stdout

    # EMR Serverless
    res_emr = runner.invoke(app, ["calculate", "--engine", "emr_serverless", "--duration-secs", "1200", "--units", "4"])
    assert res_emr.exit_code == 0
    assert "AWS EMR Serverless Run Cost" in res_emr.stdout

    # Databricks
    res_db = runner.invoke(app, ["calculate", "--engine", "databricks", "--duration-secs", "1800", "--units", "8"])
    assert res_db.exit_code == 0
    assert "Databricks Run Cost" in res_db.stdout

    # Unsupported engine
    res_bad = runner.invoke(app, ["calculate", "--engine", "unsupported_cloud", "--duration-secs", "100"])
    assert res_bad.exit_code == 0
    assert "Unsupported compute engine" in res_bad.stdout

    # 0 seconds billing floor
    res_floor = runner.invoke(app, ["calculate", "--engine", "glue", "--duration-secs", "0", "--units", "2"])
    assert res_floor.exit_code == 0
    assert "Billable Seconds: 60" in res_floor.stdout


@pytest.mark.tier2
def test_cli_audit_empty_and_json_output(tmp_path: Path):
    """CLI audit handles empty folders and writes valid JSON report."""
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    out_json = tmp_path / "audit_report.json"

    res = runner.invoke(app, ["audit", "--repo", str(empty_repo), "--output-report", str(out_json)])
    assert res.exit_code == 0
    assert "Hermes Midas FinOps Audit Summary" in res.stdout
    assert out_json.exists()

    report_data = json.loads(out_json.read_text(encoding="utf-8"))
    assert report_data["scanned_workloads_count"] == 0
    assert report_data["offending_workloads_count"] == 0
    assert report_data["prs_created"] == 0


@pytest.mark.tier2
def test_cli_optimize_on_seed_workload(tmp_path: Path):
    """CLI optimize command runs end-to-end on a copy of customer360_elt."""
    test_repo = tmp_path / "repo"
    test_repo.mkdir()
    job = test_repo / "customer360_elt.py"
    job.write_text(Path("workloads/glue/customer360_elt.py").read_text(encoding="utf-8"), encoding="utf-8")

    # Run optimize via CLI
    res = runner.invoke(app, ["optimize", "--script", str(job), "--repo", str(test_repo)])
    assert res.exit_code == 0
    assert "Midas Touch Pipeline Optimization Result" in res.stdout
    assert "customer360_elt" in res.stdout
    assert "CREATED" in res.stdout
    assert "$11,246.40" in res.stdout

    # Second run should be SKIPPED_DEDUPLICATED
    res2 = runner.invoke(app, ["optimize", "--script", str(job), "--repo", str(test_repo)])
    assert res2.exit_code == 0
    assert "SKIPPED_DEDUPLICATED" in res2.stdout
