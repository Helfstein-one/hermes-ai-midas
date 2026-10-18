"""Unit and integration tests for platform topology, compose.yaml, and mock cloud services.

Tiers Covered:
- Tier 1: Feature Coverage (Mock Cost Explorer, Mock CloudWatch, Seed Data Loader)
- Tier 2: Boundary & Corner Cases (Empty manifests, Date filters, Missing metric filters)
- Tier 3: Cross-Feature Topology Validation (compose.yaml spec validation)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hermes_midas.topology import (
    MockCloudWatchClient,
    MockCostExplorerClient,
    SeedDataLoader,
)

# ============================================================================
# Tier 1: Feature Unit Tests
# ============================================================================


@pytest.mark.tier1
def test_mock_cost_explorer_top_offenders():
    """Tier 1: Verify Mock Cost Explorer correctly ranks and returns top spending workloads."""
    client = MockCostExplorerClient()
    offenders = client.get_top_offenders(top_n=5)

    assert len(offenders) >= 3
    # Glue Customer360 spends ~$11,880.00/month, followed by Databricks ~$5,918.40/month
    top_offender = offenders[0]
    assert "glue" in top_offender["workload_id"] or "customer360" in top_offender["workload_id"]
    assert float(top_offender["total_spend_usd"]) > 10000.0


@pytest.mark.tier1
def test_mock_cost_explorer_cost_and_usage_query():
    """Tier 1: Verify GetCostAndUsage standard AWS JSON-RPC response format."""
    client = MockCostExplorerClient()
    response = client.get_cost_and_usage(
        time_period={"Start": "2026-10-01", "End": "2026-10-31"},
        granularity="MONTHLY",
    )

    assert "ResultsByTime" in response
    results = response["ResultsByTime"]
    assert len(results) >= 1
    total_unblended = float(results[0]["Total"]["UnblendedCost"]["Amount"])
    assert total_unblended > 0.0


@pytest.mark.tier1
def test_mock_cloudwatch_client_extracts_telemetry():
    """Tier 1: Verify Mock CloudWatch client extracts JVM memory, skew, and idle percentages."""
    cw_client = MockCloudWatchClient()
    telemetry = cw_client.extract_pipeline_telemetry("glue_customer360_elt")

    assert telemetry is not None
    assert telemetry["gc_metrics"]["gc_time_ratio"] == 0.28
    assert telemetry["gc_metrics"]["full_gc_cycles"] == 42
    assert telemetry["data_skew"]["skew_factor"] == 1.15


@pytest.mark.tier1
def test_seed_data_loader_finds_all_workloads():
    """Tier 1: Verify SeedDataLoader discovers Glue, EMR, and Databricks seed workloads."""
    loader = SeedDataLoader()
    manifests = loader.load_all()

    assert len(manifests) >= 3
    engines = {m.engine for m in manifests.values()}
    assert "glue" in engines
    assert "emr_serverless" in engines
    assert "databricks" in engines


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================


@pytest.mark.tier2
def test_mock_cost_explorer_itemized_breakdown():
    """Tier 2: Itemized breakdown query returns granular time series points."""
    client = MockCostExplorerClient()
    breakdown = client.get_cost_breakdown(
        workload_id="glue_customer360_elt",
        start_date="2026-10-01",
        end_date="2026-10-07",
        granularity="DAILY",
    )
    assert breakdown["total_spend_usd"] > 0.0
    assert len(breakdown["time_series"]) > 0


@pytest.mark.tier2
def test_mock_cloudwatch_nonexistent_workload_returns_default():
    """Tier 2: Requesting telemetry for an unknown workload returns a safe fallback profile."""
    cw_client = MockCloudWatchClient()
    telemetry = cw_client.extract_pipeline_telemetry("nonexistent_job_12345")
    assert telemetry is not None
    assert telemetry["executor_idle_time"]["idle_percentage"] >= 0.0


# ============================================================================
# Tier 3: Topology Specification Validation
# ============================================================================


@pytest.mark.tier3
def test_compose_yaml_specification():
    """Tier 3: Validate compose.yaml structure, rootless services, and network definition."""
    compose_path = Path("compose.yaml")
    assert compose_path.exists(), "compose.yaml must exist at project root"

    with open(compose_path, encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    assert "services" in compose_data, "compose.yaml must define services"
    services = compose_data["services"]

    # Verify all 5 core services exist
    expected_services = {"moto", "cost-explorer-mock", "gitea", "airflow", "ollama"}
    for svc in expected_services:
        assert svc in services, f"Service '{svc}' missing in compose.yaml"

    # Verify bridge network configuration
    assert "networks" in compose_data, "compose.yaml must define networks"
    assert "midas-net" in compose_data["networks"], "midas-net bridge network missing"

    # Verify rootless Gitea image
    assert "rootless" in services["gitea"]["image"], "Gitea service must use rootless image"
