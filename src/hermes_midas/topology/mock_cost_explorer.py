"""Mock AWS Cost Explorer client and standalone mock service.

Provides deterministic FinOps cost accounting, top offender rankings,
day-by-day itemized breakdowns, and AWS JSON-RPC protocol compatibility.
"""

from __future__ import annotations

import datetime
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from hermes_midas.topology.models import (
    CostBreakdownResponse,
    TimeSeriesCostPoint,
    TopOffenderItem,
    WorkloadManifest,
)


class MockCostExplorerClient:
    """Deterministic in-memory AWS Cost Explorer client.

    Adheres to official AWS Cost Explorer API structures for GetCostAndUsage,
    GetDimensionValues, and GetCostForecast, while providing fast FinOps helpers.
    """

    def __init__(self, manifests: list[WorkloadManifest] | None = None) -> None:
        self._workloads: dict[str, dict[str, Any]] = {}
        if manifests:
            for m in manifests:
                self.register_manifest(m)
        else:
            self._load_default_seed_data()

    def register_manifest(self, m: WorkloadManifest) -> None:
        """Register a workload manifest into the Cost Explorer database."""
        service_map = {
            "glue": "AWS Glue",
            "emr_serverless": "Amazon EMR Serverless",
            "databricks": "Databricks on AWS",
        }
        unit_map = {
            "glue": ("DPU-Hours", 27000.0, 900.0, "USE1-Glue:DPU-Hours"),
            "emr_serverless": ("vCPU/GB-Hours", 1200.0, 40.0, "USE1-EMR:Serverless-vCPU"),
            "databricks": ("DBU / Node-Hours", 4800.0, 160.0, "USE1-Databricks:Compute"),
        }

        service_name = service_map.get(m.engine, m.engine.title())
        unit_info = unit_map.get(m.engine, ("Units", 1000.0, 33.3, f"USE1-{m.engine}:Compute"))

        self._workloads[m.workload_id] = {
            "workload_id": m.workload_id,
            "job_name": m.job_name,
            "engine": m.engine,
            "service": service_name,
            "monthly_spend_usd": float(m.baseline_metrics.monthly_spend_usd),
            "daily_average_usd": round(float(m.baseline_metrics.monthly_spend_usd) / 30.0, 2),
            "cost_per_run_usd": float(m.baseline_metrics.cost_per_run_usd),
            "runs_per_month": m.runs_per_month,
            "runs_per_day": m.runs_per_day,
            "usage_unit": unit_info[0],
            "total_monthly_units": unit_info[1],
            "daily_units": unit_info[2],
            "usage_type": unit_info[3],
            "trend": "INCREASING" if m.engine in ("glue", "emr_serverless") else "FLAT",
            "optimized_monthly_spend_usd": float(m.optimized_metrics.monthly_spend_usd),
            "monthly_savings_usd": float(m.optimized_metrics.monthly_savings_usd),
            "waste_reduction_pct": float(m.optimized_metrics.waste_reduction_pct),
        }

    def _load_default_seed_data(self) -> None:
        """Load the authoritative seed profiles for the 3 target pipelines."""
        self._workloads = {
            "glue_customer360_elt": {
                "workload_id": "glue_customer360_elt",
                "job_name": "glue_customer360_elt",
                "engine": "glue",
                "service": "AWS Glue",
                "monthly_spend_usd": 11880.00,
                "daily_average_usd": 396.00,
                "cost_per_run_usd": 16.50,
                "runs_per_month": 720,
                "runs_per_day": 24,
                "usage_unit": "DPU-Hours",
                "total_monthly_units": 27000.0,
                "daily_units": 900.0,
                "usage_type": "USE1-Glue:DPU-Hours",
                "trend": "INCREASING",
                "optimized_monthly_spend_usd": 633.60,
                "monthly_savings_usd": 11246.40,
                "waste_reduction_pct": 94.67,
            },
            "databricks_financial_ledger_sync": {
                "workload_id": "databricks_financial_ledger_sync",
                "job_name": "databricks_financial_ledger_sync",
                "engine": "databricks",
                "service": "Databricks on AWS",
                "monthly_spend_usd": 5918.40,
                "daily_average_usd": 197.28,
                "cost_per_run_usd": 197.28,
                "runs_per_month": 30,
                "runs_per_day": 1,
                "usage_unit": "DBU / Node-Hours",
                "total_monthly_units": 4800.0,
                "daily_units": 160.0,
                "usage_type": "USE1-Databricks:Compute",
                "trend": "FLAT",
                "optimized_monthly_spend_usd": 88.80,
                "monthly_savings_usd": 5829.60,
                "waste_reduction_pct": 98.50,
            },
            "emr_clickstream_attribution": {
                "workload_id": "emr_clickstream_attribution",
                "job_name": "emr_clickstream_attribution",
                "engine": "emr_serverless",
                "service": "Amazon EMR Serverless",
                "monthly_spend_usd": 316.93,
                "daily_average_usd": 10.56,
                "cost_per_run_usd": 10.5644,
                "runs_per_month": 30,
                "runs_per_day": 1,
                "usage_unit": "vCPU/GB-Hours",
                "total_monthly_units": 1200.0,
                "daily_units": 40.0,
                "usage_type": "USE1-EMR:Serverless-Compute",
                "trend": "INCREASING",
                "optimized_monthly_spend_usd": 13.29,
                "monthly_savings_usd": 303.64,
                "waste_reduction_pct": 95.81,
            },
        }

    def get_top_offenders(
        self,
        lookback_days: int = 30,
        top_n: int = 5,
        tag_key: str = "JobName",
        service_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve highest compute spend workloads sorted descending by cost."""
        filtered = list(self._workloads.values())
        if service_filter:
            filtered = [
                w
                for w in filtered
                if w["service"].lower() == service_filter.lower() or w["engine"].lower() == service_filter.lower()
            ]

        # Calculate total spend across all workloads for percentage
        total_all_spend = sum(w["monthly_spend_usd"] for w in self._workloads.values())
        if total_all_spend <= 0:
            total_all_spend = 1.0

        # Sort descending by spend
        sorted_workloads = sorted(filtered, key=lambda w: w["monthly_spend_usd"], reverse=True)

        results: list[dict[str, Any]] = []
        for idx, w in enumerate(sorted_workloads[:top_n], start=1):
            spend_pct = round((w["monthly_spend_usd"] / total_all_spend) * 100.0, 1)
            item = TopOffenderItem(
                rank=idx,
                workload_id=w["workload_id"],
                service=w["service"],
                tag_key=tag_key,
                total_spend_usd=w["monthly_spend_usd"],
                daily_average_usd=w["daily_average_usd"],
                spend_percentage=spend_pct,
                trend=w["trend"],
                usage_unit=w["usage_unit"],
                total_units=w["total_monthly_units"],
            )
            results.append(item.to_dict())

        return results

    def get_cost_breakdown(
        self,
        workload_id: str,
        start_date: str,
        end_date: str,
        granularity: str = "DAILY",
        group_by: str = "USAGE_TYPE",
    ) -> dict[str, Any]:
        """Extract itemized time-series cost points for a specific workload."""
        if workload_id not in self._workloads:
            raise KeyError(f"Workload '{workload_id}' not found in Cost Explorer dataset.")

        workload = self._workloads[workload_id]
        start_dt = datetime.date.fromisoformat(start_date)
        end_dt = datetime.date.fromisoformat(end_date)
        num_days = max(1, (end_dt - start_dt).days)

        points: list[TimeSeriesCostPoint] = []
        daily_cost = workload["daily_average_usd"]
        daily_qty = workload["daily_units"]

        if granularity.upper() == "MONTHLY":
            points.append(
                TimeSeriesCostPoint(
                    date=start_date,
                    usage_type=workload["usage_type"],
                    usage_quantity=round(daily_qty * num_days, 2),
                    cost_usd=round(daily_cost * num_days, 2),
                )
            )
        else:  # DAILY
            curr = start_dt
            while curr < end_dt:
                date_str = curr.isoformat()
                points.append(
                    TimeSeriesCostPoint(
                        date=date_str,
                        usage_type=workload["usage_type"],
                        usage_quantity=daily_qty,
                        cost_usd=daily_cost,
                    )
                )
                curr += datetime.timedelta(days=1)

        total_spend = sum(p.cost_usd for p in points)
        response = CostBreakdownResponse(
            workload_id=workload_id,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity.upper(),
            total_spend_usd=round(total_spend, 2),
            currency="USD",
            time_series=points,
        )
        return response.to_dict()

    def forecast_workload_spend(
        self,
        workload_id: str,
        forecast_days: int = 30,
        reduction_percentage: float = 0.0,
    ) -> dict[str, Any]:
        """Compute deterministic baseline vs optimized spend forecast."""
        if workload_id not in self._workloads:
            raise KeyError(f"Workload '{workload_id}' not found in Cost Explorer dataset.")

        workload = self._workloads[workload_id]
        baseline_monthly = Decimal(str(workload["monthly_spend_usd"]))

        if reduction_percentage > 0:
            reduction_factor = Decimal(str(reduction_percentage)) / Decimal("100")
            projected_monthly = baseline_monthly * (Decimal("1") - reduction_factor)
            monthly_savings = baseline_monthly - projected_monthly
        else:
            projected_monthly = Decimal(str(workload["optimized_monthly_spend_usd"]))
            monthly_savings = Decimal(str(workload["monthly_savings_usd"]))
            reduction_factor = Decimal(str(workload["waste_reduction_pct"])) / Decimal("100")

        # Scale by forecast_days
        scale = Decimal(str(forecast_days)) / Decimal("30")
        baseline_scaled = (baseline_monthly * scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        projected_scaled = (projected_monthly * scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        savings_scaled = (monthly_savings * scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return {
            "workload_id": workload_id,
            "forecast_days": forecast_days,
            "baseline_spend_usd": float(baseline_scaled),
            "projected_spend_usd": float(projected_scaled),
            "projected_savings_usd": float(savings_scaled),
            "waste_reduction_pct": float(round(reduction_factor * 100, 2)),
            "currency": "USD",
        }

    def get_cost_and_usage(
        self,
        time_period: dict[str, str],
        granularity: str = "DAILY",
        filter: dict[str, Any] | None = None,
        metrics: list[str] | None = None,
        group_by: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Standard AWS Cost Explorer GetCostAndUsage implementation."""
        start_date = time_period.get("Start", "2026-09-15")
        end_date = time_period.get("End", "2026-10-15")
        metrics = metrics or ["UnblendedCost", "UsageQuantity"]

        # Parse group_by criteria
        group_keys = [g.get("Key", "SERVICE") for g in (group_by or [])]

        results_by_time: list[dict[str, Any]] = []
        start_dt = datetime.date.fromisoformat(start_date)
        end_dt = datetime.date.fromisoformat(end_date)

        curr = start_dt
        while curr < end_dt:
            next_day = curr + datetime.timedelta(days=1)
            time_slice = {
                "Start": curr.isoformat(),
                "End": next_day.isoformat(),
            }

            day_total_cost = Decimal("0.0")
            day_total_qty = Decimal("0.0")
            groups: list[dict[str, Any]] = []

            for _w_id, w in self._workloads.items():
                cost = Decimal(str(w["daily_average_usd"]))
                qty = Decimal(str(w["daily_units"]))
                day_total_cost += cost
                day_total_qty += qty

                # Construct group key based on request
                keys: list[str] = []
                for gk in group_keys:
                    if gk in ("SERVICE", "Service"):
                        keys.append(w["service"])
                    elif "JobName" in gk or "TAG" in gk:
                        keys.append(w["job_name"])
                    elif gk in ("USAGE_TYPE", "UsageType"):
                        keys.append(w["usage_type"])
                    else:
                        keys.append(w["workload_id"])

                groups.append(
                    {
                        "Keys": keys,
                        "Metrics": {
                            "UnblendedCost": {
                                "Amount": str(cost.quantize(Decimal("0.01"))),
                                "Unit": "USD",
                            },
                            "UsageQuantity": {
                                "Amount": str(qty.quantize(Decimal("0.1"))),
                                "Unit": w["usage_unit"],
                            },
                        },
                    }
                )

            results_by_time.append(
                {
                    "TimePeriod": time_slice,
                    "Total": {
                        "UnblendedCost": {
                            "Amount": str(day_total_cost.quantize(Decimal("0.01"))),
                            "Unit": "USD",
                        },
                        "UsageQuantity": {
                            "Amount": str(day_total_qty.quantize(Decimal("0.1"))),
                            "Unit": "N/A",
                        },
                    },
                    "Groups": groups,
                    "Estimated": False,
                }
            )

            curr = next_day

        return {
            "ResultsByTime": results_by_time,
            "DimensionValueAttributes": [],
            "DimensionKeyIncluded": group_keys,
        }

    def get_dimension_values(
        self,
        time_period: dict[str, str],
        dimension: str,
        context: str | None = None,
        filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Standard AWS Cost Explorer GetDimensionValues implementation."""
        values: list[dict[str, str]] = []
        if dimension.upper() == "SERVICE":
            services = {w["service"] for w in self._workloads.values()}
            values = [{"Value": s, "Attributes": {}} for s in sorted(services)]
        elif dimension.upper() == "USAGE_TYPE":
            usage_types = {w["usage_type"] for w in self._workloads.values()}
            values = [{"Value": u, "Attributes": {}} for u in sorted(usage_types)]
        else:
            jobs = {w["job_name"] for w in self._workloads.values()}
            values = [{"Value": j, "Attributes": {}} for j in sorted(jobs)]

        return {
            "DimensionValues": values,
            "ReturnSize": len(values),
            "TotalSize": len(values),
        }

    def get_cost_forecast(
        self,
        time_period: dict[str, str],
        metric: str = "UNBLENDED_COST",
        granularity: str = "MONTHLY",
        prediction_interval_level: int | None = None,
    ) -> dict[str, Any]:
        """Standard AWS Cost Explorer GetCostForecast implementation."""
        total_monthly = sum(w["monthly_spend_usd"] for w in self._workloads.values())
        return {
            "Total": {
                "Amount": str(round(total_monthly, 2)),
                "Unit": "USD",
            },
            "ForecastResultsByTime": [
                {
                    "TimePeriod": time_period,
                    "MeanValue": str(round(total_monthly, 2)),
                    "PredictionIntervalLowerBound": str(round(total_monthly * 0.95, 2)),
                    "PredictionIntervalUpperBound": str(round(total_monthly * 1.05, 2)),
                }
            ],
        }


# ASGI application handler for standalone mock service
def create_cost_explorer_app(client: MockCostExplorerClient | None = None):
    """Creates an ASGI/WSGI HTTP handler for the mock Cost Explorer container."""
    ce_client = client or MockCostExplorerClient()

    async def asgi_app(scope, receive, send):
        if scope["type"] != "http":
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET")

        # Health check
        if path == "/health" and method == "GET":
            body = json.dumps({"status": "healthy", "service": "midas-cost-explorer-mock"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # FinOps REST: Top offenders
        if path.startswith("/finops/top-offenders") and method == "GET":
            data = ce_client.get_top_offenders()
            body = json.dumps(data).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # FinOps REST: Breakdown
        if path.startswith("/finops/breakdown/") and method == "GET":
            workload_id = path.replace("/finops/breakdown/", "").strip("/")
            try:
                data = ce_client.get_cost_breakdown(
                    workload_id=workload_id,
                    start_date="2026-09-15",
                    end_date="2026-10-15",
                )
                body = json.dumps(data).encode()
                status = 200
            except KeyError as e:
                body = json.dumps({"error": str(e)}).encode()
                status = 404

            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # AWS JSON-RPC protocol endpoint
        if method == "POST":
            # Read request body
            body_bytes = b""
            while True:
                message = await receive()
                body_bytes += message.get("body", b"")
                if not message.get("more_body", False):
                    break

            req_json = json.loads(body_bytes.decode() or "{}")

            # Extract target from header
            headers = dict(scope.get("headers", []))
            target = headers.get(b"x-amz-target", b"").decode()

            if "GetCostAndUsage" in target or req_json.get("Action") == "GetCostAndUsage":
                resp_data = ce_client.get_cost_and_usage(
                    time_period=req_json.get("TimePeriod", {}),
                    granularity=req_json.get("Granularity", "DAILY"),
                    filter=req_json.get("Filter"),
                    metrics=req_json.get("Metrics"),
                    group_by=req_json.get("GroupBy"),
                )
            elif "GetDimensionValues" in target or req_json.get("Action") == "GetDimensionValues":
                resp_data = ce_client.get_dimension_values(
                    time_period=req_json.get("TimePeriod", {}),
                    dimension=req_json.get("Dimension", "SERVICE"),
                    context=req_json.get("Context"),
                    filter=req_json.get("Filter"),
                )
            elif "GetCostForecast" in target or req_json.get("Action") == "GetCostForecast":
                resp_data = ce_client.get_cost_forecast(
                    time_period=req_json.get("TimePeriod", {}),
                    metric=req_json.get("Metric", "UNBLENDED_COST"),
                    granularity=req_json.get("Granularity", "MONTHLY"),
                )
            else:
                resp_data = ce_client.get_cost_and_usage(
                    time_period=req_json.get("TimePeriod", {"Start": "2026-09-15", "End": "2026-10-15"})
                )

            body = json.dumps(resp_data).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/x-amz-json-1.1"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # Fallback 404
        body = b'{"error": "Not Found"}'
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return asgi_app


# Expose standard FastAPI or ASGI app instance for uvicorn
app = create_cost_explorer_app()
