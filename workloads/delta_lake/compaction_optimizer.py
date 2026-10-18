"""Delta Lake Small Files Compaction & Partitioning PySpark Pipeline.

Workload ID: delta_compaction_optimizer
Platform: Apache Spark 3.4 / Delta Lake 2.4 on AWS S3
Anti-Patterns Demonstrated:
1. Excessive Repartition: .repartition(500) before writing, producing thousands of 50KB files on S3.
2. Missing Partition Key in Write Sink: writing unpartitioned time-series telemetry.
3. Orphan Eager Actions: df_events.show(5) before downstream write.
"""

from pyspark.context import SparkContext
from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def run_pipeline() -> None:
    SparkContext.getOrCreate()
    spark = (
        SparkSession.builder.appName("DeltaCompactionOptimizer")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )

    # 1. Ingest raw IoT events
    df_events = spark.read.json("s3://midas-lake/iot/raw_events/")

    # ANTI-PATTERN 1: Orphan action
    df_events.show(5)

    # 2. Enrich events with timestamp partitions
    df_enriched = (
        df_events.filter(F.col("device_id").isNotNull())
        .withColumn("event_date", F.to_date(F.col("event_timestamp")))
        .withColumn("event_hour", F.hour(F.col("event_timestamp")))
    )

    # ANTI-PATTERN 2: Excessive repartitioning creating S3 small-file thrashing
    df_repartitioned = df_enriched.repartition(500)

    # ANTI-PATTERN 3: Write sink missing partitionBy
    df_repartitioned.write.format("delta").mode("append").save("s3://midas-lake/delta/iot_telemetry/")


if __name__ == "__main__":
    run_pipeline()
