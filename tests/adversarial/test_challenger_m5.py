"""Empirical Challenger Verification Test Suite for Milestone 5 Gate.

Executed by: Challenger 1 (Empirical Challenger)
Focus Areas:
1. Static AST Analyzer: Arbitrary PySpark pipelines, patch synthesis, and compile verification.
2. Deterministic FinOps Calculator: Authoritative pricing formulas against independent Decimal oracles.
3. FastMCP Tool Servers: Programmatic execution of tools via MCP protocol and telemetry verification.
4. Seed Workloads: End-to-end alignment with platform manifests and ROI targets.
"""

from __future__ import annotations

import ast
import json
import math
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from hermes_midas.ast_analyzer import ASTAnalyzer
from hermes_midas.finops import (
    DatabricksCalculator,
    DatabricksResourceSpec,
    EmrResourceSpec,
    EmrServerlessCalculator,
    FinOpsCalculator,
    GluePricingCalculator,
    GlueResourceSpec,
    WorkloadEvaluator,
)
from hermes_midas.finops.rates import (
    DATABRICKS_DBU_RATES,
    DATABRICKS_INSTANCE_MAP,
    DAYS_PER_MONTH,
    EMR_RAM_GB_HOURLY_RATE,
    EMR_STORAGE_GB_HOURLY_RATE,
    EMR_VCPU_HOURLY_RATE,
    GLUE_FLEX_DPU_HOURLY_RATE,
    GLUE_STANDARD_DPU_HOURLY_RATE,
    GLUE_WORKER_DPU_MAP,
    MONTHS_PER_YEAR,
)
from hermes_midas.mcp_servers.cloudwatch import server as cw_server
from hermes_midas.mcp_servers.cost_explorer import server as ce_server
from hermes_midas.mcp_servers.git_repo import server as git_server
from hermes_midas.topology.seed_loader import SeedDataLoader

# ============================================================================
# Section 1: AST Analyzer Empirical Stress Tests
# ============================================================================


