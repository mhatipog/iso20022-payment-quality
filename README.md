# ISO 20022 Payment Quality

**Practical, testable payment-data quality and reconciliation for Python, Spark and Azure Databricks.**

A banking data engineer rarely needs a new XML generator. They need to explain why their
legacy payment rows do not reconcile with bank statements, prevent silent ingestion of
bad values, and account for duplicates, inconsistent identifiers and scheme versions.
This package provides a conservative **operational quality layer** for those pipelines.

**Status:** experimental v0.3.0. Not certified for sending SEPA payments or accepting
production financial instructions. All fixtures are synthetic; no confidential bank data.

## Production engineering evidence

This release adds ANSI-safe financial amount validation, duplicate physical identifier
checks, ambiguity-safe status linking, and conservative treatment of returns/reversals.
Exact padded Spark decimals are accepted without rounding over-precise values.

- [Production gates, known limitations and reproducible measurements](docs/production-readiness.md)
- [Synthetic Python reconciliation harness](benchmarks/reconciliation.py)
- [Synthetic native Spark benchmark](benchmarks/spark_reconciliation.py)

These tests do **not** prove full EPC conformance or production settlement correctness.
Use official XSD/EPC TVS and institution-specific validation in addition to this package.

## What is implemented

- Parse **`pain.001.001.09`** customer credit transfer instructions, including per-file and
  per-payment-information transaction counts and control sums, using exact `Decimal` math.
- Extract **`camt.053.001.08`** statement entries, accounting for debit/credit sign, booking
  status and the fact that a single entry can contain *multiple* underlying transactions.
- Check IBAN mod-97 and registered country lengths (known-country table; generic fallback),
  amount formatting, three-letter currency-code shape (not full ISO 4217 registry), EUR-only
  SEPA operational profile and decimal precision.
- Detect exact replay of previously ingested files or conflicting content under the same
  business message ID (caller-managed receipt ledger).
- Read **`pain.002.001.10`** status reports (`ACCP`, `RJCT`, `PDNG`, etc.), retain
  bank reason codes, and link transaction-level observations to instructions without
  guessing a final settlement state.
- Audit `camt.053` `OPBD`/`CLBD` booked-balance arithmetic. Unassessable multi-page,
  mixed-currency or non-booked statements are identified rather than labelled wrong.
- Recognize `Sts/ Cd` and direct `Sts` status, bank return codes, reversal flags,
  and batch counts hiding aggregate entries.
- **Quarantine pattern:** invalid payment records are separated; group-header or
  payment-batch integrity failures quarantine the entire payment file.
- **Conservative reconciliation:** EndToEndId **plus debtor account**; refuses ambiguous
  matches and `NOTPROVIDED`, reports amount, currency, direction and booking mismatches.
- Redacted aggregate **legacy-migration readiness** report (coverage, failures, exceptions).
- **Spark-native** DataFrame quality checks and one-row-per-payment reconciliation: no
  Python UDFs or `.collect()` in package functions. Write Silver and Quarantine to Delta.

### Scope is deliberately narrower than the standards

This is **not** a complete ISO XSD validator, EPC scheme conformance suite, PSD2/PSD3
validation engine, anti-fraud model, payment authorization or settlement confirmation.
Use ISO XSD + the relevant EPC implementation guidelines and bank-specific usage rules
*in addition to* these operational checks. Invalid/unrecognized namespaces fail closed.

The supported message types are **pain.001.001.09**, **pain.002.001.10** and **camt.053.001.08**. ISO's latest
catalogue versions may be newer; the 2025 EPC SCT Customer-to-PSP implementation
specification is based on 2019 ISO messages. Rulebook 2025 v1.2 (30 September 2026)
**delayed the planned cutoff for unstructured addresses**, so this project intentionally
does not reject them on an invented November 2026 cutoff date.

EPC 2025 SCT rulebook: https://www.europeanpaymentscouncil.eu/what-we-do/epc-payment-schemes/sepa-credit-transfer-sct/sepa-credit-transfer-rulebook-and

ISO catalogue: https://www.iso20022.org/iso-20022-message-definitions

Camt.053.001.08 description (ISO): https://www.iso20022.org/sites/default/files/documents/messages/mdr_part_2/ISO20022_MDRPart2_BankToCustomerCashManagement_2018_2019_v1_0.pdf

## Quick start

```bash
python -m pip install -e .
python examples/demo.py
python -m iso20022_quality.cli --payment tests/fixtures/pain09.xml --statement tests/fixtures/camt08.xml
# or after installation:
iso20022-quality --payment tests/fixtures/pain09.xml --statement tests/fixtures/camt08.xml
```

Expected synthetic result: **3 payments accepted**, **1 matched**, **1 amount mismatch**,
**1 no booking found**. No personal data in CLI output.

```python
from iso20022_quality import parse_pain001, parse_camt053, read_xml_file, reconcile

payments = parse_pain001(read_xml_file("tests/fixtures/pain09.xml"))
accepted, quarantine = payments.partition()
statement = parse_camt053(read_xml_file("tests/fixtures/camt08.xml"))
results = reconcile(accepted, statement.entries)
print([r.status for r in results])
# ['MATCHED', 'AMOUNT_MISMATCH', 'NO_BOOKING_FOUND']
```

