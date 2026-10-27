"""Deterministic Spark benchmark for canonical bank-entry reconciliation.

Run: spark-submit benchmarks/spark_reconciliation.py --records 1000000
Data are synthetic and generated natively with Spark range(), not collected.
"""
import argparse
import json
from time import perf_counter

from iso20022_quality.spark import reconcile_spark


def run(spark, n, *, check_id_uniqueness=True):
    from pyspark.sql import functions as F

    base = spark.range(n)
    reference = F.concat(F.lit("SYN-"), F.col("id").cast("string"))
    p = base.select(
        F.concat(F.lit("P-"), F.col("id")).alias("payment_id"),
        reference.alias("end_to_end_id"),
        F.lit("BE68539007547034").alias("debtor_iban"),
        F.lit("25.50").alias("amount"), F.lit("EUR").alias("currency"),
    )
    e = base.filter(F.col("id") % 100 != 0).select(
        F.concat(F.lit("E-"), F.col("id")).alias("entry_id"),
        reference.alias("end_to_end_id"),
        F.lit("BE68539007547034").alias("account_iban"),
        F.when(F.col("id") % 50 == 0, F.lit("-25.49"))
        .otherwise(F.lit("-25.50")).alias("amount"),
        F.lit("EUR").alias("currency"), F.lit("BOOK").alias("status"),
    )
    start = perf_counter()
    results = reconcile_spark(p, e, check_id_uniqueness=check_id_uniqueness)
    counts = {r.reconciliation_status: r["count"]
              for r in results.groupBy("reconciliation_status").count().collect()}
    seconds = perf_counter() - start
    expected = {"NO_BOOKING_FOUND": (n + 99) // 100,
                "AMOUNT_MISMATCH": sum(i % 50 == 0 and i % 100 != 0 for i in range(n))}
    expected["MATCHED"] = n - sum(expected.values())
    assert counts == expected, (counts, expected)
    return {"records": n, "seconds": round(seconds, 3),
            "records_per_second": round(n / seconds), "counts": counts,
            "strict_id_check": check_id_uniqueness, "spark_version": spark.version,
            "shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions"),
            "caveat": "synthetic Spark SQL; excludes XML, schema checks and Delta I/O"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=100000)
    parser.add_argument("--skip-unique-id-check", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.records <= 10_000_000:
        parser.error("--records must be in [1, 10000000]")
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("iso20022-benchmark").getOrCreate()
    try:
        result = run(spark, args.records,
                     check_id_uniqueness=not args.skip_unique_id_check)
        print(json.dumps(result, sort_keys=True))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
