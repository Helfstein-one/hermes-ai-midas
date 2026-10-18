"""Command-line interface (CLI) for hermes-ai-midas."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hermes_midas.ast_analyzer import ASTAnalyzer
from hermes_midas.finops import (
    DatabricksResourceSpec,
    EmrResourceSpec,
    FinOpsCalculator,
    GlueResourceSpec,
)
from hermes_midas.orchestrator.cron_auditor import ScheduledCronAuditor
from hermes_midas.orchestrator.pipeline import optimize_workload

app = typer.Typer(
    name="hermes-midas",
    help="Autonomous FinOps & Data Engineering Optimization Agent powered by FastMCP.",
    no_args_is_help=True,
)
console = Console()


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host address."),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port number."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of worker processes."),
):
    """Launch the FastAPI Airflow Webhook trigger server."""
    import uvicorn

    console.print(f"[bold green]Starting Midas Trigger Server on {host}:{port}...[/bold green]")
    uvicorn.run("hermes_midas.orchestrator.webhook:app", host=host, port=port, workers=workers)


@app.command("serve-webhook")
def serve_webhook(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host address."),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port number."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of worker processes."),
):
    """Alias for 'serve' command."""
    serve(host=host, port=port, workers=workers)


@app.command("audit")
def audit(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository directory to scan."),
    threshold: float = typer.Option(20.0, "--threshold", "-t", help="Minimum monthly dollar savings threshold."),
    cron: str | None = typer.Option(None, "--cron", "-c", help="Cron expression for background scheduling."),
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run continuously in background daemon mode."),
    output_report: str | None = typer.Option(None, "--output-report", "-o", help="Save JSON audit report path."),
):
    """Run proactive Scheduled Cron Auditor over repository workloads."""
    auditor = ScheduledCronAuditor(min_savings_threshold=threshold)

    if daemon:
        cron_expr = cron or "0 2 * * *"
        console.print(f"[bold cyan]Starting Midas Auditor Daemon for {repo} on schedule '{cron_expr}'...[/bold cyan]")
        scheduler = auditor.start_scheduler(
            repo_dir=repo,
            cron_expr=cron_expr,
            callback=lambda r: console.print(
                f"[green]Audit tick complete: {r.offending_workloads_count} offenders found.[/green]"
            ),
        )
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()
            console.print("[yellow]Auditor daemon stopped.[/yellow]")
            return

    console.print(
        f"[bold]Scanning repository: [cyan]{repo}[/cyan] (Threshold: [green]${threshold:.2f}/mo[/green])...[/bold]"
    )
    report = auditor.scan_repository(repo)

    table = Table(title="🏆 Hermes Midas FinOps Audit Summary")
    table.add_column("Scanned", justify="right", style="cyan")
    table.add_column("Offenders", justify="right", style="magenta")
    table.add_column("PRs Created", justify="right", style="green")
    table.add_column("PRs Skipped", justify="right", style="yellow")
    table.add_column("Monthly Savings ($)", justify="right", style="bold green")
    table.add_column("Annual Savings ($)", justify="right", style="bold green")

    table.add_row(
        str(report.scanned_workloads_count),
        str(report.offending_workloads_count),
        str(report.prs_created),
        str(report.prs_skipped),
        f"${report.total_potential_monthly_savings:,.2f}",
        f"${report.total_potential_annual_savings:,.2f}",
    )
    console.print(table)

    if output_report:
        out_p = Path(output_report)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[dim]Report saved to {output_report}[/dim]")


@app.command("analyze")
def analyze(
    script: str = typer.Option(..., "--script", "-s", help="Path to PySpark script."),
    output_format: str = typer.Option("terminal", "--format", "-f", help="Output format: terminal | json | markdown."),
):
    """Statically analyze a single PySpark file for compute waste and anti-patterns."""
    script_p = Path(script)
    if not script_p.exists():
        console.print(f"[bold red]File not found: {script}[/bold red]")
        raise typer.Exit(code=1)

    source = script_p.read_text(encoding="utf-8")
    analyzer = ASTAnalyzer()
    res = analyzer.inspect(source, str(script_p))

    if output_format.lower() == "json":
        console.print(json.dumps(res.to_dict(), indent=2), soft_wrap=True)
        return

    if output_format.lower() == "markdown":
        console.print(f"# AST Analysis: `{script}`\n")
        console.print(f"- **Anti-patterns detected**: {res.anti_patterns_count}")
        for ap in res.anti_patterns:
            console.print(
                f"- **{ap.pattern_name}** ({ap.pattern_id}) at lines {ap.line_start}-{ap.line_end}: {ap.description}"
            )
        return

    # Terminal output
    table = Table(title=f"Static AST Analysis: {script_p.name}")
    table.add_column("Pattern ID", style="cyan")
    table.add_column("Lines", style="yellow")
    table.add_column("Severity", style="bold red")
    table.add_column("Description", style="white")

    for ap in res.anti_patterns:
        table.add_row(
            ap.pattern_id,
            f"{ap.line_start}-{ap.line_end}",
            ap.severity,
            ap.description,
        )
    console.print(table)
    console.print(f"Total Anti-Patterns: [bold red]{res.anti_patterns_count}[/bold red]")


@app.command("calculate")
def calculate(
    engine: str = typer.Option("glue", "--engine", "-e", help="Compute engine (glue | emr_serverless | databricks)."),
    duration_secs: float = typer.Option(3600.0, "--duration-secs", help="Job duration in seconds."),
    units: float = typer.Option(10.0, "--units", help="Workers / DPUs / Nodes allocated."),
):
    """Run deterministic FinOps pricing calculator for workload parameters."""
    from decimal import Decimal

    calc = FinOpsCalculator()
    eng = engine.lower()
    if eng == "glue":
        spec = GlueResourceSpec(worker_type="G.2X", num_workers=int(units))
        breakdown = calc.glue.calculate_run_cost(spec, Decimal(str(duration_secs)))
        console.print(
            Panel(
                f"[bold]AWS Glue Run Cost[/bold]\n"
                f"DPUs: {spec.total_dpu}\n"
                f"Billable Seconds: {breakdown.billable_seconds}\n"
                f"Hourly Rate: ${breakdown.hourly_rate_usd:,.4f}\n"
                f"Single Run Cost: [bold green]${breakdown.cost_usd:,.4f}[/bold green]",
                title="FinOps Calculator",
            )
        )
    elif eng in ("emr_serverless", "emr"):
        emr_spec = EmrResourceSpec(executor_count=int(units))
        breakdown = calc.emr.calculate_run_cost(emr_spec, Decimal(str(duration_secs)))
        console.print(
            Panel(
                f"[bold]AWS EMR Serverless Run Cost[/bold]\n"
                f"vCPU: {emr_spec.total_vcpu}, RAM: {emr_spec.total_memory_gb} GB\n"
                f"Billable Seconds: {breakdown.billable_seconds}\n"
                f"Hourly Rate: ${breakdown.hourly_rate_usd:,.4f}\n"
                f"Single Run Cost: [bold green]${breakdown.cost_usd:,.4f}[/bold green]",
                title="FinOps Calculator",
            )
        )
    elif eng == "databricks":
        db_spec = DatabricksResourceSpec(num_workers=int(units))
        breakdown = calc.databricks.calculate_run_cost(db_spec, Decimal(str(duration_secs)))
        console.print(
            Panel(
                f"[bold]Databricks Run Cost[/bold]\n"
                f"Nodes: {db_spec.total_nodes} ({db_spec.node_type})\n"
                f"Billable Seconds: {breakdown.billable_seconds}\n"
                f"Hourly Rate: ${breakdown.hourly_rate_usd:,.4f}\n"
                f"Single Run Cost: [bold green]${breakdown.cost_usd:,.4f}[/bold green]",
                title="FinOps Calculator",
            )
        )
    else:
        console.print(f"[bold red]Unsupported compute engine: {engine}[/bold red]")


@app.command("optimize")
def optimize(
    script: str = typer.Option(..., "--script", "-s", help="Path to PySpark script to optimize."),
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root directory."),
    engine: str | None = typer.Option(None, "--engine", "-e", help="Target engine override."),
    offline: bool = typer.Option(True, "--offline/--online", help="Force deterministic offline mode."),
):
    """Run end-to-end autonomous workload optimization pipeline."""
    console.print(f"[bold]Optimizing workload: [cyan]{script}[/cyan]...[/bold]")
    result = optimize_workload(
        script_path=script,
        repo_path=repo,
        engine=engine,
        offline_mode=offline,
    )

    table = Table(title="Midas Touch Pipeline Optimization Result")
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="bold")

    table.add_row("Workload", result.workload_name)
    table.add_row("Engine", result.engine)
    table.add_row("PR Action", f"[{'green' if result.pr_action == 'CREATED' else 'yellow'}]{result.pr_action}[/]")
    table.add_row("Fingerprint", result.fingerprint)
    table.add_row("Anti-Patterns", str(result.anti_patterns_count))
    table.add_row("Monthly Savings", f"${result.monthly_savings_usd:,.2f}")
    table.add_row("Waste Reduction", f"{result.waste_reduction_pct:.1f}%")
    if result.pr_url:
        table.add_row("PR URL", result.pr_url)
    console.print(table)


def main():
    """Main CLI entrypoint."""
    app()


if __name__ == "__main__":
    main()
