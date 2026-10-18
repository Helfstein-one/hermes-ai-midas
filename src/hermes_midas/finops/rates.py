"""Authoritative static cloud rate tables for AWS Glue, EMR Serverless, and Databricks."""

from __future__ import annotations

from decimal import Decimal

# AWS Glue Rate Table (us-east-1 reference)
GLUE_STANDARD_DPU_HOURLY_RATE = Decimal("0.44")
GLUE_FLEX_DPU_HOURLY_RATE = Decimal("0.29")
GLUE_MINIMUM_BILLABLE_SECONDS = Decimal(60)

GLUE_WORKER_DPU_MAP: dict[str, Decimal] = {
    "standard": Decimal("1.0"),
    "g.1x": Decimal("1.0"),
    "g.2x": Decimal("2.0"),
    "g.4x": Decimal("4.0"),
    "g.8x": Decimal("8.0"),
}

# AWS EMR Serverless Rate Table (us-east-1 reference)
EMR_VCPU_HOURLY_RATE = Decimal("0.052624")
EMR_RAM_GB_HOURLY_RATE = Decimal("0.0057785")
EMR_STORAGE_GB_HOURLY_RATE = Decimal("0.000111")
EMR_FREE_STORAGE_GB_PER_WORKER = Decimal(20)
EMR_MINIMUM_BILLABLE_SECONDS = Decimal(60)

# Databricks DBU Rate Table
DATABRICKS_DBU_RATES: dict[str, Decimal] = {
    "jobs_standard": Decimal("0.15"),
    "jobs_enterprise": Decimal("0.20"),
    "all_purpose_standard": Decimal("0.40"),
    "all_purpose_enterprise": Decimal("0.55"),
    "serverless_jobs": Decimal("0.35"),
}

# Underlying EC2 Instance Specs and Hourly On-Demand Rates (us-east-1)
DATABRICKS_INSTANCE_MAP: dict[str, dict[str, Decimal]] = {
    "m5.xlarge": {"dbu": Decimal("0.75"), "ec2_hourly": Decimal("0.192"), "vcpu": Decimal(4), "ram_gb": Decimal(16)},
    "m5.2xlarge": {"dbu": Decimal("1.50"), "ec2_hourly": Decimal("0.384"), "vcpu": Decimal(8), "ram_gb": Decimal(32)},
    "i3.xlarge": {
        "dbu": Decimal("1.00"),
        "ec2_hourly": Decimal("0.312"),
        "vcpu": Decimal(4),
        "ram_gb": Decimal("30.5"),
    },
    "i3.2xlarge": {"dbu": Decimal("2.00"), "ec2_hourly": Decimal("0.624"), "vcpu": Decimal(8), "ram_gb": Decimal(61)},
    "c5.2xlarge": {"dbu": Decimal("1.50"), "ec2_hourly": Decimal("0.340"), "vcpu": Decimal(8), "ram_gb": Decimal(16)},
    "r5.4xlarge": {"dbu": Decimal("1.50"), "ec2_hourly": Decimal("1.008"), "vcpu": Decimal(16), "ram_gb": Decimal(128)},
    "i3en.3xlarge": {
        "dbu": Decimal("2.50"),
        "ec2_hourly": Decimal("1.356"),
        "vcpu": Decimal(12),
        "ram_gb": Decimal(96),
    },
}

# Snowflake Virtual Warehouse Credits Table (Standard Edition $3.00/credit)
SNOWFLAKE_CREDIT_RATE = Decimal("3.00")
SNOWFLAKE_WAREHOUSE_CREDITS: dict[str, Decimal] = {
    "x-small": Decimal("1.0"),
    "small": Decimal("2.0"),
    "medium": Decimal("4.0"),
    "large": Decimal("8.0"),
    "x-large": Decimal("16.0"),
    "2x-large": Decimal("32.0"),
    "3x-large": Decimal("64.0"),
    "4x-large": Decimal("128.0"),
}
SNOWFLAKE_MINIMUM_BILLABLE_SECONDS = Decimal(60)

# Google BigQuery On-Demand Analysis ($6.25 per TB scanned)
BIGQUERY_ON_DEMAND_PER_TB = Decimal("6.25")
BYTES_PER_TB = Decimal(1024) ** 4

SECONDS_PER_HOUR = Decimal(3600)
DAYS_PER_MONTH = Decimal("30.5")
MONTHS_PER_YEAR = Decimal(12)
