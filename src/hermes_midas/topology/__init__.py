"""Hermes Midas Platform Topology and Seed Workloads module.

Provides container topology specifications, mock CloudWatch and Cost Explorer
services, seed workload manifests, and offline seed data loaders.
"""

from typing import TYPE_CHECKING

from hermes_midas.topology.mock_cloudwatch import MockCloudWatchClient
from hermes_midas.topology.mock_cost_explorer import (
    MockCostExplorerClient,
    create_cost_explorer_app,
)
from hermes_midas.topology.models import (
    AntiPatternDefinition,
    BaselineMetrics,
    ComputeSpec,
    CostBreakdownResponse,
    OptimizedMetrics,
    TelemetrySnapshot,
    TimeSeriesCostPoint,
    TopOffenderItem,
    WorkloadManifest,
)

if TYPE_CHECKING:
    from hermes_midas.topology.seed_loader import SeedDataLoader


def __getattr__(name: str):
    if name == "SeedDataLoader":
        from hermes_midas.topology.seed_loader import SeedDataLoader

        return SeedDataLoader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MockCostExplorerClient",
    "create_cost_explorer_app",
    "MockCloudWatchClient",
    "SeedDataLoader",
    "WorkloadManifest",
    "ComputeSpec",
    "BaselineMetrics",
    "OptimizedMetrics",
    "AntiPatternDefinition",
    "TelemetrySnapshot",
    "TopOffenderItem",
    "TimeSeriesCostPoint",
    "CostBreakdownResponse",
]
