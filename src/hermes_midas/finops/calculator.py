"""Deterministic pricing calculator for AWS Glue, EMR Serverless, and Databricks."""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from hermes_midas.finops.models import (
    ComputePlatform,
    DatabricksResourceSpec,
    EmrResourceSpec,
    FinOpsImpact,
    GlueResourceSpec,
    RunCostBreakdown,
)
from hermes_midas.finops.rates import (
    DATABRICKS_DBU_RATES,
    DATABRICKS_INSTANCE_MAP,
    DAYS_PER_MONTH,
    EMR_FREE_STORAGE_GB_PER_WORKER,
    EMR_MINIMUM_BILLABLE_SECONDS,
    EMR_RAM_GB_HOURLY_RATE,
    EMR_STORAGE_GB_HOURLY_RATE,
    EMR_VCPU_HOURLY_RATE,
    GLUE_FLEX_DPU_HOURLY_RATE,
    GLUE_MINIMUM_BILLABLE_SECONDS,
    GLUE_STANDARD_DPU_HOURLY_RATE,
    MONTHS_PER_YEAR,
    SECONDS_PER_HOUR,
)


def compute_billable_seconds(raw_seconds: Decimal | float, minimum_floor: Decimal) -> Decimal:
    """Apply ceiling rounding and enforce the 60-second billing minimum."""
    sec = Decimal(str(raw_seconds))
    # Round up to whole second
    billable = Decimal(str(math.ceil(float(sec))))
    return max(minimum_floor, billable)


class GluePricingCalculator:
    """Calculates exact deterministic DPU-hour costs for AWS Glue jobs."""

    @staticmethod
    def calculate_run_cost(
        spec: GlueResourceSpec,
        duration_seconds: Decimal | float,
    ) -> RunCostBreakdown:
        billable_sec = compute_billable_seconds(duration_seconds, GLUE_MINIMUM_BILLABLE_SECONDS)
        rate_per_dpu_hr = GLUE_FLEX_DPU_HOURLY_RATE if spec.is_flex else GLUE_STANDARD_DPU_HOURLY_RATE
        total_dpu = spec.total_dpu

        hourly_rate = total_dpu * rate_per_dpu_hr
        run_cost = hourly_rate * (billable_sec / SECONDS_PER_HOUR)

        return RunCostBreakdown(
            engine=ComputePlatform.GLUE.value,
            duration_seconds=Decimal(str(duration_seconds)),
            billable_seconds=billable_sec,
            hourly_rate_usd=hourly_rate,
            cost_usd=run_cost,
            details={
                "total_dpu": str(total_dpu),
                "rate_per_dpu_hr": str(rate_per_dpu_hr),
                "is_flex": spec.is_flex,
                "worker_type": spec.worker_type,
                "num_workers": spec.num_workers,
            },
        )

    def calculate_roi(
        self,
        baseline_spec: GlueResourceSpec,
        baseline_duration_seconds: Decimal | float,
        optimized_spec: GlueResourceSpec,
        optimized_duration_seconds: Decimal | float,
        runs_per_day: Decimal | int = 24,
        runs_per_month: Decimal | int | None = None,
    ) -> FinOpsImpact:
        base_breakdown = self.calculate_run_cost(baseline_spec, baseline_duration_seconds)
        opt_breakdown = self.calculate_run_cost(optimized_spec, optimized_duration_seconds)

        d_runs_day = Decimal(str(runs_per_day))
        d_runs_month = Decimal(str(runs_per_month)) if runs_per_month is not None else d_runs_day * DAYS_PER_MONTH

        base_cost = base_breakdown.cost_usd
        opt_cost = opt_breakdown.cost_usd
        cost_savings_per_run = base_cost - opt_cost
        daily_savings = cost_savings_per_run * d_runs_day
        monthly_savings = cost_savings_per_run * d_runs_month
        annual_savings = monthly_savings * MONTHS_PER_YEAR

        base_dur = Decimal(str(baseline_duration_seconds))
        opt_dur = Decimal(str(optimized_duration_seconds))
        waste_reduction_pct = ((base_dur - opt_dur) / base_dur) * Decimal(100) if base_dur > 0 else Decimal(0)

        formula = (
            "C_Glue = Total_DPU * (T_billable / 3600) * Rate_DPU; "
            "Savings = (C_baseline - C_optimized) * Frequency"
        )

        return FinOpsImpact(
            engine=ComputePlatform.GLUE.value,
            baseline_cost_usd=base_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            optimized_cost_usd=opt_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            cost_savings_per_run_usd=cost_savings_per_run.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            daily_savings_usd=daily_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            monthly_savings_usd=monthly_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            annual_savings_usd=annual_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            waste_reduction_pct=waste_reduction_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            pricing_formula_applied=formula,
            runs_per_day=d_runs_day,
            runs_per_month=d_runs_month,
            details={
                "baseline": base_breakdown.to_dict(),
                "optimized": opt_breakdown.to_dict(),
            },
        )


