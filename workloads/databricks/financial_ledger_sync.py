"""Financial Ledger Synchronization Pipeline (Databricks 13.3 LTS).

This workload reconciles multi-tenant general ledger journal entries, computes
daily account balances, and performs currency-level balance rollup.

Intentional Anti-Patterns:
1. Severe Key Skew: Aggregating on tenant_id where 90% of rows contain 'SYSTEM_DEFAULT'
   routes 90% of the volume to a single reducer partition/task.
2. Massive Disk Spill: The straggler partition exceeds executor heap memory, spilling
   88.5GB of shuffle data to disk and triggering repeated Full GC cycles (44% GC pause ratio).
3. 86% Cluster Idling: The cluster is over-provisioned to 64 r5.4xlarge nodes to absorb
   the memory pressure, leaving 63 nodes 86.4% idle for over 2 hours while waiting for the straggler.
"""

import pyspark.sql.functions as F
from pyspark.context import SparkContext
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    DecimalType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


def run_pipeline() -> None:
    SparkContext.getOrCreate()
    spark = SparkSession.builder.appName("DatabricksFinancialLedgerSync").getOrCreate()

    # Schema for journal transactions
    ledger_schema = StructType([
        StructField("transaction_id", StringType(), False),
        StructField("tenant_id", StringType(), False),
        StructField("account_id", StringType(), False),
        StructField("currency_code", StringType(), False),
        StructField("debit_amount", DecimalType(18, 4), True),
        StructField("credit_amount", DecimalType(18, 4), True),
        StructField("posting_date", TimestampType(), False),
    ])

    # 1. Ingest ledger transactions
    ledger_path = "s3://midas-data-lake/ledger/journal_entries/"
    df_ledger = spark.read.schema(ledger_schema).parquet(ledger_path)

    # ANTI-PATTERN 1 & 2: Severe Key Skew and Massive Disk Spill
    # In this dataset, 90% of rows have tenant_id = 'SYSTEM_DEFAULT'.
    # Standard groupBy on tenant_id directs 90% of the data to a single partition,
    # causing 88.5GB of disk spilling, extreme memory pressure, and 44% GC thrashing.
    # The straggler task takes 7,080 seconds while the median task takes only 192 seconds.
    # Recommended fix: Two-phase salted aggregation (salting key with rand() * 16).
    df_aggregated = (
        df_ledger
        .groupBy("tenant_id", "currency_code")
        .agg(
            F.sum("debit_amount").alias("total_debits"),
            F.sum("credit_amount").alias("total_credits"),
            F.count("transaction_id").alias("entry_count"),
        )
        .withColumn(
            "net_balance",
            F.coalesce(F.col("total_credits"), F.lit(0)) - F.coalesce(F.col("total_debits"), F.lit(0))
        )
    )

    # 2. Write aggregated financial balances
    # ANTI-PATTERN 3: 64-node cluster overprovisioning
    # 64 nodes (1,024 vCPUs, 8,192 GB RAM) were provisioned solely to provide heap headroom,
    # leaving 86.4% of cluster capacity idle for hours.
    output_path = "s3://midas-data-lake/curated/financial_ledger_balances/"
    (
        df_aggregated.write
        .mode("overwrite")
        .parquet(output_path)
    )


if __name__ == "__main__":
    run_pipeline()
