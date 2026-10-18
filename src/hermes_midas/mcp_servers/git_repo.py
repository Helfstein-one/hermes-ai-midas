"""FastMCP Server: midas-git-repo.

Exposes Git repository tools for code inspection and refactoring Pull Requests:
- inspect_artifact: Fetch file content and metadata across local and remote git repositories.
- create_pull_request: Create a branch, commit refactored files, and open/update a Pull Request.
- check_existing_pr: PR deduplication check by workload ID or branch name.

Provides stdio/SSE FastMCP entry points and direct Python callable functions.
"""

from __future__ import annotations

from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from fastmcp import FastMCP

from hermes_midas.mcp_servers.git_providers import (
    get_git_provider,
)

# Server instance
server = FastMCP("midas-git-repo")


def format_midas_touch_pr(
    workload_name: str,
    current_spend_monthly: float,
    projected_spend_monthly: float,
    monthly_savings: float,
    savings_pct: float,
    anti_patterns_breakdown: list[dict[str, str]],
    code_diff_summary: list[str],
    current_spend_annual: float | None = None,
    projected_spend_annual: float | None = None,
) -> str:
    """Format standardized Midas Touch Pull Request Markdown body."""
    annual_current = current_spend_annual or round(current_spend_monthly * 12, 2)
    annual_projected = projected_spend_annual or round(projected_spend_monthly * 12, 2)

    rows = "\n".join(
        f"| **{p.get('category', 'Code Pattern')}** | {p.get('observation', '')} | {p.get('impact', '')} |"
        for p in anti_patterns_breakdown
    )
    if not rows:
        rows = "| **Code Pattern** | Static AST and Telemetry Optimizations | Deterministic waste elimination |"

    diff_lines = (
        "\n".join(f"- {d}" for d in code_diff_summary)
        if code_diff_summary
        else "- Validated via ast.parse and compile."
    )

    return f"""# ⚡ [Midas Touch] FinOps Optimization: {workload_name}

## 📊 Executive Financial Summary
- **Current Spend**: ${current_spend_monthly:,.2f}/month (${annual_current:,.2f}/year)
- **Projected Spend**: ${projected_spend_monthly:,.2f}/month (${annual_projected:,.2f}/year)
- **Deterministic Monthly Savings**: **${monthly_savings:,.2f}** ({savings_pct:.1f}% reduction)
- **Payback Period**: Immediate (0 days)

## 🔍 Detected Inefficiencies & Root Cause Analysis
| Category | Observation | Impact |
|---|---|---|
{rows}

## 🛠️ Automated Code & Infrastructure Patches
{diff_lines}

## 🧪 Verification & Rollback Plan
- Run local unit tests: `uv run pytest`
- Automated AST syntax and compilation validation verified.
"""


@server.tool(
    name="inspect_artifact",
    description="Inspect file content and metadata from local filesystem or remote git repository.",
)
def inspect_artifact(
    repo_path_or_url: str = "",
    file_path: str = "",
    ref: str = "main",
    repo: str | None = None,
    path: str | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    """Inspect file content from local or remote git repository.

    Args:
        repo_path_or_url: Repository filesystem path or remote URL.
        file_path: Relative path to target file.
        ref: Git reference (branch, tag, commit). Default: main.
        repo: Parameter alias for repo_path_or_url.
        path: Parameter alias for file_path.
        backend: Optional backend override ('local' or 'remote').

    Returns:
        Dictionary containing file content, line count, existence status, and SHA.
    """
    actual_repo = repo or repo_path_or_url or "."
    actual_path = path or file_path
    if not actual_path:
        raise ValueError("Target file path must be specified.")

    provider = get_git_provider(actual_repo, backend=backend)
    return provider.inspect_artifact(
        repo=actual_repo,
        file_path=actual_path,
        ref=ref,
    )


@server.tool(
    name="create_pull_request",
    description="Create a branch, commit refactored files, and open or update a refactoring Pull Request.",
)
def create_pull_request(
    repo: str = "",
    title: str = "",
    body: str = "",
    branch: str = "",
    base: str = "main",
    changes: dict[str, str] | None = None,
    repo_path_or_url: str | None = None,
    target_branch: str | None = None,
    base_branch: str | None = None,
    file_changes: list[dict[str, str]] | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    """Create or update a pull request with refactored files.

    Args:
        repo: Repository path or remote URL.
        title: PR title.
        body: Markdown PR description.
        branch: Head branch name to create/push.
        base: Target base branch (default: main).
        changes: Map of relative file paths to new content.
        repo_path_or_url: Parameter alias for repo.
        target_branch: Parameter alias for branch.
        base_branch: Parameter alias for base.
        file_changes: Alternative list format for changes [{'path': ..., 'content': ...}].
        backend: Optional backend override ('local' or 'remote').

    Returns:
        Pull Request metadata dictionary with pr_url and status.
    """
    actual_repo = repo or repo_path_or_url or "."
    actual_branch = branch or target_branch or "finops/midas-touch"
    actual_base = base or base_branch or "main"

    normalized_changes: dict[str, str] = {}
    if changes:
        normalized_changes.update(changes)
    if file_changes:
        for fc in file_changes:
            p = fc.get("path") or fc.get("file_path")
            c = fc.get("content", "")
            if p:
                normalized_changes[p] = c

    provider = get_git_provider(actual_repo, backend=backend)
    return provider.create_pull_request(
        repo=actual_repo,
        title=title,
        body=body,
        branch=actual_branch,
        base=actual_base,
        changes=normalized_changes,
    )


@server.tool(
    name="check_existing_pr",
    description="Check for existing open pull requests for workload deduplication.",
)
def check_existing_pr(
    repo: str,
    branch: str | None = None,
    workload_id: str | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    """Check if an open pull request already exists matching branch or workload.

    Args:
        repo: Repository path or URL.
        branch: Branch name to check.
        workload_id: Workload ID to check in title or body.
        backend: Optional backend override.

    Returns:
        Deduplication result dictionary.
    """
    provider = get_git_provider(repo, backend=backend)
    return provider.check_existing_pr(
        repo=repo,
        branch=branch,
        workload_id=workload_id,
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
