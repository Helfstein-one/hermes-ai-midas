"""Pytest conftest: offline network blocking, mock environment, and test fixtures."""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

import pytest

# Enforce offline testing environment variables before any hermes_midas imports
os.environ.setdefault("MIDAS_OFFLINE_MODE", "1")
os.environ.setdefault("MIDAS_TESTING", "1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "mock_midas_key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "mock_midas_secret")
os.environ.setdefault("MIDAS_WEBHOOK_SECRET", "test-secret")


class NetworkBlockedError(RuntimeError):
    """Raised when an unauthorized network connection is attempted during offline tests."""


# Whitelisted loopback addresses for in-memory ASGI or local mock servers
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}


@pytest.fixture(autouse=True, scope="session")
def guard_network_sockets():
    """Session-wide fixture that guards network sockets to enforce 100% offline determinism.

    Any attempt to connect to external internet hosts raises NetworkBlockedError.
    """
    original_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) and address else address
        if isinstance(host, str) and (host in ALLOWED_HOSTS or host.startswith("127.") or host.startswith("/")):
            return original_connect(self, address)
        raise NetworkBlockedError(
            f"External network connection to {address} blocked by offline test guard."
        )

    socket.socket.connect = guarded_connect
    yield
    socket.socket.connect = original_connect


@pytest.fixture(autouse=True)
def clean_midas_artifacts():
    """Ensure repository-level .midas artifacts are cleaned before and after tests."""
    midas_dir = Path(".midas")
    if midas_dir.exists():
        import shutil
        shutil.rmtree(midas_dir, ignore_errors=True)
    yield
    if midas_dir.exists():
        import shutil
        shutil.rmtree(midas_dir, ignore_errors=True)


# ============================================================================
# PySpark Code Sample Fixtures
# ============================================================================

@pytest.fixture
def clean_pyspark_code() -> str:
    """A clean, well-optimized PySpark script without anti-patterns."""
    return '''"""Clean PySpark ETL job."""
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

spark = SparkSession.builder.appName("CleanETL").getOrCreate()

df_orders = spark.read.parquet("s3://bucket/orders/")
dim_customers = spark.read.parquet("s3://bucket/dim_customers/")

# Broadcast small dimension table
df_joined = df_orders.join(F.broadcast(dim_customers), on="customer_id", how="inner")

# Coalesce to reasonable partition count before write
df_final = df_joined.coalesce(16)

# Partitioned write
df_final.write.partitionBy("order_year", "order_month").mode("overwrite").parquet("s3://bucket/output/")
'''


@pytest.fixture
def orphan_actions_code() -> str:
    """PySpark script with unassigned / discarded eager actions."""
    return '''from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("OrphanActionETL").getOrCreate()

df = spark.read.parquet("s3://bucket/data/")

# Orphan actions sitting as bare expression statements
df.count()
df.collect()
df.show(20)

# Dead assignment where variable is never read
dead_val = df.count()

# Active assignment (should NOT be flagged)
active_count = df.count()
print(f"Total rows: {active_count}")

# Assert expression (should NOT be flagged)
assert df.count() > 0

df.write.mode("overwrite").parquet("s3://bucket/out/")
'''


@pytest.fixture
def unbroadcasted_join_code() -> str:
    """PySpark script joining with a dimension table without broadcast hint."""
    return '''from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("JoinETL").getOrCreate()

df_fact_orders = spark.read.parquet("s3://bucket/orders/")
dim_campaigns = spark.read.parquet("s3://bucket/dim_campaigns/")
lookup_status = spark.read.parquet("s3://bucket/lookup_status/")

# Unbroadcasted dimension joins
df_res1 = df_fact_orders.join(dim_campaigns, on="campaign_id")
df_res2 = df_res1.join(lookup_status, on="status_id", how="left")

df_res2.write.parquet("s3://bucket/output/")
'''


@pytest.fixture
def suboptimal_partition_code() -> str:
    """PySpark script with excessive repartitioning and missing partitionBy on write."""
    return '''from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("PartitionETL").getOrCreate()

df = spark.read.parquet("s3://bucket/data/")

# Excessive repartition
df_repart = df.repartition(1000)

# Dangerous coalesce(1) on large data
df_single = df_repart.coalesce(1)

# Missing partitionBy on final write with date keys
df_single.write.mode("overwrite").parquet("s3://bucket/output/")
'''


@pytest.fixture
def legacy_udf_code() -> str:
    """PySpark script using legacy Python @udf instead of native expressions."""
    return '''from pyspark.sql import SparkSession
from pyspark.sql.functions import udf
from pyspark.sql.types import StringType

spark = SparkSession.builder.appName("UdfETL").getOrCreate()

@udf(returnType=StringType())
def format_customer_tier(score):
    if score is None:
        return "STANDARD"
    return str(score).upper()

df = spark.read.parquet("s3://bucket/data/")
df_enriched = df.withColumn("tier", format_customer_tier(df["raw_score"]))
df_enriched.write.parquet("s3://bucket/out/")
'''


@pytest.fixture
def syntax_error_code() -> str:
    """Malformed Python code with syntax error."""
    return '''from pyspark.sql import SparkSession
def broken_syntax(
    df = spark.read.parquet("s3://unclosed_bracket"
'''


# ============================================================================
# Git Repository Fixtures
# ============================================================================

@pytest.fixture
def local_git_repo(tmp_path: Path) -> Path:
    """Initializes a local isolated git repository with an initial commit for testing."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Initialize git repo
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Midas Test"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@hermes.ai"], cwd=repo_dir, check=True, capture_output=True)

    # Add initial file and commit
    dummy_file = repo_dir / "jobs" / "sample_etl.py"
    dummy_file.parent.mkdir(parents=True, exist_ok=True)
    dummy_file.write_text("# Initial PySpark job\n")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True)

    return repo_dir


# ============================================================================
# Telemetry & Pricing Fixtures
# ============================================================================

@pytest.fixture
def sample_glue_telemetry() -> dict:
    """Sample telemetry payload for an AWS Glue job."""
    return {
        "engine": "glue",
        "worker_type": "G.2X",
        "number_of_workers": 10,
        "dpu_per_worker": 2,
        "total_dpu": 20,
        "duration_seconds": 2700,
        "runs_per_day": 24,
        "runs_per_month": 730,
    }


@pytest.fixture
def sample_emr_telemetry() -> dict:
    """Sample telemetry payload for an AWS EMR Serverless job."""
    return {
        "engine": "emr_serverless",
        "driver_vcpu": 2,
        "driver_memory_gb": 8,
        "executor_count": 16,
        "executor_vcpu": 4,
        "executor_memory_gb": 16,
        "duration_seconds": 3600,
        "runs_per_day": 4,
        "runs_per_month": 120,
    }


@pytest.fixture
def sample_databricks_telemetry() -> dict:
    """Sample telemetry payload for a Databricks automated ETL job."""
    return {
        "engine": "databricks",
        "tier": "enterprise_jobs",
        "node_type": "i3.xlarge",
        "node_count": 9,
        "dbu_per_node_hr": 1.0,
        "dbu_rate_usd": 0.20,
        "ec2_rate_usd_per_node_hr": 0.312,
        "duration_seconds": 5400,
        "runs_per_day": 1,
        "runs_per_month": 30,
    }
