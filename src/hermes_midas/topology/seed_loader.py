"""Automated seed data loader and export utilities for platform topology.

Loads seed workloads from disk, populates mock Cost Explorer and CloudWatch clients,
exports offline fixture bundles, and optionally provisions Moto resources.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from hermes_midas.topology.mock_cloudwatch import MockCloudWatchClient
from hermes_midas.topology.mock_cost_explorer import MockCostExplorerClient
from hermes_midas.topology.models import WorkloadManifest


class SeedDataLoader:
    """Discovers, parses, and hydrates seed workloads across the platform."""

    def __init__(self, workloads_dir: Path | str | None = None) -> None:
        if workloads_dir:
            self.workloads_dir = Path(workloads_dir)
        else:
            env_dir = os.environ.get("MIDAS_WORKLOADS_DIR")
            if env_dir and Path(env_dir).is_dir():
                self.workloads_dir = Path(env_dir)
            else:
                curr = Path(__file__).resolve()
                found = None
                for p in curr.parents:
                    cand = p / "workloads"
                    if cand.is_dir():
                        found = cand
                        break
                self.workloads_dir = found or Path("workloads")

        self._workloads: dict[str, WorkloadManifest] = {}
        self.load_all()

    def load_all(self) -> dict[str, WorkloadManifest]:
        """Discover and load all workload manifests under workloads_dir."""
        self._workloads.clear()
        if not self.workloads_dir.exists():
            return self._workloads

        for manifest_file in self.workloads_dir.glob("*/manifest.json"):
            try:
                with open(manifest_file, encoding="utf-8") as f:
                    data = json.load(f)
                manifest = WorkloadManifest.from_dict(data)
                self._workloads[manifest.workload_id] = manifest
            except Exception as e:
                print(f"Warning: Failed to load manifest {manifest_file}: {e}", file=sys.stderr)

        return self._workloads

    def get_manifest(self, workload_id: str) -> WorkloadManifest | None:
        """Retrieve manifest by workload_id."""
        return self._workloads.get(workload_id)

    def list_manifests(self) -> list[WorkloadManifest]:
        """List all discovered manifests."""
        return list(self._workloads.values())

    def get_script_source(self, workload_id: str) -> str:
        """Read original PySpark script source for a workload."""
        m = self.get_manifest(workload_id)
        if not m:
            raise KeyError(f"Workload '{workload_id}' not found.")

        script_path = Path(m.script_path)
        if not script_path.is_absolute():
            # Check relative to project root or workloads_dir
            root = self.workloads_dir.parent
            candidate = root / script_path
            if candidate.exists():
                script_path = candidate
            else:
                candidate = self.workloads_dir / script_path.name
                if candidate.exists():
                    script_path = candidate

        with open(script_path, encoding="utf-8") as f:
            return f.read()

    def populate_cost_explorer(self, client: MockCostExplorerClient) -> None:
        """Register all discovered workloads with a MockCostExplorerClient."""
        for m in self._workloads.values():
            client.register_manifest(m)

    def populate_cloudwatch(self, client: MockCloudWatchClient) -> None:
        """Register all discovered workloads with a MockCloudWatchClient."""
        for m in self._workloads.values():
            client.register_manifest(m)

    def export_seed_bundle(self, output_file: Path | str) -> dict[str, Any]:
        """Export all manifests, scripts, cost records, and telemetry to a single offline bundle."""
        bundle: dict[str, Any] = {
            "version": "1.0.0",
            "workloads": {},
            "total_workloads": len(self._workloads),
        }

        ce = MockCostExplorerClient(list(self._workloads.values()))
        cw = MockCloudWatchClient(list(self._workloads.values()))

        for w_id, m in self._workloads.items():
            script_src = ""
            try:
                script_src = self.get_script_source(w_id)
            except Exception:
                pass

            bundle["workloads"][w_id] = {
                "manifest": m.to_dict(),
                "script_content": script_src,
                "cost_profile": ce._workloads.get(w_id),
                "telemetry_profile": cw.extract_pipeline_telemetry(w_id),
            }

        bundle["top_offenders"] = ce.get_top_offenders(lookback_days=30, top_n=10)

        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2)

        return bundle

    def import_seed_bundle(self, input_file: Path | str) -> dict[str, Any]:
        """Import seed data bundle from JSON file."""
        in_path = Path(input_file)
        with open(in_path, encoding="utf-8") as f:
            data = json.load(f)

        workloads_data = data.get("workloads", {})
        for w_id, w_info in workloads_data.items():
            if "manifest" in w_info:
                manifest = WorkloadManifest.from_dict(w_info["manifest"])
                self._workloads[w_id] = manifest

        return data

    def provision_moto(
        self,
        endpoint_url: str = "http://localhost:5000",
        region_name: str = "us-east-1",
    ) -> bool:
        """Provision S3 buckets, Glue catalog, and CloudWatch logs in Moto if available."""
        try:
            import boto3
        except ImportError:
            print("Notice: boto3 not installed, skipping live Moto provisioning.", file=sys.stderr)
            return False

        try:
            s3 = boto3.client("s3", endpoint_url=endpoint_url, region_name=region_name,
                              aws_access_key_id="mock_key", aws_secret_access_key="mock_secret")
            glue = boto3.client("glue", endpoint_url=endpoint_url, region_name=region_name,
                                aws_access_key_id="mock_key", aws_secret_access_key="mock_secret")
            logs = boto3.client("logs", endpoint_url=endpoint_url, region_name=region_name,
                                aws_access_key_id="mock_key", aws_secret_access_key="mock_secret")

            # 1. Create S3 buckets
            buckets = [
                "midas-data-lake",
                "midas-telemetry",
                "midas-cur",
                "midas-code-artifacts",
            ]
            for b in buckets:
                try:
                    s3.create_bucket(Bucket=b)
                except Exception:
                    pass

            # 2. Upload script artifacts to S3
            for w_id, m in self._workloads.items():
                try:
                    src = self.get_script_source(w_id)
                    key = f"scripts/{Path(m.script_path).name}"
                    s3.put_object(Bucket="midas-code-artifacts", Key=key, Body=src.encode("utf-8"))
                except Exception:
                    pass

            # 3. Create Glue Database
            try:
                glue.create_database(DatabaseInput={"Name": "midas_dw"})
            except Exception:
                pass

            # 4. Create CloudWatch Log Groups
            log_groups = [
                "/aws-glue/jobs/output",
                "/aws-glue/jobs/error",
                "/emr-serverless/jobs/clickstream_attribution",
                "/databricks/jobs/financial_ledger_sync",
            ]
            for lg in log_groups:
                try:
                    logs.create_log_group(logGroupName=lg)
                except Exception:
                    pass

            print(f"Successfully provisioned Moto resources at {endpoint_url}")
            return True

        except Exception as e:
            print(f"Notice: Moto provisioning at {endpoint_url} skipped: {e}", file=sys.stderr)
            return False


def main() -> None:
    """CLI tool for seed data loading, bundling, and provisioning."""
    parser = argparse.ArgumentParser(description="Hermes Midas Seed Data Manager")
    parser.add_argument("--summary", action="store_true", help="Print summary of discovered seed workloads")
    parser.add_argument("--export", type=str, help="Export all seed data into a JSON bundle file")
    parser.add_argument("--import-bundle", type=str, help="Import seed data from JSON bundle file")
    parser.add_argument("--provision-moto", action="store_true", help="Provision Moto S3/Glue/Logs resources")
    parser.add_argument("--moto-url", type=str, default="http://localhost:5000", help="Moto endpoint URL")

    args = parser.parse_args()
    loader = SeedDataLoader()

    if args.summary or (not args.export and not args.import_bundle and not args.provision_moto):
        print(f"Discovered {len(loader.list_manifests())} seed workloads:")
        for m in loader.list_manifests():
            print(f"  - [{m.engine.upper()}] {m.workload_id} -> Baseline: ${m.baseline_metrics.monthly_spend_usd:,.2f}/mo, Savings: ${m.optimized_metrics.monthly_savings_usd:,.2f}/mo")

    if args.export:
        loader.export_seed_bundle(args.export)
        print(f"Exported seed data bundle to {args.export}")

    if args.import_bundle:
        loader.import_seed_bundle(args.import_bundle)
        print(f"Imported seed data bundle from {args.import_bundle}")

    if args.provision_moto:
        loader.provision_moto(endpoint_url=args.moto_url)


if __name__ == "__main__":
    main()
