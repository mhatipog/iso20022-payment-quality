# ISO 20022 Payment Quality

**Conservative banking-data validation, reconciliation and migration evidence for Python and Apache Spark.**

[Architecture](docs/architecture.md) · [Offline verification](docs/verification.md) · [Benchmarks](docs/benchmarks.md) · [Production boundaries](docs/production-readiness.md) · [Bank sample provenance](docs/bank-cases.md) · [Contributing](CONTRIBUTING.md)

**Status: experimental 0.3.0 (public source, not a certified payment processor).** The repository includes synthetic fixtures, runnable demos, regression tests and a reproducible Spark benchmark. It does not bundle customer data, licensed EPC/ISO schemas, banking credentials, or a Databricks workspace.

## The problem it solves

During payment-system migrations, syntactically valid files may still contain missing transactions, inconsistent totals, duplicated identifiers or misleading bank statements. This project separates **what the supplied data prove** from **what still needs investigation**. It is a data-quality component—not an API for sending payments.

| Capability | Entry point | Current scope |
| --- | --- | --- |
| ISO payment file checks | `parse_pain001` | `pain.001.001.09`, counts, control sums, SEPA-oriented checks |
| Bank statements | `parse_camt053` | `camt.053.001.08`, statuses, aggregated entries, reversal and return markers |
| Payment status evidence | `parse_pain002`, `link_payment_statuses` | `pain.002.001.10`, transaction-level observations, no settlement inference |
| Python reconciliation | `reconcile` | Account + EndToEndId, conservative ambiguity and exception handling |
| Spark validation and reconciliation | `validate_payments`, `reconcile_spark` | Canonical DataFrames, no Python row UDFs, optional verified matching cohorts |
| Migration readiness | `assess_readiness` | Redacted aggregate diagnostic counts |
| Migration acceptance checks | `assess_migration_gate` | Bounded Python objects + **independent** source-system control totals |
| Duplicate file detection | `file_receipt`, `detect_replays` | Caller-managed receipt records, **not** transactional exactly-once delivery |

Only the exact message versions above are parsed. XML extraction is **not** complete XSD validation or EPC implementation-guideline conformance. The `sepa_sct` profile is an operational subset, not proof of SEPA acceptance. A booked debit is **not** proof of final settlement.

## Reproduce offline

Requires Python 3.10+ and a checkout of this repository:

```bash
python -m pip install -e '.[dev]'
python examples/demo.py
python examples/migration_acceptance.py
python -m iso20022_quality.cli --payment tests/fixtures/pain09.xml --statement tests/fixtures/camt08.xml
python scripts/verify.py
```

No network calls, accounts or external bank services are required by these demos and tests **after dependencies have been installed**. The synthetic payment-file demo yields three accepted instructions: one matched, one amount mismatch and one without a booking. The migration-acceptance example first blocks incomplete evidence, then passes a separately constructed, explicitly synthetic corrected case. Never rewrite actual bank evidence in this manner.

For an installed-only package (without repository fixtures), use `iso20022-quality --help` or import `iso20022_quality`. Examples and fixtures are repository assets, **not** files shipped inside the wheel.

## Example: distinguish a valid subset from a complete migration

```python
from decimal import Decimal
from iso20022_quality import MigrationControls, assess_migration_gate

# These MUST come from a separately controlled source inventory, not the
# ISO documents being checked. Both datasets must describe the same cohort.
controls = MigrationControls(
    reference="LEGACY-AUDIT-EXPORT-2026-10",
    payment_count=1000,
    payment_total=Decimal("125000.00"),
    statement_entry_count=1000,
    statement_debit_total=Decimal("125000.00"),
)
report = assess_migration_gate(parsed_payment_files, parsed_statements, controls)
print(report.decision, report.blocking_codes)
```

The gate fails closed on quarantined records, unaccounted statement entries, incorrect totals, and unresolved reconciliation outcomes. `PASS_TECHNICAL_CHECKS` **does not authorize a production migration, payment release or settlement claim**. The source controls' true independence and cohort completeness must be established outside the library.

## Spark and Databricks

```bash
python -m pip install -e '.[spark,dev]'
python scripts/verify.py --spark
```

```python
from iso20022_quality.spark import partition_quality, reconcile_spark, validate_payments

quality = validate_payments(canonical_payments, profile="sepa_sct")
valid, quarantined = partition_quality(quality)
comparison = reconcile_spark(
    valid, canonical_bank_entries,
    scope_columns=("reconciliation_cohort",),
)
```

Both inputs must contain the **same independently checked cohort field**. Blank scope values are not matchable; account/date windows must reflect real banking cutoffs and booking practice. Input `payment_id` and `entry_id` must be stable and unique. The default `check_id_uniqueness=True` is conservative. Never turn that check off without an upstream enforced uniqueness contract.

The [Databricks example](examples/databricks.py) is **read-only**: it demonstrates quality checks, but deliberately does not perform unsafe unconditional Delta appends. The caller must implement controlled XML ingestion, durable IDs, idempotent merges, quarantine access controls, audit and replay recovery. The built-in XML parser is bounded to 16 MiB per document and is not a distributed XML input connector.

## Evidence and performance

The [reproducible benchmark](docs/benchmarks.md) processed **one million synthetic canonical Spark payments** in 14.76–20.64 seconds (clean workloads) and 14.40 seconds (adversarial key skew/exception workload) on GitHub-hosted Spark `local[2]`. Classification counts were independently asserted. These measurements **exclude XML, XSD, Delta, Databricks, real bank data and network I/O**; they are not production performance or cost guarantees.

Run the large synthetic tests through the manually triggered [Spark scale workflow](.github/workflows/benchmark-scale.yml). Default CI exercises offline Python, wheel packaging and small Spark integration. The opt-in live [public bank smoke test](examples/public_bank_smoke.py) depends on external documentation availability and is not part of the normal green CI gate.

## Project map

- [docs/architecture.md](docs/architecture.md) — interfaces, trust boundaries, data lineage and invariants
- [docs/verification.md](docs/verification.md) — one-command tests, coverage scope, CI and release verification
- [docs/benchmarks.md](docs/benchmarks.md) — measured configurations, observed results and raw workflow logs
- [docs/production-readiness.md](docs/production-readiness.md) — missing controls and deployment prerequisites
- [docs/bank-cases.md](docs/bank-cases.md) — provenance and limitations of external bank samples
- [CONTRIBUTING.md](CONTRIBUTING.md) — reproducible changes, regression expectations and safe example data
- [CHANGELOG.md](CHANGELOG.md) — tested changes, release boundaries and historical milestones
- [SECURITY.md](SECURITY.md) — responsible vulnerability reporting
- [PUBLISHING.md](PUBLISHING.md) — publication state and release checklist

Apache-2.0 licensed. This repository complements, and does not replace, banking schema validators, bank-side confirmation, fraud controls or regulatory assurance.
