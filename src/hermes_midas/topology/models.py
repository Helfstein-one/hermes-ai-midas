"""Data models and serialization structures for platform topology and seed workloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ComputeSpec:
    """Compute specification for a workload."""

    worker_type: str | None = None
    number_of_workers: int | None = None
    dpu_per_worker: int | None = None
    total_dpu: int | None = None
    dpu_rate_usd_per_hour: float | None = None
    driver_vcpu: int | None = None
    driver_memory_gb: int | None = None
    executor_count: int | None = None
    executor_vcpu: int | None = None
    executor_memory_gb: int | None = None
    total_vcpu: int | None = None
    total_memory_gb: int | None = None
    vcpu_rate_usd_per_hour: float | None = None
    memory_rate_usd_per_gb_hour: float | None = None
    node_type: str | None = None
    node_count: int | None = None
    vcpu_per_node: int | None = None
    memory_gb_per_node: int | None = None
    dbu_per_node_hr: float | None = None
    dbu_rate_usd: float | None = None
    ec2_rate_usd_per_node_hr: float | None = None
    total_rate_usd_per_node_hr: float | None = None
    cluster_hourly_rate_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComputeSpec:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class BaselineMetrics:
    """Baseline runtime and cost performance before optimization."""

    duration_seconds: int
    cost_per_run_usd: float
    monthly_spend_usd: float
    duration_minutes: float | None = None
    duration_hours: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaselineMetrics:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


@dataclass
class OptimizedMetrics:
    """Optimized runtime and cost targets post-refactoring."""

    duration_seconds: int
    cost_per_run_usd: float
    monthly_spend_usd: float
    monthly_savings_usd: float
    waste_reduction_pct: float
    duration_minutes: float | None = None
    duration_hours: float | None = None
    target_worker_type: str | None = None
    target_number_of_workers: int | None = None
    target_total_dpu: int | None = None
    target_vcpu: int | None = None
    target_memory_gb: int | None = None
    target_node_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptimizedMetrics:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


@dataclass
class AntiPatternDefinition:
    """Documented code or infrastructure anti-pattern."""

    pattern_id: str
    category: str
    description: str
    target_actions: list[str] | None = None
    target_table: str | None = None
    skew_factor: float | None = None
    spill_to_disk_bytes: int | None = None
    idle_percentage: float | None = None
    wasted_core_hours: float | None = None
    recommended_replacement: str | None = None
    estimated_overhead_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AntiPatternDefinition:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


@dataclass
class TelemetrySnapshot:
    """Complete diagnostic telemetry metrics for a workload."""

    jvm_heap_memory_allocated_mb: int
    peak_memory_used_mb: int
    avg_memory_used_mb: int
    executor_cpu_idle_pct: float
    gc_time_ratio: float
    gc_pause_seconds_total: int
    full_gc_cycles: int
    data_skew_factor: float
    shuffle_total_bytes_written: int
    spill_to_disk_bytes: int
    spill_to_memory_bytes: int
    max_task_duration_seconds: int | None = None
    median_task_duration_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TelemetrySnapshot:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


@dataclass
class WorkloadManifest:
    """Root metadata schema for seed workloads."""

    workload_id: str
    job_name: str
    engine: str
    script_path: str
    schedule: str
    runs_per_day: int
    runs_per_month: int
    compute_spec: ComputeSpec
    baseline_metrics: BaselineMetrics
    optimized_metrics: OptimizedMetrics
    anti_patterns: list[AntiPatternDefinition] = field(default_factory=list)
    telemetry: TelemetrySnapshot | None = None
    glue_version: str | None = None
    spark_version: str | None = None
    runtime_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        res["compute_spec"] = self.compute_spec.to_dict()
        res["baseline_metrics"] = self.baseline_metrics.to_dict()
        res["optimized_metrics"] = self.optimized_metrics.to_dict()
        res["anti_patterns"] = [p.to_dict() for p in self.anti_patterns]
        if self.telemetry:
            res["telemetry"] = self.telemetry.to_dict()
        return {k: v for k, v in res.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkloadManifest:
        compute_spec = ComputeSpec.from_dict(data.get("compute_spec", {}))
        baseline_metrics = BaselineMetrics.from_dict(data.get("baseline_metrics", {}))
        optimized_metrics = OptimizedMetrics.from_dict(data.get("optimized_metrics", {}))
        anti_patterns = [AntiPatternDefinition.from_dict(p) for p in data.get("anti_patterns", [])]
        telemetry = (
            TelemetrySnapshot.from_dict(data["telemetry"]) if "telemetry" in data and data["telemetry"] else None
        )

        return cls(
            workload_id=data["workload_id"],
            job_name=data["job_name"],
            engine=data["engine"],
            script_path=data["script_path"],
            schedule=data["schedule"],
            runs_per_day=data["runs_per_day"],
            runs_per_month=data["runs_per_month"],
            compute_spec=compute_spec,
            baseline_metrics=baseline_metrics,
            optimized_metrics=optimized_metrics,
            anti_patterns=anti_patterns,
            telemetry=telemetry,
            glue_version=data.get("glue_version"),
            spark_version=data.get("spark_version"),
            runtime_version=data.get("runtime_version"),
        )


@dataclass
class TopOffenderItem:
    """Ranked high-spend workload offender."""

    rank: int
    workload_id: str
    service: str
    tag_key: str
    total_spend_usd: float
    daily_average_usd: float
    spend_percentage: float
    trend: str
    usage_unit: str
    total_units: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimeSeriesCostPoint:
    """Daily or monthly itemized cost data point."""

    date: str
    usage_type: str
    usage_quantity: float
    cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CostBreakdownResponse:
    """Detailed itemized cost breakdown for a workload."""

    workload_id: str
    start_date: str
    end_date: str
    granularity: str
    total_spend_usd: float
    currency: str
    time_series: list[TimeSeriesCostPoint]

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        res["time_series"] = [p.to_dict() for p in self.time_series]
        return res