class TestASTAnalyzerEmpirical:
    """Stress tests and empirical validation of PySpark AST analysis and patching."""

    def test_ast_arbitrary_pyspark_pipeline_multi_anti_patterns(self):
        """Stress test AST analyzer on an arbitrary complex PySpark pipeline with multiple anti-patterns."""
        arbitrary_pyspark_code = '''"""Arbitrary PySpark Pipeline with multiple anti-patterns."""
from pyspark.sql import SparkSession
from pyspark.sql.functions import udf
from pyspark.sql.types import StringType

spark = SparkSession.builder.appName("ArbitraryTest").getOrCreate()
df_transactions = spark.read.parquet("s3://lake/transactions/")
dim_customers = spark.read.parquet("s3://lake/dim_customers/")
lookup_stores = spark.read.parquet("s3://lake/lookup_stores/")

# 1. Orphan actions
df_transactions.count()
df_transactions.show(20)

# 2. Dead assignment
_ = df_transactions.collect()
cnt = df_transactions.take(10)

# 3. Action inside print
print(f"Loaded: {df_transactions.first()}")

# 4. Unbroadcasted dimension joins
df_joined = df_transactions.join(dim_customers, "customer_id", "left")
df_joined2 = df_joined.join(lookup_stores, "store_id", "inner")

# 5. Excessive repartition
df_repart = df_joined2.repartition(1000)

# 6. Coalesce(1) bottleneck
df_bottleneck = df_repart.coalesce(1)

# 7. Legacy row-by-row UDF
@udf(returnType=StringType())
def format_code(val):
    return str(val).strip().upper()

df_enriched = df_bottleneck.withColumn("code", format_code("raw_code"))

# 8. Unpartitioned write
df_enriched.write.mode("overwrite").parquet("s3://lake/curated/")
'''
        analyzer = ASTAnalyzer()
        result = analyzer.inspect(arbitrary_pyspark_code, file_path="arbitrary_pipeline.py")

        # 1. Verify anti-pattern detection
        assert len(result.anti_patterns) >= 7, f"Expected >= 7 anti-patterns, got {len(result.anti_patterns)}"
        pattern_ids = {m.pattern_id for m in result.anti_patterns}
        assert "ORPHAN_ACTION" in pattern_ids
        assert "UNBROADCASTED_JOIN" in pattern_ids
        assert "SUBOPTIMAL_PARTITION" in pattern_ids
        assert "LEGACY_UDF" in pattern_ids

        # 2. Verify 4-gate validation result
        assert result.is_valid is True, f"Inspection validation failed: {result.error}"
        assert result.diff != "", "Expected non-empty unified diff"

        # 3. Empirical check: ast.parse and compile bytecode execution
        parsed_tree = ast.parse(result.patched_code)
        assert isinstance(parsed_tree, ast.Module)
        compiled_bytecode = compile(result.patched_code, "<ast_patch:arbitrary_pipeline.py>", mode="exec")
        assert compiled_bytecode is not None

        # 4. Verify specific transformations in patched code
        assert "df_transactions.count()" not in result.patched_code
        assert "df_transactions.show(20)" not in result.patched_code
        assert "F.broadcast(dim_customers)" in result.patched_code
        assert "F.broadcast(lookup_stores)" in result.patched_code
        assert "coalesce(64)" in result.patched_code
        assert "coalesce(16)" in result.patched_code
        assert "pandas_udf" in result.patched_code
        assert "import pyspark.sql.functions as F" in result.patched_code

    def test_ast_patch_compiles_on_all_seed_workloads(self):
        """Verify that every seed workload transforms into 100% valid, compilable Python bytecode."""
        analyzer = ASTAnalyzer()
        workloads_dir = Path(__file__).resolve().parent.parent.parent / "workloads"
        seed_files = [
            workloads_dir / "glue" / "customer360_elt.py",
            workloads_dir / "emr" / "clickstream_attribution.py",
            workloads_dir / "databricks" / "financial_ledger_sync.py",
        ]

        for seed_file in seed_files:
            assert seed_file.exists(), f"Seed file missing: {seed_file}"
            source = seed_file.read_text(encoding="utf-8")
            result = analyzer.inspect(source, file_path=str(seed_file))

            # Must be valid
            assert result.is_valid is True, f"Failed validation for {seed_file}: {result.error}"
            # Must parse without syntax errors
            parsed = ast.parse(result.patched_code)
            assert parsed is not None
            # Must compile to bytecode without error
            compiled = compile(result.patched_code, filename=f"<patch:{seed_file.name}>", mode="exec")
            assert compiled is not None

    def test_ast_syntax_error_resilience(self):
        """Verify unparsable source code returns is_valid=False with SYNTAX_ERROR match."""
        analyzer = ASTAnalyzer()
        invalid_code = "def invalid_python_syntax(:\n    df.count()\n"
        result = analyzer.inspect(invalid_code, file_path="syntax_error.py")

        assert result.is_valid is False
        assert len(result.anti_patterns) == 1
        assert result.anti_patterns[0].pattern_id == "SYNTAX_ERROR"
        assert result.validation_result.is_valid is False

    def test_ast_clean_code_invariance(self):
        """Verify already optimal code produces no diff and remains valid."""
        clean_code = """import pyspark.sql.functions as F

def optimal_job(spark):
    df = spark.read.parquet("s3://lake/events")
    dim = spark.read.parquet("s3://lake/dim_users")
    df_joined = df.join(F.broadcast(dim), "user_id", "inner")
    df_opt = df_joined.coalesce(64)
    df_opt.write.mode("overwrite").partitionBy("event_date").parquet("s3://lake/curated")
"""
        analyzer = ASTAnalyzer()
        result = analyzer.inspect(clean_code, file_path="clean.py")

        assert result.is_valid is True
        assert len(result.anti_patterns) == 0
        assert result.diff == ""
        assert result.patched_code == clean_code

    def test_ast_empty_block_pass_injection(self):
        """Verify removing orphan actions from if/else or try/except inserts pass statements."""
        code_with_orphan_in_blocks = """def run(df):
    if df is not None:
        df.count()
    else:
        df.show()
    try:
        df.collect()
    except Exception:
        df.first()
"""
        analyzer = ASTAnalyzer()
        result = analyzer.inspect(code_with_orphan_in_blocks)

        assert result.is_valid is True
        # Verify compiled without IndentationError
        compile(result.patched_code, "<test_pass>", "exec")
        assert "pass" in result.patched_code

    def test_ast_already_broadcasted_join_idempotency(self):
        """Verify joining with already broadcasted dimension does not re-wrap."""
        code = """import pyspark.sql.functions as F
df = spark.read.parquet("s3://events")
dim = spark.read.parquet("s3://dim_customers")
df_joined = df.join(F.broadcast(dim), "id", "inner")
"""
        analyzer = ASTAnalyzer()
        matches = analyzer.analyze(code)
        # Should not detect unbroadcasted join
        unbroadcasted = [m for m in matches if m.pattern_id == "UNBROADCASTED_JOIN"]
        assert len(unbroadcasted) == 0

    def test_ast_custom_dimension_identifiers(self):
        """Verify custom dimension set flags joins against custom table names."""
        code = """df_sales = spark.read.parquet("s3://sales")
auxiliary_data = spark.read.parquet("s3://aux")
df_joined = df_sales.join(auxiliary_data, "key", "left")
"""
        analyzer_default = ASTAnalyzer()
        matches_default = analyzer_default.analyze(code)
        assert len(matches_default) == 0

        # Now supply custom dimension identifier
        analyzer_custom = ASTAnalyzer(custom_dimensions={"auxiliary_data"})
        matches_custom = analyzer_custom.analyze(code)
        assert len(matches_custom) == 1
        assert matches_custom[0].pattern_id == "UNBROADCASTED_JOIN"


