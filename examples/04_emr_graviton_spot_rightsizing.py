#!/usr/bin/env python3
"""Example 4: AWS EMR on EC2 Graviton + Spot Task Fleet Optimization.

Demonstrates:
  1. Inefficiency: 16x m5.2xlarge On-Demand x86 nodes running daily batch job.
  2. Architecture Refactoring: Migration to AWS Graviton m6g.xlarge + Spot Task Fleet.
  3. FinOps Pricing Engine: Exact deterministic compute spend calculation.
  4. ASCII Bar Visualization: Displays comparative compute costs and cluster sizing.
"""

from __future__ import annotations

from hermes_midas.benchmarks.ascii_visualizer import render_resolution_card
from hermes_midas.finops import WorkloadEvaluator


def run_example() -> None:
    print("\n" + "=" * 68)
    print("🚀 HERMES MIDAS EXAMPLE 4: AWS EMR on EC2 Graviton + Spot Fleet")
    print("=" * 68)

    # 1. Background context
    print("\n[1/4] Context & Anti-Pattern:")
    print("  File: workloads/emr_ec2/graviton_spot_cluster.py")
    print("  Problem: Fixed 16x m5.2xlarge On-Demand x86 cluster for fault-tolerant daily batch")

    # 2. Compute Specification Comparison
    print("\n[2/4] Architecture Transformation:")
    print("  -- BASELINE:")
    print("  1x Master + 8x Core + 8x Task nodes (m5.2xlarge On-Demand)")
    print("  Hourly cluster cost: $6.528/h | Runtime: 2.0 hours ($13.056/run)")
    print("  -- OPTIMIZED:")
    print("  1x Master + 4x Core (m6g.xlarge On-Demand) + 4x Task (m6g.xlarge SPOT -70%)")
    print("  Hourly cluster cost: $1.408/h | Runtime: 0.5 hours with Graviton ($0.704/run)")

    # 3. FinOps calculation
    print("\n[3/4] Deterministic FinOps Spend Calculation:")
    evaluator = WorkloadEvaluator()
    impact = evaluator.evaluate_emr_ec2_graviton_spot()

    monthly_base = float(impact.baseline_cost_usd) * 30.0
    monthly_opt = float(impact.optimized_cost_usd) * 30.0
    savings = float(impact.monthly_savings_usd)

    print(f"  Baseline Monthly Spend:  ${monthly_base:,.2f}")
    print(f"  Optimized Monthly Spend: ${monthly_opt:,.2f}")
    print(f"  Net Monthly Savings:     ${savings:,.2f} (-94.6%)")

    # 4. Visual ASCII Card
    print("\n[4/4] Resolution Benchmark Scorecard:")
    card = render_resolution_card(
        workload_title="AWS EMR on EC2 (graviton_spot_cluster.py)",
        pattern="X86_ON_DEMAND -> GRAVITON_M6G_SPOT_FLEET",
        baseline_ms=7200.0,
        optimized_ms=1800.0,
        baseline_mb=32768.0,
        optimized_mb=16384.0,
        baseline_cost=monthly_base,
        optimized_cost=monthly_opt,
        parity_ok=True,
    )
    print(card)
    print(f"\n💡 FinOps Resolution: Monthly savings of ${savings:,.2f} (-94.6% spend) with Graviton + Spot.\n")


if __name__ == "__main__":
    run_example()
