"""End-to-end test suite executing static AST analysis and FinOps evaluation on seed workloads.

Tiers Covered:
- Tier 4: Real-World Application Scenarios (Glue Customer360, EMR Attribution, Databricks Ledger)
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest

from hermes_midas.ast_analyzer import ASTAnalyzer
from hermes_midas.finops import WorkloadEvaluator

# ============================================================================
# Tier 4: Seed Workloads E2E Verification
# ============================================================================


@pytest.mark.tier4
def test_e2e_glue_customer360_workload():
    """Tier 4 E2E: Full inspection and ROI calculation on Glue Customer360 seed workload."""
    script_path = Path("workloads/glue/customer360_elt.py")
    manifest_path = Path("workloads/glue/manifest.json")

    assert script_path.exists(), "Glue customer360_elt.py must exist"
    assert manifest_path.exists(), "Glue manifest.json must exist"

    source_code = script_path.read_text(encoding="utf-8")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Run static AST analyzer
    analyzer = ASTAnalyzer()
    inspection = analyzer.inspect(source_code, str(script_path))

    assert inspection.is_valid is True, f"AST inspection failed: {inspection.error}"
    assert inspection.anti_patterns_count >= 2

    detected_pattern_ids = {ap.pattern_id for ap in inspection.anti_patterns}
    assert "ORPHAN_ACTION" in detected_pattern_ids
    assert "LEGACY_UDF" in detected_pattern_ids

    # 2. Verify patched code compiles cleanly
    ast.parse(inspection.patched_code)
    compile(inspection.patched_code, "<patched_glue>", "exec")

    # 3. Evaluate deterministic FinOps ROI
    evaluator = WorkloadEvaluator()
    roi = evaluator.evaluate_glue_customer360_elt()

    expected_monthly = Decimal(str(manifest["optimized_metrics"]["monthly_savings_usd"]))
    assert roi.monthly_savings_usd == expected_monthly
    assert roi.monthly_savings_usd == Decimal("11246.40")


@pytest.mark.tier4
def test_e2e_emr_clickstream_attribution_workload():
    """Tier 4 E2E: Full inspection and ROI calculation on EMR clickstream attribution workload."""
    script_path = Path("workloads/emr/clickstream_attribution.py")
    manifest_path = Path("workloads/emr/manifest.json")

    assert script_path.exists(), "EMR clickstream_attribution.py must exist"
    assert manifest_path.exists(), "EMR manifest.json must exist"

    source_code = script_path.read_text(encoding="utf-8")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Run static AST analyzer
    analyzer = ASTAnalyzer()
    inspection = analyzer.inspect(source_code, str(script_path))

    assert inspection.is_valid is True, f"AST inspection failed: {inspection.error}"
    assert inspection.anti_patterns_count >= 1

    detected_pattern_ids = {ap.pattern_id for ap in inspection.anti_patterns}
    assert "UNBROADCASTED_JOIN" in detected_pattern_ids or "SUBOPTIMAL_PARTITION" in detected_pattern_ids

    # 2. Verify patched code compiles cleanly
    ast.parse(inspection.patched_code)
    compile(inspection.patched_code, "<patched_emr>", "exec")

    # 3. Evaluate deterministic FinOps ROI
    evaluator = WorkloadEvaluator()
    roi = evaluator.evaluate_emr_clickstream_attribution()

    expected_monthly = Decimal(str(manifest["optimized_metrics"]["monthly_savings_usd"]))
    assert roi.monthly_savings_usd == expected_monthly
    assert roi.monthly_savings_usd == Decimal("303.64")


@pytest.mark.tier4
def test_e2e_databricks_financial_ledger_sync_workload():
    """Tier 4 E2E: Full inspection and ROI calculation on Databricks ledger workload."""
    script_path = Path("workloads/databricks/financial_ledger_sync.py")
    manifest_path = Path("workloads/databricks/manifest.json")

    assert script_path.exists(), "Databricks financial_ledger_sync.py must exist"
    assert manifest_path.exists(), "Databricks manifest.json must exist"

    source_code = script_path.read_text(encoding="utf-8")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Run static AST analyzer
    analyzer = ASTAnalyzer()
    analyzer.inspect(source_code, str(script_path))

    # Must compile original and patched
    ast.parse(source_code)
    compile(source_code, "<orig_db>", "exec")

    # 2. Evaluate deterministic FinOps ROI
    evaluator = WorkloadEvaluator()
    roi = evaluator.evaluate_databricks_financial_ledger_sync()

    expected_monthly = Decimal(str(manifest["optimized_metrics"]["monthly_savings_usd"]))
    assert roi.monthly_savings_usd == expected_monthly
    assert roi.monthly_savings_usd == Decimal("5829.60")


@pytest.mark.tier4
def test_e2e_emr_ec2_graviton_spot_workload():
    """Tier 4 E2E: Full inspection and ROI calculation on EMR EC2 Graviton/Spot workload."""
    script_path = Path("workloads/emr_ec2/graviton_spot_cluster.py")
    manifest_path = Path("workloads/emr_ec2/manifest.json")

    assert script_path.exists(), "EMR EC2 script must exist"
    assert manifest_path.exists(), "EMR EC2 manifest must exist"

    source_code = script_path.read_text(encoding="utf-8")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. AST Inspector
    analyzer = ASTAnalyzer()
    inspection = analyzer.inspect(source_code, str(script_path))
    assert inspection.is_valid is True
    assert inspection.anti_patterns_count >= 2
    ast.parse(inspection.patched_code)
    compile(inspection.patched_code, "<patched_emr_ec2>", "exec")

    # 2. FinOps ROI
    evaluator = WorkloadEvaluator()
    roi = evaluator.evaluate_emr_ec2_graviton_spot()
    expected_monthly = Decimal(str(manifest["optimized_metrics"]["monthly_savings_usd"]))
    assert roi.monthly_savings_usd == expected_monthly
    assert roi.monthly_savings_usd == Decimal("370.56")


@pytest.mark.tier4
def test_e2e_delta_lake_compaction_optimizer_workload():
    """Tier 4 E2E: Full inspection and ROI calculation on Delta Lake compaction workload."""
    script_path = Path("workloads/delta_lake/compaction_optimizer.py")
    manifest_path = Path("workloads/delta_lake/manifest.json")

    assert script_path.exists(), "Delta Lake script must exist"
    assert manifest_path.exists(), "Delta Lake manifest must exist"

    source_code = script_path.read_text(encoding="utf-8")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. AST Inspector
    analyzer = ASTAnalyzer()
    inspection = analyzer.inspect(source_code, str(script_path))
    assert inspection.is_valid is True
    assert inspection.anti_patterns_count >= 2
    ast.parse(inspection.patched_code)
    compile(inspection.patched_code, "<patched_delta>", "exec")

    # 2. FinOps ROI
    evaluator = WorkloadEvaluator()
    roi = evaluator.evaluate_delta_compaction_optimizer()
    expected_monthly = Decimal(str(manifest["optimized_metrics"]["monthly_savings_usd"]))
    assert roi.monthly_savings_usd == expected_monthly
    assert roi.monthly_savings_usd == Decimal("793.80")


@pytest.mark.tier4
def test_e2e_dbt_snowflake_customer_orders_workload():
    """Tier 4 E2E: Full inspection and ROI calculation on dbt Snowflake seed workload."""
    from hermes_midas.sql_analyzer import SQLAnalyzer

    script_path = Path("workloads/dbt_snowflake/models/marts/fct_customer_orders.sql")
    manifest_path = Path("workloads/dbt_snowflake/manifest.json")

    assert script_path.exists(), "dbt Snowflake fct_customer_orders.sql must exist"
    assert manifest_path.exists(), "dbt Snowflake manifest.json must exist"

    source_code = script_path.read_text(encoding="utf-8")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. SQL AST Analyzer
    analyzer = SQLAnalyzer()
    inspection = analyzer.inspect(source_code, str(script_path), dialect="snowflake")
    assert inspection.is_valid is True
    assert inspection.anti_patterns_count >= 3

    detected_pattern_ids = {ap.pattern_id for ap in inspection.anti_patterns}
    assert "SELECT_STAR" in detected_pattern_ids
    assert "CARTESIAN_PRODUCT" in detected_pattern_ids
    assert "UNFILTERED_PARTITION_SCAN" in detected_pattern_ids

    # 2. FinOps ROI
    evaluator = WorkloadEvaluator()
    roi = evaluator.evaluate_dbt_snowflake_customer_orders()
    expected_monthly = Decimal(str(manifest["optimized_metrics"]["monthly_savings_usd"]))
    assert roi.monthly_savings_usd == expected_monthly
    assert roi.monthly_savings_usd == Decimal("5076.00")
    assert roi.waste_reduction_pct == Decimal("99.30")
    assert roi.annual_savings_usd == Decimal("60912.00")
