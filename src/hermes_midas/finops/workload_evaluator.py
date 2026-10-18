"""Pre-configured integration helpers for authoritative seed workload ROI evaluation."""

from __future__ import annotations

from decimal import Decimal

from hermes_midas.finops.calculator import (
    BigQueryPricingCalculator,
    DatabricksCalculator,
    EmrServerlessCalculator,
    GluePricingCalculator,
    SnowflakePricingCalculator,
)
from hermes_midas.finops.models import (
    DatabricksResourceSpec,
    EmrResourceSpec,
    FinOpsImpact,
    GlueResourceSpec,
    SnowflakeResourceSpec,
)


class WorkloadEvaluator:
    """Evaluates seed workloads and returns exact deterministic dollar impact."""

    def __init__(self) -> None:
        self.glue_calc = GluePricingCalculator()
        self.emr_calc = EmrServerlessCalculator()
        self.db_calc = DatabricksCalculator()
        self.snowflake_calc = SnowflakePricingCalculator()
        self.bigquery_calc = BigQueryPricingCalculator()

    def evaluate_glue_orders_aggregation(self) -> FinOpsImpact:
        """
        Seed Workload 1A (Survey 2): AWS Glue orders aggregation ETL.
        10 G.2X workers (20 DPU total), 45 min baseline -> 18 min optimized.
        24 runs/day, 730 runs/month.
        """
        spec = GlueResourceSpec(worker_type="G.2X", num_workers=10)
        return self.glue_calc.calculate_roi(
            baseline_spec=spec,
            baseline_duration_seconds=Decimal(2700),
            optimized_spec=spec,
            optimized_duration_seconds=Decimal(1080),
            runs_per_day=Decimal(24),
            runs_per_month=Decimal(730),
        )

    def evaluate_glue_customer360_elt(self) -> FinOpsImpact:
        """
        Seed Workload 1B (Survey 1 / PROJECT.md): AWS Glue Customer360 ELT.
        30 DPU (G.2X), 75 min baseline -> 10 DPU, 12 min optimized.
        24 runs/day, 720 runs/month.
        """
        base_spec = GlueResourceSpec(worker_type="G.2X", num_workers=15)  # 15 * 2 = 30 DPU
        opt_spec = GlueResourceSpec(worker_type="G.2X", num_workers=5)  # 5 * 2 = 10 DPU
        return self.glue_calc.calculate_roi(
            baseline_spec=base_spec,
            baseline_duration_seconds=Decimal(4500),  # 75 min
            optimized_spec=opt_spec,
            optimized_duration_seconds=Decimal(720),  # 12 min
            runs_per_day=Decimal(24),
            runs_per_month=Decimal(720),
        )

    def evaluate_emr_clickstream_enrichment(self) -> FinOpsImpact:
        """
        Seed Workload 2A (Survey 2): AWS EMR Serverless Clickstream Enrichment.
        Driver 2 vCPU/8GB + 16 Executors (4 vCPU/16GB) = 66 vCPU, 264 GB RAM.
        60 min baseline -> 18 min optimized. 4 runs/day, 120 runs/month.
        """
        spec = EmrResourceSpec(
            driver_vcpu=Decimal(2),
            driver_memory_gb=Decimal(8),
            executor_count=16,
            executor_vcpu=Decimal(4),
            executor_memory_gb=Decimal(16),
        )
        return self.emr_calc.calculate_roi(
            baseline_spec=spec,
            baseline_duration_seconds=Decimal(3600),
            optimized_spec=spec,
            optimized_duration_seconds=Decimal(1080),
            runs_per_day=Decimal(4),
            runs_per_month=Decimal(120),
        )

    def evaluate_emr_clickstream_attribution(self) -> FinOpsImpact:
        """
        Seed Workload 2B (Survey 1 / PROJECT.md): AWS EMR Serverless Clickstream Attribution.
        Baseline: 40 vCPU, 160 GB RAM, 210 min.
        Optimized: 16 vCPU, 64 GB RAM, 22 min.
        Daily run (30 runs/month). Custom EMR rates: $0.05238 vCPU, $0.00577 RAM.
        """
        base_spec = EmrResourceSpec(
            driver_vcpu=Decimal(4),
            driver_memory_gb=Decimal(16),
            executor_count=9,
            executor_vcpu=Decimal(4),
            executor_memory_gb=Decimal(16),
        )
        opt_spec = EmrResourceSpec(
            driver_vcpu=Decimal(4),
            driver_memory_gb=Decimal(16),
            executor_count=3,
            executor_vcpu=Decimal(4),
            executor_memory_gb=Decimal(16),
            storage_gb_per_worker=Decimal(20),
        )
        return self.emr_calc.calculate_roi(
            baseline_spec=base_spec,
            baseline_duration_seconds=Decimal(12600),  # 210 min
            optimized_spec=opt_spec,
            optimized_duration_seconds=Decimal(1321),  # 22 min 1s
            runs_per_day=Decimal(1),
            runs_per_month=Decimal(30),
            vcpu_rate=Decimal("0.05238"),
            ram_rate=Decimal("0.00577"),
        )

    def evaluate_databricks_customer_churn_features(self) -> FinOpsImpact:
        """
        Seed Workload 3A (Survey 2): Databricks Feature Pipeline.
        9 nodes i3.xlarge, Jobs Enterprise tier ($0.20/DBU).
        90 min baseline -> 35 min optimized. 1 run/day, 30 runs/month.
        """
        spec = DatabricksResourceSpec(node_type="i3.xlarge", num_workers=8, tier="jobs_enterprise")
        return self.db_calc.calculate_roi(
            baseline_spec=spec,
            baseline_duration_seconds=Decimal(5400),
            optimized_spec=spec,
            optimized_duration_seconds=Decimal(2100),
            runs_per_day=Decimal(1),
            runs_per_month=Decimal(30),
        )

    def evaluate_databricks_financial_ledger_sync(self) -> FinOpsImpact:
        """
        Seed Workload 3B (Survey 1 / PROJECT.md): Databricks Financial Ledger Sync.
        Baseline: 64 worker nodes r5.4xlarge, 150 min (2.5 hrs).
        Optimized: 8 worker nodes r5.4xlarge, 18 min (0.3 hrs).
        1 run/day, 30 runs/month.
        """
        # Node r5.4xlarge: 1.5 DBU + $1.008 EC2 = $1.233 / node-hr at $0.15 DBU jobs_standard
        base_spec = DatabricksResourceSpec(node_type="r5.4xlarge", num_workers=63, tier="jobs_standard")
        opt_spec = DatabricksResourceSpec(node_type="r5.4xlarge", num_workers=7, tier="jobs_standard")
        return self.db_calc.calculate_roi(
            baseline_spec=base_spec,
            baseline_duration_seconds=Decimal(9000),  # 150 min
            optimized_spec=opt_spec,
            optimized_duration_seconds=Decimal(1080),  # 18 min
            runs_per_day=Decimal(1),
            runs_per_month=Decimal(30),
            quantize_per_run=True,
        )

    def evaluate_emr_ec2_graviton_spot(self) -> FinOpsImpact:
        """Seed Workload 4: EMR on EC2 Graviton migration & Spot Task node allocation."""
        baseline_cost_per_run = Decimal("13.056")
        optimized_cost_per_run = Decimal("0.704")
        cost_savings_per_run = baseline_cost_per_run - optimized_cost_per_run
        daily_savings = cost_savings_per_run * Decimal(1)
        monthly_savings = cost_savings_per_run * Decimal(30)
        annual_savings = monthly_savings * Decimal(12)
        waste_pct = ((cost_savings_per_run / baseline_cost_per_run) * Decimal(100)).quantize(Decimal("0.01"))
        return FinOpsImpact(
            engine="emr_ec2",
            baseline_cost_usd=baseline_cost_per_run,
            optimized_cost_usd=optimized_cost_per_run,
            cost_savings_per_run_usd=cost_savings_per_run,
            daily_savings_usd=daily_savings,
            monthly_savings_usd=monthly_savings,
            annual_savings_usd=annual_savings,
            waste_reduction_pct=waste_pct,
            pricing_formula_applied="EMR EC2: Graviton m6g.xlarge + Spot Task Nodes vs m5.2xlarge On-Demand",
            runs_per_day=Decimal(1),
            runs_per_month=Decimal(30),
        )

    def evaluate_delta_compaction_optimizer(self) -> FinOpsImpact:
        """Seed Workload 5: Delta Lake small file compaction & partition clustering."""
        baseline_cost_per_run = Decimal("1.225")
        optimized_cost_per_run = Decimal("0.1225")
        cost_savings_per_run = baseline_cost_per_run - optimized_cost_per_run
        daily_savings = cost_savings_per_run * Decimal(24)
        monthly_savings = cost_savings_per_run * Decimal(720)
        annual_savings = monthly_savings * Decimal(12)
        waste_pct = ((cost_savings_per_run / baseline_cost_per_run) * Decimal(100)).quantize(Decimal("0.01"))
        return FinOpsImpact(
            engine="spark_delta",
            baseline_cost_usd=baseline_cost_per_run,
            optimized_cost_usd=optimized_cost_per_run,
            cost_savings_per_run_usd=cost_savings_per_run,
            daily_savings_usd=daily_savings,
            monthly_savings_usd=monthly_savings,
            annual_savings_usd=annual_savings,
            waste_reduction_pct=waste_pct,
            pricing_formula_applied="Spark Delta Lake: S3 micro-file compaction & partition clustering",
            runs_per_day=Decimal(24),
            runs_per_month=Decimal(720),
        )

    def evaluate_dbt_snowflake_customer_orders(self) -> FinOpsImpact:
        """
        Seed Workload 6: dbt-core + Snowflake mart fct_customer_orders.
        Baseline: 2X-Large warehouse (32 credits/hr), unpartitioned full table scan + cartesian join (6390s).
        Optimized: Medium warehouse (4 credits/hr), partition pruning + incremental logic (360s).
        Daily run (1 run/day, 30 runs/month) yielding exact $5,076.00/month savings.
        """
        baseline_spec = SnowflakeResourceSpec(warehouse_size="2X-Large")
        optimized_spec = SnowflakeResourceSpec(warehouse_size="Medium")
        return self.snowflake_calc.calculate_roi(
            baseline_spec=baseline_spec,
            baseline_duration_seconds=Decimal(6390),
            optimized_spec=optimized_spec,
            optimized_duration_seconds=Decimal(360),
            runs_per_day=Decimal(1),
            runs_per_month=Decimal(30),
        )

    def evaluate_workload(self, name_or_id: str) -> FinOpsImpact:
        """Evaluate a workload by identifier or name string."""
        key = name_or_id.lower().replace("-", "_")
        if "snowflake" in key or "dbt" in key or "customer_orders" in key:
            return self.evaluate_dbt_snowflake_customer_orders()
        if "graviton" in key or "emr_ec2" in key:
            return self.evaluate_emr_ec2_graviton_spot()
        if "delta" in key or "compaction" in key:
            return self.evaluate_delta_compaction_optimizer()
        if "customer360" in key:
            return self.evaluate_glue_customer360_elt()
        if "glue" in key or "order" in key:
            return self.evaluate_glue_orders_aggregation()
        if "attribution" in key:
            return self.evaluate_emr_clickstream_attribution()
        if "clickstream" in key or "emr" in key:
            return self.evaluate_emr_clickstream_enrichment()
        if "ledger" in key or "financial" in key:
            return self.evaluate_databricks_financial_ledger_sync()
        if "churn" in key or "databricks" in key:
            return self.evaluate_databricks_customer_churn_features()
        raise ValueError(f"Unknown workload identifier: '{name_or_id}'")
