# Architecture and trust boundaries

[Home](../README.md) · [Verification](verification.md) · [Production readiness](production-readiness.md)

## What the repository supplies

```text
Authorized payment XML   Authorized statement XML   Payment-status XML
     pain.001                  camt.053                 pain.002
         |                         |                        |
         +---- bounded XML parsing / scoped diagnostics --+
                                   |
                        Canonical immutable records
                         /        |           \
                    quality   lifecycle      reconciliation
                         \        |           /
                          migration-readiness
                                   |
             independent controls → technical migration gate
                                   |
                         BLOCKED / PASS_TECHNICAL_CHECKS
```

The bounded Python file parser processes individual `pain.001.001.09`,
`camt.053.001.08`, and `pain.002.001.10` documents. The Spark functions
accept **already canonicalized** DataFrames rather than pretending to be a
distributed XML or XSD parser. Only listed message versions are supported.

## Core invariants

1. Preserve exact `Decimal` financial amounts; reject binary floating-point
   payment columns. Spark casts malformed amounts safely to invalid findings
   under ANSI mode; no silent rounding of excess precision.
2. Treat group-level integrity failures as file-wide quarantine, never a partially
   accepted payment file.
3. Reconcile on a supported account/reference pair and an **optional independent
   matching cohort**, not an arbitrarily selected candidate. Reused keys,
   missing entry IDs and aggregated rows cannot produce successful matches.
4. `pain.002` observations record what was reported and when supplied; an
   `ACCP` observation, bank booking or returned record is not proof of settlement.
5. Compare independent source-system totals to the **entire scoped population**.
   A matched subset alone does not establish a complete migration. Source control
   provenance and scope consistency remain deployment responsibilities.
6. Outputs are diagnostics and aggregate reports, never instructions to settle
   money or authorize a production cutover.

## Data-platform integration

```text
Trusted XML ingestion (outside this package)
          | → immutable source object and receipt ledger
          v
Bronze (raw, access controlled) → canonicalization
          |
          v
Spark quality checks → Silver candidates / protected quarantine
          |
          v
Scope-aware Spark reconciliation → exception statuses / audit lineage
          |
          v
Independent source controls + human review → migration decision
```

**Not implemented by the library:** production-scale XML reading, official
XSD/EPC technical validation, Delta atomic writes, exactly-once ledgering,
time-window association, complete ISO message coverage, bank calendar
interpretation or production authorization. The [Databricks example](../examples/databricks.py)
reads but does not write production tables.

## Code map

- `xml.py`, `models.py`, `iban.py` — bounded extraction, canonical records
- `reconcile.py`, `lifecycle.py` — conservative Python evidence matching
- `spark.py` — distributed canonical-table quality and reconciliation
- `readiness.py`, `migration_gate.py` — aggregates and independent controls
- `ingestion.py`, `statement_quality.py` — replay diagnostics, balance arithmetic
- `tests/fixtures`, `examples/`, `benchmarks/` — reproducible synthetic evidence

See [bank sample provenance](bank-cases.md) and
[measured benchmark limits](benchmarks.md) before comparing the results to
real banking workloads.
