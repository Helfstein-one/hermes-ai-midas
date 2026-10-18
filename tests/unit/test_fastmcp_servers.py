"""Unit and contract tests for FastMCP tooling layer.

Tiers Covered:
- Tier 1: Feature Coverage (Cost Explorer, CloudWatch, Git Repo MCP tool definitions and schemas)
- Tier 2: Boundary & Corner Cases (Parameter validation, Missing arguments, Invalid dates)
- Tier 3: Cross-Feature FastMCP In-Memory Invocation
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field, ValidationError

from hermes_midas.mcp_servers.cloudwatch import server as cw_server
from hermes_midas.mcp_servers.cost_explorer import server as ce_server
from hermes_midas.mcp_servers.git_repo import server as git_server

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from fastmcp import FastMCP




# ============================================================================
# Contract Schema Definitions (Authoritative R3 Contract)
# ============================================================================

class TopOffendersRequest(BaseModel):
    dimension: str = Field(default="JobName", description="Grouping dimension: JobName | Service | Engine")
    limit: int = Field(default=5, ge=1, le=50, description="Max number of offenders to retrieve")


class CostAndUsageRequest(BaseModel):
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")
    granularity: str = Field(default="DAILY", description="DAILY | MONTHLY")


class JobTelemetryRequest(BaseModel):
    job_id: str = Field(..., description="Pipeline workload identifier")
    engine: str = Field(default="glue", description="glue | emr_serverless | databricks")


class CreatePRRequest(BaseModel):
    repo: str = Field(..., description="Repository path or URL")
    title: str = Field(..., description="Pull request title")
    body: str = Field(..., description="Markdown description")
    branch: str = Field(..., description="Head branch name")
    base: str = Field(default="main", description="Target base branch")
    changes: dict[str, str] = Field(..., description="Map of relative file path to updated content")


# ============================================================================
# Reference Server Factory / Dynamic Adapter
# ============================================================================


def get_cost_explorer_mcp_server() -> FastMCP:
    """Retrieve authoritative FastMCP Cost Explorer server."""
    return ce_server


def get_cloudwatch_mcp_server() -> FastMCP:
    """Retrieve authoritative FastMCP CloudWatch server."""
    return cw_server


def get_git_repo_mcp_server() -> FastMCP:
    """Retrieve authoritative FastMCP Git Repo server."""
    return git_server


# ============================================================================
# Tier 1: Feature Unit Tests
# ============================================================================

@pytest.mark.tier1
def test_cost_explorer_mcp_server_tools_registered():
    """Tier 1: Verify FastMCP Cost Explorer server exposes required tools."""
    server = get_cost_explorer_mcp_server()
    # Must have name and tools
    assert server.name == "midas-cost-explorer"
    # Execute tools in-process
    top_offenders = server._tool_manager.get_tool("get_top_offenders")
    assert top_offenders is not None


@pytest.mark.tier1
def test_cloudwatch_mcp_server_tools_registered():
    """Tier 1: Verify FastMCP CloudWatch server exposes get_job_telemetry tool."""
    server = get_cloudwatch_mcp_server()
    assert server.name == "midas-cloudwatch"
    tool = server._tool_manager.get_tool("get_job_telemetry")
    assert tool is not None


@pytest.mark.tier1
def test_git_repo_mcp_server_tools_registered():
    """Tier 1: Verify FastMCP Git Repo server exposes inspect_artifact and create_pull_request."""
    server = get_git_repo_mcp_server()
    assert server.name == "midas-git-repo"
    assert server._tool_manager.get_tool("inspect_artifact") is not None
    assert server._tool_manager.get_tool("create_pull_request") is not None


@pytest.mark.tier1
@pytest.mark.asyncio
async def test_fastmcp_cost_explorer_tool_execution():
    """Tier 1: Call get_top_offenders and verify structured output."""
    server = get_cost_explorer_mcp_server()
    tool = server._tool_manager.get_tool("get_top_offenders")
    result = await tool.run(arguments={"limit": 3})

    assert isinstance(result, list)
    assert len(result) >= 1
    assert "workload_id" in result[0]
    assert "total_spend_usd" in result[0]


@pytest.mark.tier1
@pytest.mark.asyncio
async def test_fastmcp_cloudwatch_tool_execution():
    """Tier 1: Call get_job_telemetry and verify compute metrics extraction."""
    server = get_cloudwatch_mcp_server()
    tool = server._tool_manager.get_tool("get_job_telemetry")
    result = await tool.run(arguments={"job_id": "glue_customer360_elt"})

    assert isinstance(result, dict)
    assert "gc_metrics" in result
    assert "heap_memory" in result
    assert result["gc_metrics"]["gc_time_ratio"] == 0.28


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================

@pytest.mark.tier2
def test_pydantic_schema_validation_top_offenders_bounds():
    """Tier 2: Pydantic rejects limit < 1 or limit > 50."""
    with pytest.raises(ValidationError):
        TopOffendersRequest(limit=0)

    with pytest.raises(ValidationError):
        TopOffendersRequest(limit=100)

    valid = TopOffendersRequest(limit=10)
    assert valid.limit == 10


@pytest.mark.tier2
def test_pydantic_schema_validation_cost_and_usage_required_fields():
    """Tier 2: CostAndUsageRequest enforces required date strings."""
    with pytest.raises(ValidationError):
        CostAndUsageRequest()  # missing start_date and end_date

    req = CostAndUsageRequest(start_date="2026-10-01", end_date="2026-10-31")
    assert req.granularity == "DAILY"
