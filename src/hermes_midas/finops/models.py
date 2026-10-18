"""Data models for deterministic FinOps calculations and ROI metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from hermes_midas.finops.rates import (
    GLUE_WORKER_DPU_MAP,
)


class ComputePlatform(StrEnum):
    """Supported cloud distributed compute engines."""

    GLUE = "glue"
    EMR_SERVERLESS = "emr_serverless"
    DATABRICKS = "databricks"
    SNOWFLAKE = "snowflake"
    BIGQUERY = "bigquery"


@dataclass
class GlueResourceSpec:
    """Resource configuration for AWS Glue jobs."""

    worker_type: str = "G.2X"
    num_workers: int = 10
    is_flex: bool = False

    @property
    def total_dpu(self) -> Decimal:
        """Compute total allocated DPUs."""
        unit_dpu = GLUE_WORKER_DPU_MAP.get(self.worker_type.lower(), Decimal("2.0"))
        return Decimal(str(self.num_workers)) * unit_dpu


@dataclass
class EmrResourceSpec:
    """Resource configuration for AWS EMR Serverless applications."""

    driver_vcpu: Decimal = Decimal(2)
    driver_memory_gb: Decimal = Decimal(8)
    executor_count: int = 16
    executor_vcpu: Decimal = Decimal(4)
    executor_memory_gb: Decimal = Decimal(16)
    storage_gb_per_worker: Decimal = Decimal(20)

    @property
    def total_vcpu(self) -> Decimal:
        """Total aggregate vCPU allocated across driver and executors."""
        return self.driver_vcpu + (Decimal(str(self.executor_count)) * self.executor_vcpu)

    @property
    def total_memory_gb(self) -> Decimal:
        """Total aggregate RAM allocated across driver and executors."""
        return self.driver_memory_gb + (Decimal(str(self.executor_count)) * self.executor_memory_gb)


@dataclass
class DatabricksResourceSpec:
    """Resource configuration for Databricks classic or serverless clusters."""

    node_type: str = "i3.xlarge"
    num_workers: int = 8
    tier: str = "jobs_enterprise"
    is_serverless: bool = False

    @property
    def total_nodes(self) -> int:
        """Total nodes including 1 driver + worker nodes."""
        return 1 + self.num_workers


@dataclass
class SnowflakeResourceSpec:
    """Resource configuration for Snowflake Virtual Warehouses."""

    warehouse_size: str = "large"
    credit_rate_usd: Decimal = Decimal("3.00")

    @property
    def credits_per_hour(self) -> Decimal:
        from hermes_midas.finops.rates import SNOWFLAKE_WAREHOUSE_CREDITS

        return SNOWFLAKE_WAREHOUSE_CREDITS.get(self.warehouse_size.lower(), Decimal("8.0"))


@dataclass
class BigQueryResourceSpec:
    """Resource configuration for Google BigQuery On-Demand queries."""

    scanned_bytes: Decimal = Decimal("1099511627776")  # 1 TB
    rate_per_tb: Decimal = Decimal("6.25")


@dataclass
class RunCostBreakdown:
    """Granular cost breakdown for a single pipeline run."""

    engine: str
    duration_seconds: Decimal
    billable_seconds: Decimal
    hourly_rate_usd: Decimal
    cost_usd: Decimal
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "duration_seconds": float(self.duration_seconds),
            "billable_seconds": float(self.billable_seconds),
            "hourly_rate_usd": float(self.hourly_rate_usd),
            "cost_usd": float(self.cost_usd),
            "details": self.details,
        }


@dataclass
class FinOpsImpact:
    """Deterministic financial ROI and compute waste metrics without LLM hallucination."""

    engine: str
    baseline_cost_usd: Decimal
    optimized_cost_usd: Decimal
    cost_savings_per_run_usd: Decimal
    daily_savings_usd: Decimal
    monthly_savings_usd: Decimal
    annual_savings_usd: Decimal
    waste_reduction_pct: Decimal
    pricing_formula_applied: str
    runs_per_day: Decimal = Decimal(1)
    runs_per_month: Decimal = Decimal(30)
    details: dict[str, Any] = field(default_factory=dict)

    # Convenience float properties for interoperability with external schemas
    @property
    def monthly_savings(self) -> float:
        return float(self.monthly_savings_usd)

    @property
    def annual_savings(self) -> float:
        return float(self.annual_savings_usd)

    @property
    def monthly_baseline_cost(self) -> float:
        return float(self.baseline_cost_usd * self.runs_per_month)

    @property
    def monthly_optimized_cost(self) -> float:
        return float(self.optimized_cost_usd * self.runs_per_month)

    def to_dict(self) -> dict[str, Any]:
        """Convert financial impact metrics into serializable dictionary."""
        return {
            "engine": self.engine,
            "baseline_cost_usd": str(self.baseline_cost_usd),
            "optimized_cost_usd": str(self.optimized_cost_usd),
            "cost_savings_per_run_usd": str(self.cost_savings_per_run_usd),
            "daily_savings_usd": str(self.daily_savings_usd),
            "monthly_savings_usd": str(self.monthly_savings_usd),
            "annual_savings_usd": str(self.annual_savings_usd),
            "waste_reduction_pct": str(self.waste_reduction_pct),
            "pricing_formula_applied": self.pricing_formula_applied,
            "runs_per_day": float(self.runs_per_day),
            "runs_per_month": float(self.runs_per_month),
            "monthly_savings": self.monthly_savings,
            "annual_savings": self.annual_savings,
            "monthly_baseline_cost": self.monthly_baseline_cost,
            "monthly_optimized_cost": self.monthly_optimized_cost,
            "details": self.details,
        }

    def dict(self) -> dict[str, Any]:
        """Pydantic v1 compatibility alias."""
        return self.to_dict()

    def model_dump(self) -> dict[str, Any]:
        """Pydantic v2 compatibility alias."""
        return self.to_dict()