class EmrServerlessCalculator:
    """Calculates exact deterministic vCPU-hr and GB-hr costs for AWS EMR Serverless."""

    @staticmethod
    def calculate_run_cost(
        spec: EmrResourceSpec,
        duration_seconds: Decimal | float,
        vcpu_rate: Decimal | None = None,
        ram_rate: Decimal | None = None,
    ) -> RunCostBreakdown:
        billable_sec = compute_billable_seconds(duration_seconds, EMR_MINIMUM_BILLABLE_SECONDS)
        rate_vcpu = vcpu_rate or EMR_VCPU_HOURLY_RATE
        rate_ram = ram_rate or EMR_RAM_GB_HOURLY_RATE

        total_vcpu = spec.total_vcpu
        total_ram = spec.total_memory_gb

        hourly_vcpu_cost = total_vcpu * rate_vcpu
        hourly_ram_cost = total_ram * rate_ram

        # Storage over 20 GB per worker
        extra_storage_per_worker = max(Decimal(0), spec.storage_gb_per_worker - EMR_FREE_STORAGE_GB_PER_WORKER)
        total_billable_storage = extra_storage_per_worker * Decimal(str(spec.executor_count + 1))
        hourly_storage_cost = total_billable_storage * EMR_STORAGE_GB_HOURLY_RATE

        total_hourly_rate = hourly_vcpu_cost + hourly_ram_cost + hourly_storage_cost
        run_cost = total_hourly_rate * (billable_sec / SECONDS_PER_HOUR)

        return RunCostBreakdown(
            engine=ComputePlatform.EMR_SERVERLESS.value,
            duration_seconds=Decimal(str(duration_seconds)),
            billable_seconds=billable_sec,
            hourly_rate_usd=total_hourly_rate,
            cost_usd=run_cost,
            details={
                "total_vcpu": str(total_vcpu),
                "total_ram_gb": str(total_ram),
                "hourly_vcpu_cost": str(hourly_vcpu_cost),
                "hourly_ram_cost": str(hourly_ram_cost),
                "hourly_storage_cost": str(hourly_storage_cost),
            },
        )

    def calculate_roi(
        self,
        baseline_spec: EmrResourceSpec,
        baseline_duration_seconds: Decimal | float,
        optimized_spec: EmrResourceSpec,
        optimized_duration_seconds: Decimal | float,
        runs_per_day: Decimal | int = 4,
        runs_per_month: Decimal | int | None = None,
        vcpu_rate: Decimal | None = None,
        ram_rate: Decimal | None = None,
    ) -> FinOpsImpact:
        base_breakdown = self.calculate_run_cost(baseline_spec, baseline_duration_seconds, vcpu_rate, ram_rate)
        opt_breakdown = self.calculate_run_cost(optimized_spec, optimized_duration_seconds, vcpu_rate, ram_rate)

        d_runs_day = Decimal(str(runs_per_day))
        d_runs_month = Decimal(str(runs_per_month)) if runs_per_month is not None else d_runs_day * DAYS_PER_MONTH

        base_cost = base_breakdown.cost_usd
        opt_cost = opt_breakdown.cost_usd
        cost_savings_per_run = base_cost - opt_cost
        daily_savings = cost_savings_per_run * d_runs_day
        monthly_savings = cost_savings_per_run * d_runs_month
        annual_savings = monthly_savings * MONTHS_PER_YEAR

        base_dur = Decimal(str(baseline_duration_seconds))
        opt_dur = Decimal(str(optimized_duration_seconds))
        waste_reduction_pct = ((base_dur - opt_dur) / base_dur) * Decimal(100) if base_dur > 0 else Decimal(0)

        formula = (
            "C_EMR = (vCPU * Rate_vCPU + RAM_GB * Rate_RAM) * (T_billable / 3600); "
            "Savings = (C_baseline - C_optimized) * Frequency"
        )

        return FinOpsImpact(
            engine=ComputePlatform.EMR_SERVERLESS.value,
            baseline_cost_usd=base_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            optimized_cost_usd=opt_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            cost_savings_per_run_usd=cost_savings_per_run.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            daily_savings_usd=daily_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            monthly_savings_usd=monthly_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            annual_savings_usd=annual_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            waste_reduction_pct=waste_reduction_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            pricing_formula_applied=formula,
            runs_per_day=d_runs_day,
            runs_per_month=d_runs_month,
            details={
                "baseline": base_breakdown.to_dict(),
                "optimized": opt_breakdown.to_dict(),
            },
        )