Use `assess_readiness([payments], [statement])` for a redacted, deterministic
aggregate report. Control-sum and count mismatches quarantine the entire payment file
because treating only individual rows as valid would conceal a possible omitted payment.

## Bank-published compatibility examples

See [bank examples and limitations](docs/bank-cases.md). The opt-in
`python examples/public_bank_smoke.py` command fetches published Goldman Sachs
XML examples and outputs aggregate compatibility diagnostics without recording
personal financial information. These are publicly documented *sample messages*,
not private production transactions. Network access is necessary.

## Azure Databricks: canonical Delta input, native Spark quality

The Spark input is **already flattened/canonicalized**. Use a trusted XML ingestion
step (Autoloader with a suitable XML parser or a controlled upstream connector)
for the source documents. This library does not pretend a driver-side XML parser
is a scalable Spark XML data source.

Install in your Databricks environment with:

```bash
# From a project checkout, until a PyPI release exists:
python -m pip install -e '.[spark]'
```

A PyPI distribution has not been published. Supported
Spark versions: 3.4 and newer, subject to your Databricks runtime compatibility.

Canonical payment DataFrame must contain:

| column | meaning |
| --- | --- |
| `end_to_end_id` | ISO payment EndToEndId, or `NOTPROVIDED` |
| `debtor_iban` | originating account IBAN |
| `creditor_iban` | beneficiary account IBAN |
| `amount` | positive decimal amount or decimal string, max 16 integral + 8 fractional digits |
| `currency` | 3-letter ISO currency code |

```python
from iso20022_quality.spark import validate_payments, partition_quality

bronze = spark.table("bronze.iso20022_payments")
quality = validate_payments(bronze, profile="sepa_sct")
valid, quarantine = partition_quality(quality)
valid.write.format("delta").mode("append").saveAsTable("silver.iso20022_payments")
quarantine.write.format("delta").mode("append").saveAsTable("ops.iso20022_quarantine")
```

`dq_errors: array<string>`, `dq_warnings: array<string>`, and `dq_valid: boolean` are
added; original columns are preserved. `NOTPROVIDED` gets a warning, not a false
rejection. The Spark IBAN checksum uses native SQL higher-order functions, not a
Python per-record UDF. Production jobs should partition by ingestion date and record
batch provenance, and write via idempotent merge rather than unconditional append.

For reconciliation at scale, supply a unique `payment_id` and a unique `entry_id`
plus canonical statement columns (`end_to_end_id`, `account_iban`, signed `amount`,
`currency`, `status`) and use:

```python
from iso20022_quality.spark import reconcile_spark
comparison = reconcile_spark(silver_payments, silver_bank_entries)
comparison.groupBy("reconciliation_status").count().show()
```

The implementation aggregates candidate entries *before* joining to payments to
avoid multiplying payment rows. A unique end-to-end reference is **not** assumed;
ambiguous references are explicitly reported. For performance, use physical
partitioning and bank/date constraints in your caller when querying large datasets.

## How it differs from existing ISO 20022 libraries

Many Python packages already generate or parse ISO messages, or validate XSD.
Examples include [pain001](https://github.com/sebastienrousseau/pain001).
This project focuses on **operational discrepancies and data-platform integration**:
conservative cross-message reconciliation, quarantine decisions, privacy-conscious
readiness summaries, and Spark SQL-native canonical-table validation. It is designed
to **complement**, not replace, an XML/XSD library.

## Limitations / planned milestones

1. Official XSD / TVS conformance hooks using legitimately sourced schema files
   (not redistributed without verifying the applicable terms).
2. Additional production formats: `camt.054` notifications,
   recurring return/reversal handling, bank-specific message variants.
3. Rule packs keyed to EPC guideline publication and bank profile, with provenance.
4. Per-transaction details inside aggregated camt entries (no false allocation of
   entry amount), better multi-day and partial settlement reconciliation.
5. Deduplication/idempotence, schema evolution and partition-aware benchmarks with
   measured Spark runtimes on a supported Databricks runtime.
6. XML batches >16 MiB via controlled streaming ingestion and multi-file orchestration.

## Ingestion idempotency

Use `file_receipt` and `detect_replays` with a database-backed receipt ledger to
recognize exact replays and conflicting replacement payloads before Silver writes.
The receipt ledger and Silver/Quarantine writes must share an atomic transaction or
idempotent merge key; a Python hash alone **does not** deliver exactly-once semantics.

## Privacy and security

- No real customer data or accounts are included, and the CLI emits aggregate
  counts only. Sample IBANs are published standard test values.
- XML is parsed using `defusedxml` to prevent entity expansion and has a 16 MiB
  per-document limit. Invalid documents raise exceptions rather than being treated
  as clean records.
- Matching does **not** prove settlement. `BOOK` is only a booked bank-statement
  status as observed in supplied data; never trigger payments or irreversible actions
  based on matches.
- Avoid logging raw XML, transaction references and account identifiers in production;
  store quarantine rows with your organization's RBAC, retention and encryption rules.

## Development

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check src tests examples
```

Spark tests in `tests/test_spark_optional.py` are skipped when PySpark is not installed.
Do not interpret a successful Python test suite as proving Spark integration or
EPC conformance. See `LICENSE` for the Apache-2.0 project license; no ISO/EPC
specification text or schema files are bundled.
