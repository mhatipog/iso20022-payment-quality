# Verification and test coverage

[Home](../README.md) · [Architecture](architecture.md) · [Benchmarks](benchmarks.md)

## Fast, self-contained local check

From a repository checkout, with Python 3.10+:

```bash
python -m pip install -e '.[dev]'
python scripts/verify.py
```

This performs Ruff, the Python test suite with **measured coverage**, the
synthetic payment/demo, the independently controlled migration-acceptance
example and the CLI against checked-in fixtures. It makes no network calls
after dependencies are installed. The CLI and demo output is aggregate/synthetic.

The Python core coverage gate is **90% minimum**; a 27 October 2026 CI run measured **92% (60 tests)**. The Python coverage scope excludes `spark.py`, which runs in its own real
PySpark integration job. **Coverage is execution evidence, not a proof of
correctness**; it cannot certify XSD/EPC scheme compliance or true banking
settlement status.

For the Spark path:

```bash
python -m pip install -e '.[spark,dev]'
python scripts/verify.py --spark
```

The Spark tests exercise ANSI numeric failures, exact Decimal values, returns,
reversals, ambiguous references, missing entry IDs, quarantines and scoped
matching. CI uses Java 17 and a local Spark runtime. Real Databricks testing
remains a separate, documented production prerequisite.

## Independent packaging check

GitHub Actions builds a wheel and installs it in a fresh virtual environment
from **outside** the checkout. It checks the installed module, package metadata
and CLI. The examples and fixtures remain repo-only assets; they are intentionally
not included in the distribution wheel.

```bash
python -m build --wheel
```

The [publishing checklist](../PUBLISHING.md) describes tagging and release
verification. A tagged release or PyPI package should not be inferred from
a source branch or successful wheel build.

## Expensive or network-dependent checks

- [Spark scale workflow](../.github/workflows/benchmark-scale.yml) is manually
  triggered. Its data are generated synthetically within Spark.
- [Live bank sample smoke](../examples/public_bank_smoke.py) is opt-in.
  Bank documentation can change or time out, so it must not be substituted
  for the offline CI gate. It validates selected example extraction only.
- Official EPC/ISO conformance, bank acceptance testing, cost measurements and
  full end-to-end Databricks/Delta recovery tests **have not been completed**.

## Review of results

Check the CI summary and look for all of: Python tests and coverage, offline
examples, wheel smoke, Spark tests, and an assertion-checked 20k Spark run.
Keep any failed job visible. For performance claims, cite the exact action run
and machine/runtime configuration rather than claiming an SLA.
