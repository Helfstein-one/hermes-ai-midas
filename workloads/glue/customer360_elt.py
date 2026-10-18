"""Customer 360 ELT PySpark Job for AWS Glue.

Workload ID: glue_customer360_elt
Platform: AWS Glue (4.0, G.2X Workers)
Anti-Patterns Demonstrated:
1. Orphan Actions: Standalone df_raw.count() and df_raw.show(10) force redundant full scans.
2. Legacy Python UDF: Row-by-row @udf clean_address causes JVM-Python SerDe bottleneck and GC thrashing.
"""

import pyspark.sql.functions as F
from pyspark.context import SparkContext
from pyspark.sql import SparkSession
from pyspark.sql.functions import udf
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


def run_pipeline() -> None:
    SparkContext.getOrCreate()
    spark = SparkSession.builder.appName("GlueCustomer360ELT").getOrCreate()

    customer_schema = StructType([
        StructField("customer_id", StringType(), False),
        StructField("first_name", StringType(), True),
        StructField("last_name", StringType(), True),
        StructField("street", StringType(), True),
        StructField("city", StringType(), True),
        StructField("state", StringType(), True),
        StructField("zip_code", StringType(), True),
        StructField("annual_spend", DoubleType(), True),
        StructField("updated_at", TimestampType(), True),
    ])

    raw_path = "s3://midas-data-lake/raw/customers/"
    df_raw = spark.read.schema(customer_schema).parquet(raw_path)

    # ANTI-PATTERN 1: Orphan Eager Actions
    df_raw.count()
    df_raw.show(10)

    # ANTI-PATTERN 2: Legacy Python row-by-row UDF
    @udf(returnType=StringType())
    def clean_address(street, city, state, zip_code):
        if not street:
            return "UNKNOWN"
        street_clean = street.strip().upper()
        city_clean = (city or "").strip().upper()
        state_clean = (state or "").strip().upper()
        zip_clean = (zip_code or "").strip()
        return f"{street_clean}, {city_clean}, {state_clean} {zip_clean}".strip()

    df_enriched = (
        df_raw.filter(F.col("customer_id").isNotNull())
        .withColumn("full_name", F.concat_ws(" ", F.col("first_name"), F.col("last_name")))
        .withColumn(
            "formatted_address",
            clean_address(F.col("street"), F.col("city"), F.col("state"), F.col("zip_code")),
        )
        .withColumn("tier", F.when(F.col("annual_spend") > 5000.0, "VIP").otherwise("STANDARD"))
    )

    curated_path = "s3://midas-data-lake/curated/customer360/"
    df_enriched.write.mode("overwrite").parquet(curated_path)


if __name__ == "__main__":
    run_pipeline()
