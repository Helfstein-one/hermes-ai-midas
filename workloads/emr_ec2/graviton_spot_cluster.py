"""EMR on EC2 PySpark ETL Pipeline for Core Transaction Aggregation.

Workload ID: emr_ec2_graviton_spot
Platform: Amazon EMR on EC2 (EMR 6.10, Apache Spark 3.3.1)
Anti-Patterns Demonstrated:
1. Overprovisioned x86 On-Demand Instances (m5.2xlarge instead of Graviton m6g with Spot Task nodes).
2. Unbroadcasted Join: Small merchant reference table (8.5 MB) joined without broadcast hint.
3. Orphan Actions: Standalone df_raw.count() executed in batch loops.
4. Legacy Row-by-Row UDF: format_currency inducing Python-JVM IPC serialization.
"""

from pyspark.context import SparkContext
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.functions import udf
from pyspark.sql.types import DoubleType, StringType, StructField, StructType, TimestampType


def run_pipeline() -> None:
    SparkContext.getOrCreate()
    spark = SparkSession.builder.appName("EMRTransactionAggregation").getOrCreate()

    txn_schema = StructType([
        StructField("txn_id", StringType(), False),
        StructField("merchant_id", StringType(), False),
        StructField("amount", DoubleType(), True),
        StructField("currency", StringType(), True),
        StructField("timestamp", TimestampType(), True),
    ])

    # 1. Read transactions
    df_txns = spark.read.schema(txn_schema).parquet("s3://midas-lake/transactions/raw/")

    # ANTI-PATTERN 1: Orphan Eager Action
    df_txns.count()

    # 2. Read small merchant metadata (8.5 MB)
    df_merchants = spark.read.parquet("s3://midas-lake/merchants/dim/")

    # ANTI-PATTERN 2: Unbroadcasted Join with small reference table
    df_joined = df_txns.join(df_merchants, on="merchant_id", how="inner")

    # ANTI-PATTERN 3: Legacy Python UDF
    @udf(returnType=StringType())
    def format_currency(amount, currency):
        if amount is None:
            return "0.00"
        return f"{currency} {amount:,.2f}"

    df_formatted = df_joined.withColumn("formatted_amount", format_currency(F.col("amount"), F.col("currency")))

    # 3. Write out aggregations
    df_formatted.write.mode("overwrite").parquet("s3://midas-lake/curated/daily_transactions/")


if __name__ == "__main__":
    run_pipeline()