# ============================================================================
# Section 2: FinOps Calculator Independent Decimal Oracle
# ============================================================================


def oracle_glue_cost(
    worker_type: str,
    num_workers: int,
    is_flex: bool,
    duration_seconds: Decimal | float,
) -> Decimal:
    """Independent ground-up calculation for AWS Glue job run cost."""
    sec = Decimal(str(duration_seconds))
    billable_sec = max(Decimal(60), Decimal(str(math.ceil(float(sec)))))
    dpu_unit = GLUE_WORKER_DPU_MAP[worker_type.lower()]
    total_dpu = Decimal(str(num_workers)) * dpu_unit
    rate = GLUE_FLEX_DPU_HOURLY_RATE if is_flex else GLUE_STANDARD_DPU_HOURLY_RATE
    hourly = total_dpu * rate
    return hourly * (billable_sec / Decimal(3600))


def oracle_emr_cost(
    executor_count: int,
    executor_vcpu: Decimal,
    executor_memory_gb: Decimal,
    storage_gb_per_worker: Decimal,
    driver_vcpu: Decimal,
    driver_memory_gb: Decimal,
    duration_seconds: Decimal | float,
) -> Decimal:
    """Independent ground-up calculation for AWS EMR Serverless run cost."""
    sec = Decimal(str(duration_seconds))
    billable_sec = max(Decimal(60), Decimal(str(math.ceil(float(sec)))))
    tot_vcpu = driver_vcpu + (Decimal(str(executor_count)) * executor_vcpu)
    tot_ram = driver_memory_gb + (Decimal(str(executor_count)) * executor_memory_gb)
    extra_storage = max(Decimal(0), storage_gb_per_worker - Decimal(20))
    billable_storage = extra_storage * Decimal(str(executor_count + 1))

    hourly_vcpu = tot_vcpu * EMR_VCPU_HOURLY_RATE
    hourly_ram = tot_ram * EMR_RAM_GB_HOURLY_RATE
    hourly_storage = billable_storage * EMR_STORAGE_GB_HOURLY_RATE
    hourly_total = hourly_vcpu + hourly_ram + hourly_storage
    return hourly_total * (billable_sec / Decimal(3600))


