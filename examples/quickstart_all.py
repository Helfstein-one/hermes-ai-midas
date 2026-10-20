#!/usr/bin/env python3
"""Run all 5 Hermes Midas FinOps optimization examples sequentially.

Executes:
  1. Snowflake SQL dbt Mart (Cartesian join -> Pruned join)
  2. AWS Glue 4.0 PySpark (Legacy UDF -> Native Catalyst)
  3. AWS EMR Serverless (Orphan actions -> Single pass DAG)
  4. AWS EMR on EC2 (x86 On-Demand -> Graviton + Spot)
  5. Databricks Delta Lake (Micro-files -> Coalesced compaction)

Outputs complete ASCII resolution cards and consolidated FinOps scoreboard.
"""

from __future__ import annotations

from hermes_midas.benchmarks.demo import MidasDemoRunner


def main() -> None:
    print("\n" + "=" * 68)
    print("👑 HERMES MIDAS: COMPLETE RESOLUTION & BENCHMARK TOUR")
    print("=" * 68)
    runner = MidasDemoRunner()
    runner.run_all(interactive=False)


if __name__ == "__main__":
    main()
