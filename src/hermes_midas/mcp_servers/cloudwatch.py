"""FastMCP Server: midas-cloudwatch.

Exposes telemetry and compute waste diagnostic tools:
- get_job_telemetry: Comprehensive runtime telemetry (heap, idle, skew, GC, spill).
- extract_skew_metrics: Data skew factor, task duration distribution, and straggler detection.
- get_gc_and_idle_metrics: JVM GC pause ratios and executor CPU idle percentages.
- scan_log_anomalies: Driver and executor log scanning for OOM, spill, and IPC SerDe bottlenecks.
- get_metric_data_series: Multi-metric time series arrays for charting and diagnostic validation.

Provides stdio/SSE FastMCP entry points and direct Python callable functions.
"""

from __future__ import annotations

from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from fastmcp import FastMCP

from hermes_midas.topology import MockCloudWatchClient

# Server instance
server = FastMCP("midas-cloudwatch")

# Global client holder
_client_instance: MockCloudWatchClient | None = None


def get_cloudwatch_client() -> MockCloudWatchClient:
    """Retrieve the active CloudWatch client, defaulting to MockCloudWatchClient."""
    global _client_instance
    if _client_instance is None:
        _client_instance = MockCloudWatchClient()
    return _client_instance


def set_cloudwatch_client(client: Any) -> None:
    """Inject a custom or live CloudWatch client."""
    global _client_instance
    _client_instance = client


@server.tool(
    name="get_job_telemetry",
    description="Extract compute waste indicators: heap, idle time, skew, GC, and spill metrics.",
)
def get_job_telemetry(
    job_id: str,
    engine: str = "auto",
    run_id: str | None = None,
    lookback_hours: int = 24,
) -> dict[str, Any]:
    """Extract full telemetry profile for an ELT pipeline job.

    Args:
        job_id: Pipeline job identifier (e.g. glue_customer360_elt).
        engine: Compute engine (glue, emr_serverless, databricks, or auto).
        run_id: Optional specific execution run identifier.
        lookback_hours: Lookback window in hours (default: 24).

    Returns:
        Structured telemetry metrics dictionary.
    """
    client = get_cloudwatch_client()
    return client.extract_pipeline_telemetry(
        job_name=job_id,
        run_id=run_id,
        lookback_hours=lookback_hours,
    )


@server.tool(
    name="extract_skew_metrics",
    description="Extract data skew factor, task duration distribution, and straggler detection for a workload.",
)
def extract_skew_metrics(job_id: str) -> dict[str, Any]:
    """Extract task execution skew metrics for a workload.

    Args:
        job_id: Pipeline job identifier.

    Returns:
        Skew factor and task distribution indicators.
    """
    client = get_cloudwatch_client()
    telemetry = client.extract_pipeline_telemetry(job_name=job_id)
    skew = telemetry.get("data_skew", {})
    return {
        "job_id": job_id,
        "skew_factor": skew.get("skew_factor", 1.0),
        "max_task_duration_seconds": skew.get("max_task_duration_seconds", 0),
        "median_task_duration_seconds": skew.get("median_task_duration_seconds", 0),
        "is_severely_skewed": skew.get("is_severely_skewed", False),
        "status": skew.get("status", "BALANCED"),
        "data_skew": skew,
    }


@server.tool(
    name="get_gc_and_idle_metrics",
    description="Extract JVM garbage collection overhead and executor idle percentages for a workload.",
)
def get_gc_and_idle_metrics(job_id: str) -> dict[str, Any]:
    """Extract GC time ratio and executor idle metrics for a workload.

    Args:
        job_id: Pipeline job identifier.

    Returns:
        Dictionary with GC overhead and idle metrics.
    """
    client = get_cloudwatch_client()
    telemetry = client.extract_pipeline_telemetry(job_name=job_id)
    gc = telemetry.get("gc_metrics", {})
    idle = telemetry.get("executor_idle_time", {})
    return {
        "job_id": job_id,
        "gc_metrics": gc,
        "executor_idle_time": idle,
        "gc_time_ratio": gc.get("gc_time_ratio", 0.0),
        "idle_percentage": idle.get("idle_percentage", 0.0),
        "is_gc_thrashing": gc.get("is_gc_thrashing", False),
        "status": "ANOMALY_DETECTED" if (gc.get("is_gc_thrashing") or idle.get("idle_percentage", 0) > 50) else "HEALTHY",
    }


@server.tool(
    name="scan_log_anomalies",
    description="Scan driver and executor log streams for Spark runtime failure patterns and warnings.",
)
def scan_log_anomalies(
    log_group: str,
    lookback_hours: int = 24,
    pattern_filter: str | None = None,
) -> dict[str, Any]:
    """Scan CloudWatch log streams for runtime anomalies (OOM, GC thrashing, disk spill).

    Args:
        log_group: CloudWatch log group path (e.g. /aws-glue/jobs/output).
        lookback_hours: Lookback window in hours.
        pattern_filter: Optional substring filter.

    Returns:
        Anomaly detection report with error samples.
    """
    client = get_cloudwatch_client()
    return client.scan_log_anomalies(
        log_group=log_group,
        lookback_hours=lookback_hours,
        pattern_filter=pattern_filter,
    )


@server.tool(
    name="get_metric_data_series",
    description="Extract multi-metric time series arrays for charting and diagnostic validation.",
)
def get_metric_data_series(
    metric_names: list[str],
    namespace: str,
    dimensions: dict[str, str],
    start_time: str,
    end_time: str,
) -> list[dict[str, Any]]:
    """Extract multi-metric time series.

    Args:
        metric_names: Metric names to query.
        namespace: CloudWatch namespace.
        dimensions: Dimension key-value pairs.
        start_time: ISO-8601 start timestamp.
        end_time: ISO-8601 end timestamp.

    Returns:
        List of metric series points.
    """
    client = get_cloudwatch_client()
    return client.get_metric_data_series(
        metric_names=metric_names,
        namespace=namespace,
        dimensions=dimensions,
        start_time=start_time,
        end_time=end_time,
    )


def run_stdio() -> None:
    """Run FastMCP server using Standard I/O transport."""
    server.run(transport="stdio")


def run_sse() -> None:
    """Run FastMCP server using Server-Sent Events (SSE) HTTP transport."""
    server.run(transport="sse")


if __name__ == "__main__":
    import sys
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport == "sse":
        run_sse()
    else:
        run_stdio()
