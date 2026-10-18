"""Hermes Midas FastMCP Tooling Layer.

Exposes three FastMCP servers:
1. midas-cost-explorer: AWS Cost Explorer FinOps analysis and top offender discovery.
2. midas-cloudwatch: Telemetry extraction for heap, idle, skew, GC, and spill metrics.
3. midas-git-repo: Artifact inspection and automated Pull Request generation across local and remote git servers.

Provides both FastMCP server instances (stdio / SSE transports) and direct in-process
Python callable functions for orchestrator workflows.
"""

from __future__ import annotations

from hermes_midas.mcp_servers.cloudwatch import (
    extract_skew_metrics,
    get_cloudwatch_client,
    get_gc_and_idle_metrics,
    get_job_telemetry,
    get_metric_data_series,
    scan_log_anomalies,
    set_cloudwatch_client,
)
from hermes_midas.mcp_servers.cloudwatch import (
    run_sse as run_cloudwatch_sse,
)
from hermes_midas.mcp_servers.cloudwatch import (
    run_stdio as run_cloudwatch_stdio,
)
from hermes_midas.mcp_servers.cloudwatch import (
    server as cloudwatch_server,
)
from hermes_midas.mcp_servers.cost_explorer import (
    forecast_workload_spend,
    get_cost_and_usage,
    get_cost_breakdown,
    get_cost_explorer_client,
    get_top_offenders,
    set_cost_explorer_client,
)
from hermes_midas.mcp_servers.cost_explorer import (
    run_sse as run_cost_explorer_sse,
)
from hermes_midas.mcp_servers.cost_explorer import (
    run_stdio as run_cost_explorer_stdio,
)
from hermes_midas.mcp_servers.cost_explorer import (
    server as cost_explorer_server,
)
from hermes_midas.mcp_servers.git_providers import (
    GitProvider,
    LocalFilesystemGitProvider,
    RemoteRestGitProvider,
    get_git_provider,
)
from hermes_midas.mcp_servers.git_repo import (
    check_existing_pr,
    create_pull_request,
    format_midas_touch_pr,
    inspect_artifact,
)
from hermes_midas.mcp_servers.git_repo import (
    run_sse as run_git_repo_sse,
)
from hermes_midas.mcp_servers.git_repo import (
    run_stdio as run_git_repo_stdio,
)
from hermes_midas.mcp_servers.git_repo import (
    server as git_repo_server,
)

__all__ = [
    "GitProvider",
    "LocalFilesystemGitProvider",
    "RemoteRestGitProvider",
    "check_existing_pr",
    "cloudwatch_server",
    "cost_explorer_server",
    "create_pull_request",
    "extract_skew_metrics",
    "forecast_workload_spend",
    "format_midas_touch_pr",
    "get_cloudwatch_client",
    "get_cost_and_usage",
    "get_cost_breakdown",
    "get_cost_explorer_client",
    "get_gc_and_idle_metrics",
    "get_git_provider",
    "get_job_telemetry",
    "get_metric_data_series",
    "get_top_offenders",
    "git_repo_server",
    "inspect_artifact",
    "run_cloudwatch_sse",
    "run_cloudwatch_stdio",
    "run_cost_explorer_sse",
    "run_cost_explorer_stdio",
    "run_git_repo_sse",
    "run_git_repo_stdio",
    "scan_log_anomalies",
    "set_cloudwatch_client",
    "set_cost_explorer_client",
]