def oracle_databricks_cost(
    node_type: str,
    num_workers: int,
    tier: str,
    duration_seconds: Decimal | float,
) -> Decimal:
    """Independent ground-up calculation for Databricks cluster run cost."""
    sec = Decimal(str(duration_seconds))
    billable_sec = max(Decimal(60), Decimal(str(math.ceil(float(sec)))))
    total_nodes = Decimal(str(1 + num_workers))
    node_info = DATABRICKS_INSTANCE_MAP[node_type.lower()]
    dbu_unit_rate = DATABRICKS_DBU_RATES[tier.lower()]

    hourly_dbu = total_nodes * node_info["dbu"] * dbu_unit_rate
    hourly_ec2 = total_nodes * node_info["ec2_hourly"]
    hourly_total = hourly_dbu + hourly_ec2
    return hourly_total * (billable_sec / Decimal(3600))


class TestFinOpsCalculatorEmpirical:
    """Stress tests verifying FinOps calculator formulas against independent decimal calculations."""

    @pytest.mark.parametrize(
        "worker_type,num_workers,is_flex,dur_base,dur_opt,runs_day",
        [
            ("G.2X", 10, False, 1200, 400, 24),
            ("G.1X", 20, True, 3600, 1800, 4),
            ("G.4X", 5, False, 600, 120, 12),
            ("G.8X", 2, False, 45, 10, 1),  # Tests under-60s floor
            ("standard", 15, True, 75.4, 60.1, 8),  # Tests ceil rounding
        ],
    )
    def test_finops_glue_against_independent_decimal_oracle(
        self, worker_type, num_workers, is_flex, dur_base, dur_opt, runs_day
    ):
        calc = GluePricingCalculator()
        spec_base = GlueResourceSpec(worker_type=worker_type, num_workers=num_workers, is_flex=is_flex)
        spec_opt = GlueResourceSpec(worker_type=worker_type, num_workers=num_workers, is_flex=is_flex)

        impact = calc.calculate_roi(spec_base, dur_base, spec_opt, dur_opt, runs_per_day=runs_day)

        # Independent oracle check
        c_base = oracle_glue_cost(worker_type, num_workers, is_flex, dur_base)
        c_opt = oracle_glue_cost(worker_type, num_workers, is_flex, dur_opt)
        savings_run = c_base - c_opt
        daily = savings_run * Decimal(str(runs_day))
        monthly = daily * DAYS_PER_MONTH
        annual = monthly * MONTHS_PER_YEAR

        assert impact.baseline_cost_usd == c_base.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        assert impact.optimized_cost_usd == c_opt.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        assert impact.cost_savings_per_run_usd == savings_run.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        assert impact.daily_savings_usd == daily.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert impact.monthly_savings_usd == monthly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert impact.annual_savings_usd == annual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @pytest.mark.parametrize(
        "executors,vcpu,ram,storage,dur_base,dur_opt,runs_day",
        [
            (16, Decimal(4), Decimal(16), Decimal(20), 750, 250, 4),
            (32, Decimal(8), Decimal(32), Decimal(50), 1800, 900, 2),
            (8, Decimal(2), Decimal(8), Decimal(80), 30, 15, 10),  # Tests floor
            (4, Decimal(4), Decimal(16), Decimal(20), 121.2, 60.5, 6),  # Fractional seconds
        ],
    )
    def test_finops_emr_against_independent_decimal_oracle(
        self, executors, vcpu, ram, storage, dur_base, dur_opt, runs_day
    ):
        calc = EmrServerlessCalculator()
        spec_base = EmrResourceSpec(
            executor_count=executors,
            executor_vcpu=vcpu,
            executor_memory_gb=ram,
            storage_gb_per_worker=storage,
        )
        spec_opt = EmrResourceSpec(
            executor_count=executors,
            executor_vcpu=vcpu,
            executor_memory_gb=ram,
            storage_gb_per_worker=storage,
        )

        impact = calc.calculate_roi(spec_base, dur_base, spec_opt, dur_opt, runs_per_day=runs_day)

        c_base = oracle_emr_cost(executors, vcpu, ram, storage, Decimal(2), Decimal(8), dur_base)
        c_opt = oracle_emr_cost(executors, vcpu, ram, storage, Decimal(2), Decimal(8), dur_opt)
        savings_run = c_base - c_opt
        daily = savings_run * Decimal(str(runs_day))
        monthly = daily * DAYS_PER_MONTH
        annual = monthly * MONTHS_PER_YEAR

        assert impact.baseline_cost_usd == c_base.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        assert impact.optimized_cost_usd == c_opt.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        assert impact.daily_savings_usd == daily.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert impact.monthly_savings_usd == monthly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert impact.annual_savings_usd == annual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @pytest.mark.parametrize(
        "node_type,workers,tier,dur_base,dur_opt,runs_day",
        [
            ("r5.4xlarge", 63, "jobs_enterprise", 7200, 1800, 1),
            ("m5.xlarge", 8, "jobs_standard", 3600, 1200, 3),
            ("i3.2xlarge", 16, "all_purpose_standard", 1800, 600, 2),
            ("c5.2xlarge", 4, "serverless_jobs", 900, 300, 12),
            ("i3en.3xlarge", 10, "jobs_enterprise", 45, 20, 1),  # Floor
        ],
    )
    def test_finops_databricks_against_independent_decimal_oracle(
        self, node_type, workers, tier, dur_base, dur_opt, runs_day
    ):
        calc = DatabricksCalculator()
        spec_base = DatabricksResourceSpec(node_type=node_type, num_workers=workers, tier=tier)
        spec_opt = DatabricksResourceSpec(node_type=node_type, num_workers=workers, tier=tier)

        impact = calc.calculate_roi(spec_base, dur_base, spec_opt, dur_opt, runs_per_day=runs_day)

        c_base = oracle_databricks_cost(node_type, workers, tier, dur_base)
        c_opt = oracle_databricks_cost(node_type, workers, tier, dur_opt)
        savings_run = c_base - c_opt
        daily = savings_run * Decimal(str(runs_day))
        monthly = daily * DAYS_PER_MONTH
        annual = monthly * MONTHS_PER_YEAR

        assert impact.baseline_cost_usd == c_base.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        assert impact.optimized_cost_usd == c_opt.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        assert impact.daily_savings_usd == daily.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert impact.monthly_savings_usd == monthly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert impact.annual_savings_usd == annual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def test_finops_billing_floor_enforcement(self):
        """Verify strict enforcement of the 60-second minimum billing floor."""
        calc = FinOpsCalculator()
        # For durations <= 60s, cost must be identical to 60s
        glue_spec = GlueResourceSpec(worker_type="g.2x", num_workers=10)
        c0 = calc.glue.calculate_run_cost(glue_spec, 0)
        c1 = calc.glue.calculate_run_cost(glue_spec, 1)
        c30 = calc.glue.calculate_run_cost(glue_spec, 30)
        c59 = calc.glue.calculate_run_cost(glue_spec, 59.9)
        c60 = calc.glue.calculate_run_cost(glue_spec, 60)

        assert c0.billable_seconds == Decimal(60)
        assert c1.billable_seconds == Decimal(60)
        assert c30.billable_seconds == Decimal(60)
        assert c59.billable_seconds == Decimal(60)
        assert c60.billable_seconds == Decimal(60)
        assert c0.cost_usd == c60.cost_usd

        # 60.1s must round up to 61s
        c61 = calc.glue.calculate_run_cost(glue_spec, 60.1)
        assert c61.billable_seconds == Decimal(61)
        assert c61.cost_usd > c60.cost_usd

    def test_finops_seed_workloads_roi_manifest_match(self):
        """Verify monthly dollar savings match the exact manifest figures for all 3 seed workloads."""
        loader = SeedDataLoader()
        evaluator = WorkloadEvaluator()

        # 1. Glue: customer360_elt ($11,246.40/mo waste)
        glue_manifest = loader.get_manifest("glue_customer360_elt")
        assert glue_manifest is not None
        glue_roi = evaluator.evaluate_glue_customer360_elt()
        expected_glue = Decimal(str(glue_manifest.optimized_metrics.monthly_savings_usd))
        assert glue_roi.monthly_savings_usd == expected_glue
        assert glue_roi.monthly_savings_usd == Decimal("11246.40")

        # 2. EMR: clickstream_attribution ($303.64/mo waste)
        emr_manifest = loader.get_manifest("emr_clickstream_attribution")
        assert emr_manifest is not None
        emr_roi = evaluator.evaluate_emr_clickstream_attribution()
        expected_emr = Decimal(str(emr_manifest.optimized_metrics.monthly_savings_usd))
        assert emr_roi.monthly_savings_usd == expected_emr
        assert emr_roi.monthly_savings_usd == Decimal("303.64")

        # 3. Databricks: financial_ledger_sync ($5,829.60/mo waste)
        db_manifest = loader.get_manifest("databricks_financial_ledger_sync")
        assert db_manifest is not None
        db_roi = evaluator.evaluate_databricks_financial_ledger_sync()
        expected_db = Decimal(str(db_manifest.optimized_metrics.monthly_savings_usd))
        assert db_roi.monthly_savings_usd == expected_db
        assert db_roi.monthly_savings_usd == Decimal("5829.60")


