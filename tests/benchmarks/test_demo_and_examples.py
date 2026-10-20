"""Automated test suite for Midas interactive demo runner, ASCII visualizer, and example scripts."""

from __future__ import annotations

from typer.testing import CliRunner

from hermes_midas.benchmarks.ascii_visualizer import make_bar, render_metric_bar, render_resolution_card
from hermes_midas.benchmarks.demo import MidasDemoRunner
from hermes_midas.cli import app


def test_ascii_make_bar_proportions() -> None:
    assert make_bar(0, 100, width=10) == ""
    assert make_bar(50, 100, width=10) == "█████"
    assert make_bar(100, 100, width=10) == "██████████"
    assert make_bar(150, 100, width=10) == "██████████"


def test_ascii_render_metric_bar() -> None:
    # Latency speedup
    out_latency = render_metric_bar(
        "Execution Time",
        baseline=20.0,
        optimized=2.0,
        unit="ms",
        width=15,
        speedup_label=True,
    )
    assert "[Execution Time]" in out_latency
    assert "Baseline:" in out_latency
    assert "Optimized:" in out_latency
    assert "10.00x faster" in out_latency

    # Currency savings
    out_cost = render_metric_bar(
        "Monthly Spend",
        baseline=1000.0,
        optimized=100.0,
        unit="USD",
        width=15,
        is_currency=True,
    )
    assert "$1,000.00" in out_cost
    assert "$100.00" in out_cost
    assert "-$900.00" in out_cost
    assert "-90.0%" in out_cost


def test_ascii_render_resolution_card() -> None:
    card = render_resolution_card(
        workload_title="Unit Test Workload",
        pattern="CARTESIAN_JOIN -> INNER_JOIN",
        baseline_ms=10.0,
        optimized_ms=1.0,
        baseline_mb=12.0,
        optimized_mb=2.0,
        baseline_cost=500.0,
        optimized_cost=50.0,
        parity_ok=True,
    )
    assert "RESOLUTION BENCHMARK: Unit Test Workload" in card
    assert "100% DATA PARITY MATCH" in card
    assert "[Execution Latency]" in card
    assert "[Peak Memory (RAM)]" in card
    assert "[Monthly Cloud Spend]" in card


def test_demo_runner_snowflake() -> None:
    runner = MidasDemoRunner()
    res = runner.run_snowflake_demo(interactive=False)
    assert res["scenario"] == "snowflake"
    assert res["savings_usd"] == 5076.00
    assert res["metric"].data_parity_verified is True
    assert res["metric"].speedup_factor > 1.5


def test_demo_runner_glue() -> None:
    runner = MidasDemoRunner()
    res = runner.run_glue_demo(interactive=False)
    assert res["scenario"] == "glue"
    assert res["savings_usd"] == 11246.40
    assert res["metric"].data_parity_verified is True
    assert res["metric"].speedup_factor > 1.2


def test_demo_runner_emr_serverless() -> None:
    runner = MidasDemoRunner()
    res = runner.run_emr_serverless_demo(interactive=False)
    assert res["scenario"] == "emr_serverless"
    assert res["savings_usd"] == 303.64
    assert res["metric"].data_parity_verified is True
    assert res["metric"].speedup_factor > 1.2


def test_demo_runner_emr_graviton() -> None:
    runner = MidasDemoRunner()
    res = runner.run_emr_graviton_demo(interactive=False)
    assert res["scenario"] == "emr_graviton"
    assert res["savings_usd"] == 370.56


def test_demo_runner_delta() -> None:
    runner = MidasDemoRunner()
    res = runner.run_delta_demo(interactive=False)
    assert res["scenario"] == "delta"
    assert res["savings_usd"] == 793.80
    assert res["metric"].data_parity_verified is True


def test_demo_runner_all_tour() -> None:
    runner = MidasDemoRunner()
    results = runner.run_all(interactive=False)
    assert len(results) == 5
    total_savings = sum(r["savings_usd"] for r in results)
    assert total_savings > 17000.0


def test_cli_demo_subcommand() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--scenario", "snowflake", "--no-interactive"])
    assert result.exit_code == 0
    assert "CENÁRIO 1: Snowflake SQL" in result.stdout
    assert "100% DATA PARITY MATCH" in result.stdout
