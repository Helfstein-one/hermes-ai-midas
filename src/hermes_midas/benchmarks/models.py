"""Domain models for empirical efficiency benchmarks and real execution metrics."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkloadExecutionMetric(BaseModel):
    """Execution performance metric comparing unoptimized vs optimized code."""

    workload_name: str
    engine: str
    pattern_addressed: str
    baseline_duration_ms: float
    optimized_duration_ms: float
    speedup_factor: float
    time_reduction_pct: float
    baseline_memory_mb: float
    optimized_memory_mb: float
    memory_reduction_pct: float
    baseline_cpu_time_ms: float
    optimized_cpu_time_ms: float
    data_parity_verified: bool
    rows_processed: int
    iterations: int = 3
    details: dict[str, Any] = Field(default_factory=dict)


class EngineThroughputMetric(BaseModel):
    """Throughput and latency metrics for the Midas Static AST / SQL engine."""

    workloads_evaluated: int
    total_time_ms: float
    throughput_per_second: float
    latency_p50_ms: float
    latency_p95_ms: float
    ast_syntax_valid_pct: float = 100.0


class BenchmarkSuiteReport(BaseModel):
    """Consolidated benchmark suite report."""

    timestamp: str
    python_version: str
    platform: str
    workload_metrics: list[WorkloadExecutionMetric] = Field(default_factory=list)
    engine_metric: EngineThroughputMetric | None = None
    average_speedup: float = 0.0
    average_memory_savings_pct: float = 0.0
    summary: str = ""
