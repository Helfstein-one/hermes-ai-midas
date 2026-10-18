"""Mock CloudWatch client and telemetry generator.

Extracts compute waste indicators: heap memory, executor idle time,
data skew, GC thrashing, and disk spill metrics matching CloudWatch formats.
"""

from __future__ import annotations

import datetime
import math
import re
from typing import Any

from hermes_midas.topology.models import TelemetrySnapshot, WorkloadManifest


class MockCloudWatchClient:
    """In-memory mock CloudWatch Metrics and Logs client."""

    def __init__(self, manifests: list[WorkloadManifest] | None = None) -> None:
        self._telemetry_profiles: dict[str, dict[str, Any]] = {}
        self._log_streams: dict[str, list[dict[str, Any]]] = {}
        self._custom_metrics: dict[str, list[dict[str, Any]]] = {}

        if manifests:
            for m in manifests:
                self.register_manifest(m)
        else:
            self._load_default_seed_telemetry()

    def register_manifest(self, m: WorkloadManifest) -> None:
        """Register telemetry profile and log streams from a workload manifest."""
        t = m.telemetry
        if not t:
            return

        # Determine statuses
        heap_pct = round((t.peak_memory_used_mb / max(1, t.jvm_heap_memory_allocated_mb)) * 100.0, 1)
        heap_status = "CRITICAL" if heap_pct > 90.0 else ("WARNING" if heap_pct > 75.0 else "HEALTHY")

        idle_pct = t.executor_cpu_idle_pct
        idle_status = "SEVERE_WASTE" if idle_pct > 50.0 else ("MODERATE_WASTE" if idle_pct > 25.0 else "OPTIMAL")

        skew_factor = t.data_skew_factor
        skew_status = "EXTREME_SKEW" if skew_factor > 10.0 else ("MODERATE_SKEW" if skew_factor > 2.0 else "BALANCED")

        gc_ratio = t.gc_time_ratio
        gc_status = "GC_THRASHING" if gc_ratio > 0.20 else ("WARNING" if gc_ratio > 0.10 else "HEALTHY")

        spill_bytes = t.spill_to_disk_bytes
        spill_status = "MASSIVE_DISK_SPILL" if spill_bytes > 10 * 1024**3 else ("MODERATE_SPILL" if spill_bytes > 0 else "NO_SPILL")

        # Estimate wasted core hours
        total_exec_hours = round(float(m.baseline_metrics.duration_seconds) / 3600.0 * 64, 1)
        idle_exec_hours = round(total_exec_hours * (idle_pct / 100.0), 1)
        wasted_cores = round(idle_exec_hours * 16, 1)

        self._telemetry_profiles[m.workload_id] = {
            "job_name": m.job_name,
            "engine": m.engine,
            "run_id": f"run-{m.engine[:3]}-20261015-080000",
            "status": "COMPLETED_WITH_WARNINGS" if (idle_pct > 50 or gc_ratio > 0.2 or spill_bytes > 0) else "COMPLETED",
            "duration_seconds": m.baseline_metrics.duration_seconds,
            "heap_memory": {
                "max_allocated_mb": t.jvm_heap_memory_allocated_mb,
                "peak_used_mb": t.peak_memory_used_mb,
                "avg_used_mb": t.avg_memory_used_mb,
                "heap_utilization_pct": heap_pct,
                "status": heap_status,
            },
            "executor_idle_time": {
                "total_executor_hours": total_exec_hours,
                "idle_executor_hours": idle_exec_hours,
                "idle_percentage": idle_pct,
                "wasted_core_hours": wasted_cores,
                "status": idle_status,
            },
            "data_skew": {
                "skew_factor": skew_factor,
                "max_task_duration_seconds": t.max_task_duration_seconds or int(m.baseline_metrics.duration_seconds * 0.78),
                "median_task_duration_seconds": t.median_task_duration_seconds or int(m.baseline_metrics.duration_seconds * 0.02),
                "is_severely_skewed": skew_factor > 3.0,
                "status": skew_status,
            },
            "gc_metrics": {
                "gc_time_ratio": gc_ratio,
                "total_gc_pause_seconds": t.gc_pause_seconds_total,
                "full_gc_cycles": t.full_gc_cycles,
                "is_gc_thrashing": gc_ratio > 0.20,
                "status": gc_status,
            },
            "spill_metrics": {
                "spill_to_disk_bytes": t.spill_to_disk_bytes,
                "spill_to_memory_bytes": t.spill_to_memory_bytes,
                "status": spill_status,
            },
        }

        # Generate sample log streams for the workload
        log_group = f"/aws/{m.engine}/jobs/{m.job_name}"
        self._log_streams[log_group] = self._generate_log_events(m.workload_id, m.engine, t)

    def _load_default_seed_telemetry(self) -> None:
        """Load default telemetry snapshots matching survey specifications."""
        # 1. Glue customer360
        self._telemetry_profiles["glue_customer360_elt"] = {
            "job_name": "glue_customer360_elt",
            "engine": "glue",
            "run_id": "run-glue-20261015-080000",
            "status": "COMPLETED_WITH_WARNINGS",
            "duration_seconds": 4500,
            "heap_memory": {
                "max_allocated_mb": 28000,
                "peak_used_mb": 25200,
                "avg_used_mb": 14500,
                "heap_utilization_pct": 90.0,
                "status": "WARNING",
            },
            "executor_idle_time": {
                "total_executor_hours": 37.5,
                "idle_executor_hours": 6.9,
                "idle_percentage": 18.5,
                "wasted_core_hours": 55.2,
                "status": "OPTIMAL",
            },
            "data_skew": {
                "skew_factor": 1.15,
                "max_task_duration_seconds": 210,
                "median_task_duration_seconds": 182,
                "is_severely_skewed": False,
                "status": "BALANCED",
            },
            "gc_metrics": {
                "gc_time_ratio": 0.28,
                "total_gc_pause_seconds": 1260,
                "full_gc_cycles": 42,
                "is_gc_thrashing": True,
                "status": "GC_THRASHING",
            },
            "spill_metrics": {
                "spill_to_disk_bytes": 0,
                "spill_to_memory_bytes": 0,
                "status": "NO_SPILL",
            },
        }

        # 2. EMR clickstream
        self._telemetry_profiles["emr_clickstream_attribution"] = {
            "job_name": "emr_clickstream_attribution",
            "engine": "emr_serverless",
            "run_id": "run-emr-20261015-080000",
            "status": "COMPLETED_WITH_WARNINGS",
            "duration_seconds": 12600,
            "heap_memory": {
                "max_allocated_mb": 163840,
                "peak_used_mb": 112000,
                "avg_used_mb": 64000,
                "heap_utilization_pct": 68.4,
                "status": "HEALTHY",
            },
            "executor_idle_time": {
                "total_executor_hours": 140.0,
                "idle_executor_hours": 95.5,
                "idle_percentage": 68.2,
                "wasted_core_hours": 382.0,
                "status": "SEVERE_WASTE",
            },
            "data_skew": {
                "skew_factor": 8.4,
                "max_task_duration_seconds": 3200,
                "median_task_duration_seconds": 380,
                "is_severely_skewed": True,
                "status": "MODERATE_SKEW",
            },
            "gc_metrics": {
                "gc_time_ratio": 0.08,
                "total_gc_pause_seconds": 1008,
                "full_gc_cycles": 12,
                "is_gc_thrashing": False,
                "status": "HEALTHY",
            },
            "spill_metrics": {
                "spill_to_disk_bytes": 0,
                "spill_to_memory_bytes": 0,
                "status": "NO_SPILL",
            },
        }

        # 3. Databricks financial ledger
        self._telemetry_profiles["databricks_financial_ledger_sync"] = {
            "job_name": "databricks_financial_ledger_sync",
            "engine": "databricks",
            "run_id": "run-dbx-20261015-080000",
            "status": "COMPLETED_WITH_WARNINGS",
            "duration_seconds": 9000,
            "heap_memory": {
                "max_allocated_mb": 131072,
                "peak_used_mb": 128500,
                "avg_used_mb": 34200,
                "heap_utilization_pct": 98.0,
                "status": "CRITICAL",
            },
            "executor_idle_time": {
                "total_executor_hours": 160.0,
                "idle_executor_hours": 137.6,
                "idle_percentage": 86.4,
                "wasted_core_hours": 2201.6,
                "status": "SEVERE_WASTE",
            },
            "data_skew": {
                "skew_factor": 15.2,
                "max_task_duration_seconds": 7080,
                "median_task_duration_seconds": 192,
                "is_severely_skewed": True,
                "status": "EXTREME_SKEW",
            },
            "gc_metrics": {
                "gc_time_ratio": 0.44,
                "total_gc_pause_seconds": 3960,
                "full_gc_cycles": 184,
                "is_gc_thrashing": True,
                "status": "GC_THRASHING",
            },
            "spill_metrics": {
                "spill_to_disk_bytes": 88583700480,
                "spill_to_memory_bytes": 142857142857,
                "status": "MASSIVE_DISK_SPILL",
            },
        }

        # Populate sample logs for log scanning
        self._log_streams["/aws-glue/jobs/output"] = self._generate_log_events(
            "glue_customer360_elt", "glue", None
        )
        self._log_streams["/emr-serverless/jobs/clickstream_attribution"] = self._generate_log_events(
            "emr_clickstream_attribution", "emr_serverless", None
        )
        self._log_streams["/databricks/jobs/financial_ledger_sync"] = self._generate_log_events(
            "databricks_financial_ledger_sync", "databricks", None
        )

    def _generate_log_events(
        self, workload_id: str, engine: str, t: TelemetrySnapshot | None
    ) -> list[dict[str, Any]]:
        """Generate realistic log entries indicating specific runtime anomalies."""
        now = int(datetime.datetime.now(datetime.UTC).timestamp() * 1000)
        logs: list[dict[str, Any]] = [
            {"timestamp": now - 3600000, "message": f"INFO [Driver] Starting execution for {workload_id}"},
        ]

        if "glue" in workload_id:
            logs.extend([
                {"timestamp": now - 3000000, "message": "WARN [Executor-3] Java GC pause (2800ms) exceeded threshold; frequent full collections in progress"},
                {"timestamp": now - 2500000, "message": "WARN [PythonWorker] PySpark SerDe IPC socket buffer overflow; row-by-row UDF deserialization stalled"},
                {"timestamp": now - 1800000, "message": "INFO [Driver] Stage 3 finished: df.count() evaluated in 1240s"},
                {"timestamp": now - 900000, "message": "INFO [Driver] Stage 4 finished: df.show(10) evaluated in 890s"},
            ])
        elif "emr" in workload_id:
            logs.extend([
                {"timestamp": now - 3200000, "message": "WARN [TaskSetManager] Stage 2 contains 10,000 tasks generated by repartition(10000)"},
                {"timestamp": now - 2800000, "message": "WARN [BlockManager] Shuffle exchange wrote 450,971,566,080 bytes across SortMergeJoin"},
                {"timestamp": now - 2100000, "message": "WARN [ExecutorAllocationManager] Executors 68.2% idle waiting on network shuffle fetch"},
                {"timestamp": now - 1100000, "message": "WARN [S3AFileSystem] SlowDown: 503 Service Unavailable during PUT of 80KB partition"},
            ])
        elif "databricks" in workload_id:
            logs.extend([
                {"timestamp": now - 3400000, "message": "WARN [TaskSetManager] Extreme skew detected: Task 142 processed 90% of keys (tenant_id=SYSTEM_DEFAULT)"},
                {"timestamp": now - 3000000, "message": "WARN [MemoryStore] Will not store rdd_12_142 as bytes 88583700480 exceeds partition memory limit"},
                {"timestamp": now - 2600000, "message": "ERROR [UnsafeExternalSorter] Spilling 88583700480 bytes of data to disk on executor 7"},
                {"timestamp": now - 2000000, "message": "WARN [GarbageCollector] GC overhead limit exceeded warning: 184 full GC cycles executed"},
                {"timestamp": now - 800000, "message": "WARN [ClusterManager] 63 executor nodes idle for 7080s waiting for straggler Task 142"},
            ])

        logs.append({"timestamp": now - 100000, "message": f"INFO [Driver] Pipeline {workload_id} finished execution."})
        return logs

    def extract_pipeline_telemetry(
        self,
        job_name: str,
        run_id: str | None = None,
        lookback_hours: int = 24,
    ) -> dict[str, Any]:
        """Extract compute waste indicators: heap, idle time, skew, GC, and spill metrics."""
        # Search by exact job_name or substring match
        matched_profile = None
        for k, prof in self._telemetry_profiles.items():
            if prof["job_name"] == job_name or k == job_name:
                matched_profile = prof
                break
            if job_name in k or k in job_name:
                matched_profile = prof
                break

        if not matched_profile:
            # Generate default fallback profile
            matched_profile = {
                "job_name": job_name,
                "engine": "generic_spark",
                "run_id": run_id or f"run-gen-{int(datetime.datetime.now().timestamp())}",
                "status": "COMPLETED",
                "duration_seconds": 1800,
                "heap_memory": {
                    "max_allocated_mb": 32768,
                    "peak_used_mb": 16000,
                    "avg_used_mb": 8000,
                    "heap_utilization_pct": 48.8,
                    "status": "HEALTHY",
                },
                "executor_idle_time": {
                    "total_executor_hours": 10.0,
                    "idle_executor_hours": 1.0,
                    "idle_percentage": 10.0,
                    "wasted_core_hours": 8.0,
                    "status": "OPTIMAL",
                },
                "data_skew": {
                    "skew_factor": 1.0,
                    "max_task_duration_seconds": 60,
                    "median_task_duration_seconds": 58,
                    "is_severely_skewed": False,
                    "status": "BALANCED",
                },
                "gc_metrics": {
                    "gc_time_ratio": 0.04,
                    "total_gc_pause_seconds": 72,
                    "full_gc_cycles": 1,
                    "is_gc_thrashing": False,
                    "status": "HEALTHY",
                },
                "spill_metrics": {
                    "spill_to_disk_bytes": 0,
                    "spill_to_memory_bytes": 0,
                    "status": "NO_SPILL",
                },
            }

        return matched_profile

    def get_metric_data_series(
        self,
        metric_names: list[str],
        namespace: str,
        dimensions: dict[str, str],
        start_time: str,
        end_time: str,
    ) -> list[dict[str, Any]]:
        """Extract multi-metric time series arrays for charting and diagnostic validation."""
        start_dt = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = datetime.datetime.fromisoformat(end_time.replace("Z", "+00:00"))

        results: list[dict[str, Any]] = []
        for name in metric_names:
            timestamps: list[str] = []
            values: list[float] = []

            curr = start_dt
            step = datetime.timedelta(minutes=15)
            val_base = 50.0
            if "Idle" in name:
                val_base = 75.0
            elif "Heap" in name or "Memory" in name:
                val_base = 85.0
            elif "GC" in name:
                val_base = 25.0
            elif "Spill" in name:
                val_base = 120.0

            idx = 0
            while curr < end_dt:
                timestamps.append(curr.isoformat())
                # Add synthetic wave
                wave = math.sin(idx * 0.5) * 10.0
                values.append(round(max(0.0, val_base + wave), 2))
                curr += step
                idx += 1

            results.append({
                "metric_name": name,
                "namespace": namespace,
                "dimensions": dimensions,
                "unit": "Percent" if "Percent" in name or "Idle" in name else "Bytes",
                "timestamps": timestamps,
                "values": values,
            })

        return results

    def scan_log_anomalies(
        self,
        log_group: str,
        lookback_hours: int = 24,
        pattern_filter: str | None = None,
    ) -> dict[str, Any]:
        """Scan log streams for runtime anomalies (OOM, GC thrashing, disk spill)."""
        # Find logs for the log_group
        events: list[dict[str, Any]] = []
        for group_name, stream in self._log_streams.items():
            if log_group in group_name or group_name in log_group:
                events.extend(stream)

        if not events:
            # Fallback scan across all streams
            for stream in self._log_streams.values():
                events.extend(stream)

        # Anomaly pattern matchers
        patterns = {
            "OOM_OR_HEAP_EXHAUSTION": re.compile(r"OutOfMemoryError|GC overhead limit exceeded|MemoryStore", re.IGNORECASE),
            "DISK_SPILL": re.compile(r"Spill|Spilling|UnsafeExternalSorter", re.IGNORECASE),
            "GC_THRASHING": re.compile(r"GC pause|full collection|Full GC", re.IGNORECASE),
            "DATA_SKEW": re.compile(r"skew|straggler|processed 90% of keys", re.IGNORECASE),
            "MICRO_PARTITIONING_OR_THROTTLING": re.compile(r"SlowDown|503|10,000 tasks|repartition", re.IGNORECASE),
            "PYTHON_SERDE_BOTTLENECK": re.compile(r"SerDe|row-by-row UDF|PythonWorker", re.IGNORECASE),
        }

        detected_patterns: list[str] = []
        error_samples: list[str] = []

        for evt in events:
            msg = evt.get("message", "")
            if pattern_filter and pattern_filter.lower() not in msg.lower():
                continue

            for p_name, rx in patterns.items():
                if rx.search(msg):
                    if p_name not in detected_patterns:
                        detected_patterns.append(p_name)
                    if len(error_samples) < 10:
                        error_samples.append(msg)

        return {
            "log_group": log_group,
            "lookback_hours": lookback_hours,
            "total_events_scanned": len(events),
            "total_anomalies_found": len(error_samples),
            "detected_patterns": detected_patterns,
            "error_samples": error_samples,
        }

    def get_metric_data(
        self,
        MetricDataQueries: list[dict[str, Any]],
        StartTime: Any,
        EndTime: Any,
    ) -> dict[str, Any]:
        """Boto3-compatible get_metric_data implementation."""
        results: list[dict[str, Any]] = []
        for q in MetricDataQueries:
            q_id = q.get("Id", "m1")
            metric_stat = q.get("MetricStat", {})
            metric = metric_stat.get("Metric", {})
            metric_name = metric.get("MetricName", "ExecutorCpuIdle")

            val = 86.4 if "Idle" in metric_name else (15.2 if "Skew" in metric_name else 44.0)
            now = datetime.datetime.now(datetime.UTC)
            timestamps = [(now - datetime.timedelta(minutes=i * 5)).isoformat() for i in range(5)]
            values = [val for _ in range(5)]

            results.append({
                "Id": q_id,
                "Label": metric_name,
                "Timestamps": timestamps,
                "Values": values,
                "StatusCode": "Complete",
            })

        return {
            "MetricDataResults": results,
            "Messages": [],
        }

    def put_metric_data(self, Namespace: str, MetricData: list[dict[str, Any]]) -> dict[str, Any]:
        """Boto3-compatible put_metric_data implementation."""
        if Namespace not in self._custom_metrics:
            self._custom_metrics[Namespace] = []
        self._custom_metrics[Namespace].extend(MetricData)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def filter_log_events(
        self,
        logGroupName: str,
        filterPattern: str | None = None,
        startTime: int | None = None,
        endTime: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Boto3-compatible filter_log_events implementation."""
        events = self._log_streams.get(logGroupName, [])
        filtered: list[dict[str, Any]] = []
        for e in events:
            if startTime and e["timestamp"] < startTime:
                continue
            if endTime and e["timestamp"] > endTime:
                continue
            if filterPattern and filterPattern.lower() not in e["message"].lower():
                continue
            filtered.append(e)

        return {"events": filtered, "searchedLogStreams": []}