class DatabricksCalculator:
    """Calculates exact deterministic DBU and underlying EC2 instance costs for Databricks."""

    @staticmethod
    def calculate_run_cost(
        spec: DatabricksResourceSpec,
        duration_seconds: Decimal | float,
    ) -> RunCostBreakdown:
        billable_sec = compute_billable_seconds(duration_seconds, Decimal(60))
        inst_info = DATABRICKS_INSTANCE_MAP.get(
            spec.node_type.lower(),
            {"dbu": Decimal("1.00"), "ec2_hourly": Decimal("0.312")},
        )
        node_dbu = inst_info["dbu"]
        node_ec2_hourly = inst_info["ec2_hourly"]

        dbu_unit_rate = DATABRICKS_DBU_RATES.get(spec.tier.lower(), Decimal("0.20"))
        total_nodes = Decimal(str(spec.total_nodes))

        hourly_dbu_cost = total_nodes * node_dbu * dbu_unit_rate
        hourly_ec2_cost = total_nodes * node_ec2_hourly
        total_hourly_rate = hourly_dbu_cost + hourly_ec2_cost

        run_cost = total_hourly_rate * (billable_sec / SECONDS_PER_HOUR)

        return RunCostBreakdown(
            engine=ComputePlatform.DATABRICKS.value,
            duration_seconds=Decimal(str(duration_seconds)),
            billable_seconds=billable_sec,
            hourly_rate_usd=total_hourly_rate,
            cost_usd=run_cost,
            details={
                "total_nodes": spec.total_nodes,
                "node_type": spec.node_type,
                "tier": spec.tier,
                "hourly_dbu_cost": str(hourly_dbu_cost),
                "hourly_ec2_cost": str(hourly_ec2_cost),
            },
        )

    def calculate_roi(
        self,
        baseline_spec: DatabricksResourceSpec,
        baseline_duration_seconds: Decimal | float,
        optimized_spec: DatabricksResourceSpec,
        optimized_duration_seconds: Decimal | float,
        runs_per_day: Decimal | int = 1,
        runs_per_month: Decimal | int | None = None,
        quantize_per_run: bool = False,
    ) -> FinOpsImpact:
        base_breakdown = self.calculate_run_cost(baseline_spec, baseline_duration_seconds)
        opt_breakdown = self.calculate_run_cost(optimized_spec, optimized_duration_seconds)

        d_runs_day = Decimal(str(runs_per_day))
        d_runs_month = Decimal(str(runs_per_month)) if runs_per_month is not None else d_runs_day * DAYS_PER_MONTH

        base_cost = base_breakdown.cost_usd
        opt_cost = opt_breakdown.cost_usd
        if quantize_per_run:
            base_cost_quant = base_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            opt_cost_quant = opt_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            cost_savings_per_run = base_cost_quant - opt_cost_quant
        else:
            cost_savings_per_run = base_cost - opt_cost
        daily_savings = cost_savings_per_run * d_runs_day
        monthly_savings = cost_savings_per_run * d_runs_month
        annual_savings = monthly_savings * MONTHS_PER_YEAR

        base_dur = Decimal(str(baseline_duration_seconds))
        opt_dur = Decimal(str(optimized_duration_seconds))
        waste_reduction_pct = ((base_dur - opt_dur) / base_dur) * Decimal(100) if base_dur > 0 else Decimal(0)

        formula = (
            "C_Databricks = N_nodes * (DBU_node * Rate_DBU + Rate_EC2) * (T_billable / 3600); "
            "Savings = (C_baseline - C_optimized) * Frequency"
        )

        return FinOpsImpact(
            engine=ComputePlatform.DATABRICKS.value,
            baseline_cost_usd=base_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            optimized_cost_usd=opt_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            cost_savings_per_run_usd=cost_savings_per_run.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            daily_savings_usd=daily_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            monthly_savings_usd=monthly_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            annual_savings_usd=annual_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            waste_reduction_pct=waste_reduction_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            pricing_formula_applied=formula,
            runs_per_day=d_runs_day,
            runs_per_month=d_runs_month,
            details={
                "baseline": base_breakdown.to_dict(),
                "optimized": opt_breakdown.to_dict(),
            },
        )


