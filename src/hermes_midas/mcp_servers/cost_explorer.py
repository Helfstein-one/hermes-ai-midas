"""FastMCP Server: midas-cost-explorer.

Exposes FinOps tools for AWS Cost Explorer:
- get_top_offenders: Ranked list of highest spend workloads.
- get_cost_breakdown: Itemized day-by-day and month-by-month spend per workload.
- get_cost_and_usage: Standard multi-dimensional cost queries across date windows.
- forecast_workload_spend: Deterministic spend projections and ROI calculations.

Provides stdio/SSE FastMCP entry points and direct Python callable functions.
"""

from __future__ import annotations

from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from fastmcp import FastMCP

from hermes_midas.topology import MockCostExplorerClient

# Server instance
server = FastMCP("midas-cost-explorer")

# Global client holder
_client_instance: MockCostExplorerClient | None = None


def get_cost_explorer_client() -> MockCostExplorerClient:
    """Retrieve the active Cost Explorer client, defaulting to MockCostExplorerClient."""
    global _client_instance
    if _client_instance is None:
        _client_instance = MockCostExplorerClient()
    return _client_instance


def set_cost_explorer_client(client: Any) -> None:
    """Inject a custom or live Cost Explorer client."""
    global _client_instance
    _client_instance = client


@server.tool(
    name="get_top_offenders",
    description="Retrieve the highest compute spend workloads grouped by dimension over a lookback window.",
)
def get_top_offenders(
    limit: int = 10,
    dimension: str = "WORKLOAD",
    lookback_days: int = 30,
    service_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Query top compute spend offenders sorted descending by cost.

    Args:
        limit: Max number of workloads to return (default: 10).
        dimension: Grouping dimension (e.g. WORKLOAD, JobName, Service, Engine).
        lookback_days: Number of days to aggregate spend (default: 30).
        service_filter: Optional filter by service or engine name.

    Returns:
        List of ranked workload spend dictionaries.
    """
    client = get_cost_explorer_client()
    tag_key = "JobName" if dimension.upper() in ("WORKLOAD", "JOBNAME", "JOB_NAME") else dimension
    return client.get_top_offenders(
        lookback_days=lookback_days,
        top_n=limit,
        tag_key=tag_key,
        service_filter=service_filter,
    )


@server.tool(
    name="get_cost_breakdown",
    description="Extract itemized day-by-day cost and usage metrics for a specific workload.",
)
def get_cost_breakdown(
    workload_id: str,
    start_date: str = "2026-09-15",
    end_date: str = "2026-10-15",
    granularity: str = "DAILY",
    group_by: str = "USAGE_TYPE",
) -> dict[str, Any]:
    """Retrieve itemized time-series cost points for a specific workload.

    Args:
        workload_id: Unique workload identifier (e.g. glue_customer360_elt).
        start_date: Start date in YYYY-MM-DD format (default: 2026-09-15).
        end_date: End date in YYYY-MM-DD format (default: 2026-10-15).
        granularity: DAILY or MONTHLY (default: DAILY).
        group_by: Dimension grouping (default: USAGE_TYPE).

    Returns:
        Cost breakdown dictionary with itemized time series.
    """
    client = get_cost_explorer_client()
    return client.get_cost_breakdown(
        workload_id=workload_id,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        group_by=group_by,
    )


@server.tool(
    name="get_cost_and_usage",
    description="Query itemized cost and usage across date ranges matching AWS Cost Explorer schema.",
)
def get_cost_and_usage(
    start_date: str,
    end_date: str,
    granularity: str = "DAILY",
    metrics: list[str] | None = None,
    group_by: list[dict[str, str]] | None = None,
    filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute standard multi-dimensional cost query.

    Args:
        start_date: Query period start date (YYYY-MM-DD).
        end_date: Query period end date (YYYY-MM-DD).
        granularity: DAILY or MONTHLY.
        metrics: List of metrics (e.g. UnblendedCost, UsageQuantity).
        group_by: Grouping keys list.
        filter: Filter expression map.

    Returns:
        ResultsByTime structure matching AWS Cost Explorer API.
    """
    client = get_cost_explorer_client()
    time_period = {"Start": start_date, "End": end_date}
    return client.get_cost_and_usage(
        time_period=time_period,
        granularity=granularity,
        filter=filter,
        metrics=metrics,
        group_by=group_by,
    )


@server.tool(
    name="forecast_workload_spend",
    description="Compute deterministic baseline vs optimized spend forecast and ROI.",
)
def forecast_workload_spend(
    workload_id: str,
    forecast_days: int = 30,
    reduction_percentage: float = 0.0,
) -> dict[str, Any]:
    """Compute projected spend, total dollar reduction, and ROI percentage.

    Args:
        workload_id: Workload identifier.
        forecast_days: Horizon in days (30, 60, 90).
        reduction_percentage: Expected waste reduction pct (0.0 uses manifest default).

    Returns:
        Projected spend and savings dictionary.
    """
    client = get_cost_explorer_client()
    return client.forecast_workload_spend(
        workload_id=workload_id,
        forecast_days=forecast_days,
        reduction_percentage=reduction_percentage,
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
