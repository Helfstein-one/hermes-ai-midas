"""Clickstream Attribution Pipeline (Amazon EMR Serverless Spark 3.4.1).

This workload processes massive web/mobile clickstream event streams,
joins events with marketing campaign dimension metadata, and computes
first-touch and last-touch conversion attribution.

Intentional Anti-Patterns:
1. Unbroadcasted Dimension Join: Joining 1TB clickstream events with 15MB campaign
   dimension table without broadcast hint triggers expensive SortMergeJoin and 450GB network shuffle.
2. Micro-Partitioning: Explicit df.repartition(10000) produces thousands of tiny files (<80KB),
   causing excessive S3 PUT request overhead, partition throttling, and metadata explosion.
"""

import pyspark.sql.functions as F
from pyspark.context import SparkContext
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


def run_pipeline() -> None:
    SparkContext.getOrCreate()
    spark = SparkSession.builder.appName("EMRClickstreamAttribution").getOrCreate()

    # Event schema
    events_schema = StructType([
        StructField("event_id", StringType(), False),
        StructField("session_id", StringType(), False),
        StructField("user_id", StringType(), True),
        StructField("campaign_id", StringType(), True),
        StructField("event_type", StringType(), False),
        StructField("page_url", StringType(), True),
        StructField("revenue", DoubleType(), True),
        StructField("event_timestamp", TimestampType(), False),
    ])

    # Dimension schema (small reference lookup table, ~15MB)
    dim_campaigns_schema = StructType([
        StructField("campaign_id", StringType(), False),
        StructField("campaign_name", StringType(), True),
        StructField("channel", StringType(), True),
        StructField("budget", DoubleType(), True),
        StructField("target_region", StringType(), True),
    ])

    # 1. Read input sources
    events_path = "s3://midas-data-lake/raw/clickstream_events/"
    campaigns_path = "s3://midas-data-lake/dimensions/campaign_metadata/"

    df_events = spark.read.schema(events_schema).parquet(events_path)
    dim_campaigns = spark.read.schema(dim_campaigns_schema).parquet(campaigns_path)

    # ANTI-PATTERN 1: Unbroadcasted Dimension Join
    # dim_campaigns is only 15MB, but lacking F.broadcast(dim_campaigns) forces Spark
    # into a distributed SortMergeJoin / ShuffleHashJoin across all executors,
    # causing 451GB of shuffle I/O and leaving executors 68.2% idle waiting on network exchanges.
    df_joined = df_events.join(
        dim_campaigns,
        on="campaign_id",
        how="inner"
    )

    # 2. Compute attribution metrics
    df_attributed = (
        df_joined
        .withColumn("is_conversion", F.when(F.col("event_type") == "PURCHASE", 1).otherwise(0))
        .groupBy("campaign_id", "campaign_name", "channel", "target_region")
        .agg(
            F.count("event_id").alias("total_clicks"),
            F.sum("is_conversion").alias("total_conversions"),
            F.sum("revenue").alias("gross_revenue"),
        )
    )

    # ANTI-PATTERN 2: Suboptimal Micro-Partitioning
    # Forcing 10,000 partitions on aggregated output creates tiny ~75KB files,
    # swamping driver task scheduling and triggering S3 503 SlowDown exceptions.
    # Should use coalesce(64) or adaptive partition sizing instead.
    df_partitioned = df_attributed.repartition(10000)

    # 3. Write target dataset
    output_path = "s3://midas-data-lake/analytics/campaign_attribution/"
    (
        df_partitioned.write
        .mode("overwrite")
        .parquet(output_path)
    )


if __name__ == "__main__":
    run_pipeline()
