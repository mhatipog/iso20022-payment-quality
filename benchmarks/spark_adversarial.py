"""Adversarial Spark benchmark: skewed references, invalid IDs and bank exceptions.

All records are artificial. Classifications are checked against an independent
deterministic oracle, not against the function under test. Data remain in Spark.
"""
from collections import Counter
import json
from time import perf_counter

from iso20022_quality.spark import reconcile_spark


def expected_counts(n: int) -> dict[str, int]:
    if n < 1000:
        raise ValueError("Use at least 1000 records to populate the skewed reference")
    results: Counter[str] = Counter()
    for i in range(n):
        if i % 20 == 0:
            code = "AMBIGUOUS_MATCH"
        elif i % 101 == 0:
            code = "INVALID_ENTRY_ID"
        elif i % 50 == 0:
            code = "AMOUNT_MISMATCH"
        elif i % 103 == 0:
            code = "REVERSAL_REQUIRES_REVIEW"
        elif i % 107 == 0:
            code = "RETURN_REQUIRES_REVIEW"
        elif i % 109 == 0:
            code = "NOT_BOOKED"
        else:
            code = "MATCHED"
        results[code] += 1
    return dict(results)


def run(spark, n: int):
    from pyspark.sql import functions as F

    if not 1000 <= n <= 10_000_000:
        raise ValueError("records must be in [1000, 10000000]")
    base = spark.range(n)
    ref = F.when(F.col("id") % 20 == 0, F.lit("HOT-REFERENCE")).otherwise(
        F.concat(F.lit("SYN-"), F.col("id").cast("string"))
    )
    payments = base.select(
        F.concat(F.lit("P-"), F.col("id")).alias("payment_id"),
        ref.alias("end_to_end_id"),
        F.lit("BE68539007547034").alias("debtor_iban"),
        F.lit("25.50").alias("amount"),
        F.lit("EUR").alias("currency"),
    )
    entries = base.filter(F.col("id") % 100 != 0).select(
        F.when(F.col("id") % 101 == 0, F.lit(None))
        .otherwise(F.concat(F.lit("E-"), F.col("id"))).alias("entry_id"),
        ref.alias("end_to_end_id"),
        F.lit("BE68539007547034").alias("account_iban"),
        F.when(F.col("id") % 50 == 0, F.lit("-25.49"))
        .otherwise(F.lit("-25.50")).alias("amount"),
        F.lit("EUR").alias("currency"),
        F.when(F.col("id") % 109 == 0, F.lit("PDNG"))
        .otherwise(F.lit("BOOK")).alias("status"),
        (F.col("id") % 103 == 0).alias("reversal"),
        F.when(F.col("id") % 107 == 0, F.lit("PMNT/ICDT/ARET"))
        .otherwise(F.lit("")).alias("bank_transaction_code"),
    )
    start = perf_counter()
    observed = {
        row.reconciliation_status: row["count"]
        for row in reconcile_spark(payments, entries)
        .groupBy("reconciliation_status").count().collect()
    }
    duration = perf_counter() - start
    expected = expected_counts(n)
    assert observed == expected, {"observed": observed, "expected": expected}
    return {
        "scenario": "skewed-5pct-hot-reference-and-bank-exceptions",
        "records": n, "seconds": round(duration, 3),
        "records_per_second": round(n / duration),
        "counts": observed,
        "spark_version": spark.version,
        "shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions"),
        "caveat": "synthetic, no XML, XSD, Delta I/O, real bank data or operational SLA",
    }


if __name__ == "__main__":
    from pyspark.sql import SparkSession
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=100000)
    args = parser.parse_args()
    spark = SparkSession.builder.appName("iso20022-skew-benchmark").getOrCreate()
    try:
        print(json.dumps(run(spark, args.records), sort_keys=True))
    finally:
        spark.stop()