# ============================================================================
# Section 3: FastMCP Tool Server Programmatic Invocation Tests
# ============================================================================


class TestFastMCPToolsEmpirical:
    """Empirically test programmatic tool dispatch and telemetry return across all FastMCP servers."""

    @pytest.mark.asyncio
    async def test_fastmcp_cost_explorer_endpoints_programmatic_invocation(self):
        """Call Cost Explorer tool endpoints via FastMCP protocol and check returned metrics."""
        # 1. get_top_offenders
        res_offenders = await ce_server.call_tool("get_top_offenders", {"limit": 3})
        items = [json.loads(c.text) for c in res_offenders[0]]
        assert len(items) == 3
        assert items[0]["workload_id"] == "glue_customer360_elt"
        assert items[0]["total_spend_usd"] == 11880.0
        assert items[1]["workload_id"] == "databricks_financial_ledger_sync"
        assert items[2]["workload_id"] == "emr_clickstream_attribution"

        # 2. get_cost_breakdown
        res_breakdown = await ce_server.call_tool(
            "get_cost_breakdown",
            {"workload_id": "glue_customer360_elt", "start_date": "2026-09-15", "end_date": "2026-10-15"},
        )
        bd_data = json.loads(res_breakdown[0][0].text)
        assert bd_data["workload_id"] == "glue_customer360_elt"
        assert bd_data["total_spend_usd"] == 11880.0
        assert len(bd_data["time_series"]) == 30

        # 3. get_cost_and_usage
        res_cu = await ce_server.call_tool(
            "get_cost_and_usage",
            {"start_date": "2026-10-01", "end_date": "2026-10-05", "granularity": "DAILY"},
        )
        cu_data = json.loads(res_cu[0][0].text)
        assert "ResultsByTime" in cu_data

        # 4. forecast_workload_spend
        res_fc = await ce_server.call_tool(
            "forecast_workload_spend",
            {"workload_id": "glue_customer360_elt", "forecast_days": 30},
        )
        fc_data = json.loads(res_fc[0][0].text)
        assert fc_data["workload_id"] == "glue_customer360_elt"
        assert fc_data["projected_savings_usd"] == 11246.40
        assert fc_data["waste_reduction_pct"] == 94.67

    @pytest.mark.asyncio
    async def test_fastmcp_cloudwatch_endpoints_programmatic_invocation(self):
        """Call CloudWatch tool endpoints via FastMCP protocol and check telemetry metrics."""
        # 1. get_job_telemetry
        res_telem = await cw_server.call_tool("get_job_telemetry", {"job_id": "glue_customer360_elt"})
        telem = json.loads(res_telem[0][0].text)
        assert telem["job_name"] == "glue_customer360_elt"
        assert telem["gc_metrics"]["gc_time_ratio"] == 0.28
        assert telem["gc_metrics"]["is_gc_thrashing"] is True

        # 2. extract_skew_metrics
        res_skew = await cw_server.call_tool("extract_skew_metrics", {"job_id": "databricks_financial_ledger_sync"})
        skew = json.loads(res_skew[0][0].text)
        assert skew["job_id"] == "databricks_financial_ledger_sync"
        assert skew["skew_factor"] == 15.2
        assert skew["is_severely_skewed"] is True
        assert skew["status"] == "EXTREME_SKEW"

        # 3. get_gc_and_idle_metrics
        res_gc = await cw_server.call_tool("get_gc_and_idle_metrics", {"job_id": "emr_clickstream_attribution"})
        gc_idle = json.loads(res_gc[0][0].text)
        assert gc_idle["job_id"] == "emr_clickstream_attribution"
        assert gc_idle["executor_idle_time"]["idle_percentage"] == 68.2
        assert gc_idle["status"] == "ANOMALY_DETECTED"

        # 4. scan_log_anomalies
        res_logs = await cw_server.call_tool("scan_log_anomalies", {"log_group": "/aws-glue/jobs/output"})
        logs = json.loads(res_logs[0][0].text)
        assert logs["log_group"] == "/aws-glue/jobs/output"
        assert len(logs["detected_patterns"]) >= 2
        assert "GC_THRASHING" in logs["detected_patterns"]

        # 5. get_metric_data_series
        res_series = await cw_server.call_tool(
            "get_metric_data_series",
            {
                "metric_names": ["CPUUtilization", "MemoryUtilization"],
                "namespace": "AWS/Glue",
                "dimensions": {"JobName": "glue_customer360_elt"},
                "start_time": "2026-10-14T00:00:00Z",
                "end_time": "2026-10-15T00:00:00Z",
            },
        )
        series_list = [json.loads(c.text) for c in res_series[0]]
        assert len(series_list) == 2
        assert series_list[0]["metric_name"] == "CPUUtilization"

    @pytest.mark.asyncio
    async def test_fastmcp_git_repo_endpoints_programmatic_invocation(self, tmp_path):
        """Call Git Repo tool endpoints via FastMCP protocol and verify artifact inspection and PR generation."""
        # Create a temporary local git repo structure
        test_file = tmp_path / "sample.py"
        test_file.write_text("print('hello world')\n", encoding="utf-8")

        # 1. inspect_artifact
        res_inspect = await git_server.call_tool(
            "inspect_artifact",
            {"repo": str(tmp_path), "path": "sample.py"},
        )
        inspect_data = json.loads(res_inspect[0][0].text)
        assert inspect_data["exists"] is True
        assert inspect_data["line_count"] == 1
        assert "print('hello world')" in inspect_data["content"]

        # 2. create_pull_request
        res_pr = await git_server.call_tool(
            "create_pull_request",
            {
                "repo": str(tmp_path),
                "title": "⚡ [Midas Touch] Optimize sample.py",
                "body": "PR description body",
                "branch": "finops/sample-optimization",
                "changes": {"sample.py": "# refactored\nprint('optimized')\n"},
            },
        )
        pr_data = json.loads(res_pr[0][0].text)
        assert pr_data["status"] in ("CREATED", "UPDATED")
        assert pr_data["branch"] == "finops/sample-optimization"

        # 3. check_existing_pr
        res_check = await git_server.call_tool(
            "check_existing_pr",
            {"repo": str(tmp_path), "branch": "finops/sample-optimization"},
        )
        check_data = json.loads(res_check[0][0].text)
        assert check_data["has_existing_pr"] is True
        assert check_data["status"] == "OPEN"
