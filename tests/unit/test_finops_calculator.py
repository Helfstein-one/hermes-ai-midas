"""Unit and boundary tests for deterministic FinOps pricing calculator.

Tiers Covered:
- Tier 1: Feature Coverage (Glue DPU, EMR vCPU/RAM, Databricks DBU+EC2, Seed Workload ROI)
- Tier 2: Boundary & Corner Cases (60s Duration Floor, Ceiling Rounding, Zero Savings, Streaming Micro-batches)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hermes_midas.finops import (
    DatabricksCalculator,
    DatabricksResourceSpec,
    EmrResourceSpec,
    EmrServerlessCalculator,
    GluePricingCalculator,
    GlueResourceSpec,
    WorkloadEvaluator,
)
from hermes_midas.finops.calculator import compute_billable_seconds
from hermes_midas.finops.rates import GLUE_MINIMUM_BILLABLE_SECONDS

# ============================================================================
# Tier 1: Feature Unit Tests
# ============================================================================


@pytest.mark.tier1
def test_glue_pricing_calculator_standard_formula():
    """Tier 1: Verify exact AWS Glue standard DPU pricing ($0.44/DPU-hr)."""
    calc = GluePricingCalculator()
    # 10 G.2X workers = 20 DPU. Duration 2700s (45 min) = 0.75 hr.
    # Expected: 20 * 0.75 * 0.44 = $6.6000
    spec = GlueResourceSpec(worker_type="G.2X", num_workers=10)
    breakdown = calc.calculate_run_cost(spec, duration_seconds=2700)

    assert breakdown.hourly_rate_usd == Decimal("8.80")
    assert breakdown.cost_usd == Decimal("6.60")
    assert breakdown.engine == "glue"


@pytest.mark.tier1
def test_glue_pricing_calculator_flex_tier():
    """Tier 1: Verify AWS Glue Flex pricing ($0.29/DPU-hr)."""
    calc = GluePricingCalculator()
    # 5 G.1X workers = 5 DPU. Duration 3600s (1.0 hr).
    # Expected: 5 * 1.0 * 0.29 = $1.4500
    spec = GlueResourceSpec(worker_type="G.1X", num_workers=5, is_flex=True)
    breakdown = calc.calculate_run_cost(spec, duration_seconds=3600)

    assert breakdown.cost_usd == Decimal("1.45")


@pytest.mark.tier1
def test_emr_serverless_calculator_standard_formula():
    """Tier 1: Verify AWS EMR Serverless compute rates (vCPU $0.052624, RAM $0.0057785)."""
    calc = EmrServerlessCalculator()
    spec = EmrResourceSpec(
        driver_vcpu=Decimal("2"),
        driver_memory_gb=Decimal("8"),
        executor_count=4,
        executor_vcpu=Decimal("4"),
        executor_memory_gb=Decimal("16"),
    )
    breakdown = calc.calculate_run_cost(spec, duration_seconds=3600)

    assert breakdown.cost_usd == Decimal("1.363284")


@pytest.mark.tier1
def test_databricks_calculator_standard_formula():
    """Tier 1: Verify Databricks DBU + underlying EC2 rates."""
    calc = DatabricksCalculator()
    spec = DatabricksResourceSpec(node_type="i3.xlarge", num_workers=8, tier="jobs_enterprise")
    breakdown = calc.calculate_run_cost(spec, duration_seconds=5400)

    assert breakdown.hourly_rate_usd == Decimal("4.608")
    assert breakdown.cost_usd == Decimal("6.912")


@pytest.mark.tier1
def test_seed_workload_evaluator_glue_customer360_roi():
    """Tier 1: Verify exact dollar ROI for Glue customer360_elt ($11,246.40/mo savings)."""
    evaluator = WorkloadEvaluator()
    impact = evaluator.evaluate_glue_customer360_elt()

    assert impact.monthly_savings_usd == Decimal("11246.40")
    assert impact.waste_reduction_pct == Decimal("84.00")
    assert impact.annual_savings_usd == Decimal("134956.80")


@pytest.mark.tier1
def test_seed_workload_evaluator_emr_attribution_roi():
    """Tier 1: Verify exact dollar ROI for EMR attribution."""
    evaluator = WorkloadEvaluator()
    impact = evaluator.evaluate_emr_clickstream_attribution()

    assert impact.monthly_savings_usd == Decimal("303.64")
    assert impact.waste_reduction_pct == Decimal("89.52")


@pytest.mark.tier1
def test_seed_workload_evaluator_databricks_ledger_roi():
    """Tier 1: Verify exact dollar ROI for Databricks financial ledger."""
    evaluator = WorkloadEvaluator()
    impact = evaluator.evaluate_databricks_financial_ledger_sync()

    assert impact.monthly_savings_usd == Decimal("5829.60")
    assert impact.waste_reduction_pct == Decimal("88.00")


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================


@pytest.mark.tier2
def test_billable_seconds_enforces_60_second_floor():
    """Tier 2: Durations under 60 seconds are elevated to 60s minimum billing floor."""
    billable = compute_billable_seconds(12, GLUE_MINIMUM_BILLABLE_SECONDS)
    assert billable == Decimal("60")

    billable_zero = compute_billable_seconds(0, GLUE_MINIMUM_BILLABLE_SECONDS)
    assert billable_zero == Decimal("60")


@pytest.mark.tier2
def test_billable_seconds_ceiling_rounds_fractional_seconds():
    """Tier 2: Fractional seconds are rounded up per cloud provider billing spec."""
    billable = compute_billable_seconds(65.1, GLUE_MINIMUM_BILLABLE_SECONDS)
    assert billable == Decimal("66")


@pytest.mark.tier2
def test_zero_waste_reduction_produces_zero_savings():
    """Tier 2: Baseline equal to optimized results in exactly $0.00 savings and 0% waste."""
    calc = GluePricingCalculator()
    spec = GlueResourceSpec(worker_type="G.1X", num_workers=2)
    impact = calc.calculate_roi(
        baseline_spec=spec,
        baseline_duration_seconds=300,
        optimized_spec=spec,
        optimized_duration_seconds=300,
        runs_per_day=24,
    )
    assert impact.monthly_savings_usd == Decimal("0.00")
    assert impact.waste_reduction_pct == Decimal("0.00")


@pytest.mark.tier2
def test_high_frequency_microbatch_no_precision_drift():
    """Tier 2: Streaming micro-batches (8,640 runs/day = every 10s) compute without precision drift."""
    calc = GluePricingCalculator()
    spec = GlueResourceSpec(worker_type="G.1X", num_workers=2)
    impact = calc.calculate_roi(
        baseline_spec=spec,
        baseline_duration_seconds=60,
        optimized_spec=spec,
        optimized_duration_seconds=60,
        runs_per_day=8640,
        runs_per_month=Decimal("259200"),
    )
    # Output must be a pure Decimal with zero floating point representation noise
    assert isinstance(impact.monthly_savings_usd, Decimal)
    assert isinstance(impact.baseline_cost_usd, Decimal)


@pytest.mark.tier2
def test_unknown_databricks_instance_type_uses_safe_fallback():
    """Tier 2: Unknown instance type in Databricks spec falls back to safe default pricing."""
    calc = DatabricksCalculator()
    spec = DatabricksResourceSpec(node_type="custom.unknown.type", num_workers=4)
    breakdown = calc.calculate_run_cost(spec, duration_seconds=3600)
    assert breakdown.cost_usd > Decimal("0.00")
    assert breakdown.engine == "databricks"
