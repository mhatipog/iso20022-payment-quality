"""Illustrative notebook code; run on a Databricks cluster with pyspark installed.

Assumes a preceding XML ingestion layer has produced a canonical Delta table with
schema documented in README.md. Never pass client-specific raw bank XML into logs.
"""

from iso20022_quality.spark import partition_quality, validate_payments

source = spark.read.format("delta").table("bronze.iso20022_payments")  # noqa: F821
quality = validate_payments(source, profile="sepa_sct")
valid, quarantine = partition_quality(quality)
(valid.write.format("delta").mode("append").saveAsTable("silver.iso20022_payments"))
(quarantine.write.format("delta").mode("append").saveAsTable("ops.iso20022_quarantine"))
