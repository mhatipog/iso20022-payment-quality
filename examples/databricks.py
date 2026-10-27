"""Read-only Databricks notebook example for already-canonical Delta payments.

Deliberately does NOT write Silver or quarantine tables. Unconditional append
would duplicate records on replay; implement your institution's verified
idempotent MERGE, audit ledger, access controls and rollback separately.
Requires an active Databricks/Spark session and an existing canonical table.
"""
from pyspark.sql import SparkSession

from iso20022_quality.spark import partition_quality, validate_payments

session = SparkSession.getActiveSession()
if session is None:
    raise RuntimeError("Run within an active Spark/Databricks session")

bronze = session.read.table("bronze.iso20022_payments")
quality = validate_payments(bronze, profile="sepa_sct")
valid, quarantine = partition_quality(quality)

# Driver collects only aggregate counts here, never raw financial records.
counts = {
    str(row["dq_valid"]): row["count"]
    for row in quality.groupBy("dq_valid").count().collect()
}
print("Synthetic/authorized batch validation counts:", counts)
# valid, quarantine are DataFrames for caller-controlled, audited persistence.
