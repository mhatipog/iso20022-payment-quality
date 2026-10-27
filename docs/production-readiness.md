# Production readiness and reproducible evidence

The package is an **operational data-quality component**, not an ISO/EPC certification engine, settlement service, or payment initiator. Use only on non-production / redacted data until your institution has completed integration testing and sign-off.

## Safety properties demonstrated in tests

- Malformed decimal XML (exponents, signs and NaN) is invalid, not silently converted.
- PySpark amount columns must be exact decimal or string; binary float/double is rejected.
- Spark ANSI-enabled invalid numeric rows produce INVALID_AMOUNT instead of aborting the reconciliation batch.
- Reused payment_id or entry_id in the supplied processing scope is surfaced. Supplying a unique end-to-end reference is **not** sufficient proof of identity.
- Non-unique EndToEndId+debtor account, aggregated statement entries, reversals, returns and non-booked entries never become clean matches.
- Ambiguous pain.002 references are not assigned to arbitrary payment instructions.
- Invalid source records are not eligible for successful reconciliation.

The Spark implementation has no per-row Python UDF or driver-side collect. Its conservative physical identifier checks involve distributed shuffles. `check_id_uniqueness=False` saves those shuffles **only if upstream uniqueness is actually enforced**.

## What must be implemented by the deploying organization

1. Obtain licensed/authorized official ISO XSD and current EPC technical validation subsets; test supported versions and your bank's usage restrictions. XML extraction here is not equivalent to schema validation.
2. Ingest XML in a scalable, bounded, secure reader; do not collect entire banking files onto a Spark driver. The built-in parser enforces a 16 MiB document limit.
3. Partition reconciliation by institution, account and settlement/booking period. References can be reused across time and channels; this function does not discover an appropriate temporal join scope.
4. Use immutable, source-derived transaction identities and configure idempotent Delta MERGE keys. Coordinate file-receipt recording with Silver and quarantine commits; the library's replay detector is not an atomic transactional ledger.
5. Enforce RBAC, encryption, masking, retention and audit trails on account references and quarantine tables; never send raw financial records to telemetry.
6. Run regression/canary jobs on representative *authorized* production samples, including paginated multi-day camt, returns, chargebacks, non-EUR accounts, multi-currency FX and status sequencing.
7. Configure threshold alerts for invalid files, quality exceptions, unmatched values and reconcile drift. Keep human approval for any money movement.

## Benchmarks run locally (27 October 2026)

Hardware: isolated Linux container, Python 3.13.5, x86_64. Deterministic **synthetic data**; benchmark scripts check exact classification counts. These values exclude XML ingest, XSD, database writes, Kafka, Delta and Databricks.

| Synthetic payments | Local in-memory Python reconciliation | Throughput |
|---:|---:|---:|
| 10,000 | 0.034 s | 290,153 payments/sec |
| 100,000 | 0.746 s | 134,120 payments/sec |
| 250,000 | 2.776 s | 90,051 payments/sec |

Timing varies significantly run-to-run; a repeated 100,000-row run took 0.515 s. These are *observations*, not guaranteed rates. Reproduce with `python benchmarks/reconciliation.py --records 100000`.

Additional XML extraction tests (synthetic pain.001.001.09, no XSD): 1,000 transactions in 0.027 s; 10,000 transactions in 0.307 s. These were run with a standalone local generator, not part of the published benchmark script.

**No verified 1–10 million row Spark/Databricks throughput or cost benchmark exists yet.** It would be misleading to infer large-scale distributed performance from the local Python measurements.

## Verification/acceptance plan

- CI: Python 3.10 and 3.12 unit tests, Spark integration with Java 17, Ruff.
- Offline: controlled and privacy-safe scenarios, XSD coverage, schema evolution and replay tests.
- Data-platform scale: 100k, 1M and 10M synthetic data, at least two realistic key-skew patterns, forced shuffles and strict/no-duplicate variants. Record Spark/DBR runtime, executors, partition sizes, shuffle read/write bytes, spill, job duration, error rate, and financial reconciliation counts.
- Only then call the particular supported version and workload *production validated* for that deployment.


## Reconciliation across banks and processing periods

`reconcile_spark` defaults to matching on EndToEndId and debtor account, with
conservative ambiguity detection. The same pair may legitimately be reused
across separate imports, bank relationships or periods. Do not force a match
by choosing one arbitrary statement row.

Where the ingestion system creates a **shared, validated reconciliation
cohort** in both inputs, pass `scope_columns=("reconciliation_cohort",)`.
For example, a cohort can represent a carefully bounded bank relationship,
reconciliation run and authorized processing window:

```python
from iso20022_quality.spark import reconcile_spark

outcome = reconcile_spark(
    canonical_payments,
    canonical_entries,
    scope_columns=("reconciliation_cohort",),
)
```

Null/blank cohort keys yield `UNMATCHABLE_SCOPE`. Missing or blank bank-entry
identifiers yield `INVALID_ENTRY_ID`, not `MATCHED`. Reused physical
identifiers are marked as duplicates when `check_id_uniqueness=True`.
Cohorts must be consistently derived and audited upstream. Do **not** equate
requested execution date with booking date; bank value dates, booking dates,
cutoffs and holidays differ.

The function does not establish an end-to-end audit ledger, conditional
exactly-once ingest, temporal matching windows, or regulatory compliance.