class FinOpsCalculator:
    """Unified FinOps calculator facade across all supported data engineering engines."""

    def __init__(self) -> None:
        self.glue = GluePricingCalculator()
        self.emr = EmrServerlessCalculator()
        self.databricks = DatabricksCalculator()

    def calculate_job_roi(
        self,
        engine: str,
        baseline_duration_seconds: Decimal | float,
        optimized_duration_seconds: Decimal | float,
        baseline_spec: GlueResourceSpec | EmrResourceSpec | DatabricksResourceSpec | None = None,
        optimized_spec: GlueResourceSpec | EmrResourceSpec | DatabricksResourceSpec | None = None,
        runs_per_day: Decimal | int = 1,
        runs_per_month: Decimal | int | None = None,
    ) -> FinOpsImpact:
        eng_lower = engine.lower()
        if eng_lower == ComputePlatform.GLUE.value:
            b_spec = baseline_spec or GlueResourceSpec()
            o_spec = optimized_spec or GlueResourceSpec()
            return self.glue.calculate_roi(
                b_spec, baseline_duration_seconds, o_spec, optimized_duration_seconds, runs_per_day, runs_per_month
            )
        elif eng_lower == ComputePlatform.EMR_SERVERLESS.value or eng_lower == "emr":
            b_spec = baseline_spec or EmrResourceSpec()
            o_spec = optimized_spec or EmrResourceSpec()
            return self.emr.calculate_roi(
                b_spec, baseline_duration_seconds, o_spec, optimized_duration_seconds, runs_per_day, runs_per_month
            )
        elif eng_lower == ComputePlatform.DATABRICKS.value:
            b_spec = baseline_spec or DatabricksResourceSpec()
            o_spec = optimized_spec or DatabricksResourceSpec()
            return self.databricks.calculate_roi(
                b_spec, baseline_duration_seconds, o_spec, optimized_duration_seconds, runs_per_day, runs_per_month
            )
        else:
            raise ValueError(f"Unsupported compute engine: '{engine}'. Expected glue, emr_serverless, or databricks.")
