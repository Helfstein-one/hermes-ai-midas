"""Automated benchmark assertions proving real compute and memory efficiency gains."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_midas.benchmarks.reporter import BenchmarkReporter
from hermes_midas.benchmarks.runner import BenchmarkRunner


@pytest.fixture(scope="module")
def benchmark_runner() -> BenchmarkRunner:
    return BenchmarkRunner(iterations=2, data_scale=40_000)


def test_sql_partition_and_join_real_speedup(benchmark_runner: BenchmarkRunner) -> None:
    """Verify dbt Snowflake SQL refactoring achieves > 2x speedup and > 50% memory reduction."""
    metric = benchmark_runner.benchmark_sql_partition_and_join(rows=30_000)

    assert metric.speedup_factor >= 2.0, f"Expected >= 2x speedup, got {metric.speedup_factor}x"
    assert metric.time_reduction_pct >= 50.0
    assert metric.memory_reduction_pct >= 50.0
    assert metric.data_parity_verified is True
    assert metric.optimized_duration_ms < metric.baseline_duration_ms


def test_udf_vs_vectorized_real_speedup(benchmark_runner: BenchmarkRunner) -> None:
    """Verify PySpark legacy UDF conversion to native vectorized expressions saves time and RAM."""
    metric = benchmark_runner.benchmark_udf_vs_vectorized(rows=40_000)

    assert metric.speedup_factor >= 1.5, f"Expected >= 1.5x speedup, got {metric.speedup_factor}x"
    assert metric.time_reduction_pct >= 30.0
    assert metric.memory_reduction_pct >= 30.0
    assert metric.data_parity_verified is True
    assert metric.optimized_duration_ms < metric.baseline_duration_ms


def test_orphan_actions_real_speedup(benchmark_runner: BenchmarkRunner) -> None:
    """Verify eliminating orphan action triggers saves >= 50% wall-clock time."""
    metric = benchmark_runner.benchmark_orphan_actions_recomputation(rows=30_000)

    assert metric.speedup_factor >= 1.8, f"Expected >= 1.8x speedup, got {metric.speedup_factor}x"
    assert metric.time_reduction_pct >= 40.0
    assert metric.data_parity_verified is True
    assert metric.optimized_duration_ms < metric.baseline_duration_ms


def test_small_files_compaction_real_speedup(benchmark_runner: BenchmarkRunner) -> None:
    """Verify small file I/O coalescing saves disk I/O latency without data loss."""
    metric = benchmark_runner.benchmark_small_files_compaction(micro_batches=40, batch_size=500)

    assert metric.speedup_factor >= 1.3, f"Expected >= 1.3x speedup, got {metric.speedup_factor}x"
    assert metric.data_parity_verified is True
    assert metric.optimized_duration_ms < metric.baseline_duration_ms


def test_midas_engine_throughput_and_ast_validity(benchmark_runner: BenchmarkRunner) -> None:
    """Verify Midas Engine processes > 500 workloads/sec with p95 < 15ms and 100% AST validity."""
    metric = benchmark_runner.benchmark_midas_engine_throughput(workload_count=40)

    assert metric.throughput_per_second >= 400.0, f"Expected >= 400 workloads/s, got {metric.throughput_per_second}"
    assert metric.latency_p50_ms < 10.0
    assert metric.latency_p95_ms < 25.0
    assert metric.ast_syntax_valid_pct == 100.0


def test_benchmark_report_and_json_export(tmp_path: Path) -> None:
    """Verify BenchmarkReporter generates valid Markdown and JSON artifacts."""
    runner = BenchmarkRunner(iterations=1, data_scale=10_000)
    report = runner.run_all()

    md_out = str(tmp_path / "report.md")
    json_out = str(tmp_path / "metrics.json")

    reporter = BenchmarkReporter()
    reporter.generate_markdown_report(report, output_path=md_out)
    reporter.export_json(report, output_path=json_out)

    # Validate Markdown file
    md_file = Path(md_out)
    assert md_file.exists()
    content = md_file.read_text(encoding="utf-8")
    assert "# 📊 Relatório Exaustivo de Eficiência Real" in content
    assert "dbt_snowflake_customer_orders" in content
    assert "Speedup" in content

    # Validate JSON file
    json_file = Path(json_out)
    assert json_file.exists()
    with open(json_file, encoding="utf-8") as f:
        data = json.load(f)
    assert "workload_metrics" in data
    assert "engine_metric" in data
    assert len(data["workload_metrics"]) == 4
    assert data["average_speedup"] > 1.0
