# Contributing

We welcome concrete, reproducible improvements to banking data-quality checks,
reconciliation safety, migration evidence and practical Spark performance.

## Getting started

```bash
python -m pip install -e '.[dev]'
python scripts/verify.py
```

If changing Spark logic, also install `.[spark,dev]` and run
`python scripts/verify.py --spark`. The same offline checks run in CI.
See [verification details](docs/verification.md).

## A useful change includes

- A precise problem statement, affected message versions and an observable
  incorrect result or missing safety property.
- The smallest robust fix, an independently expected regression outcome,
  and negative/ambiguous cases where the answer must **not** be `MATCHED`.
- Updated user-facing docs and explicit limitations if behavior changes.
- Benchmarks with full data-generation recipe and workload/hardware metadata
  when claiming performance. Compare identical correctness criteria.
- Clearly synthetic or openly licensable fixtures; **never** customer files,
  secrets, raw IBANs from real people, production identifiers or leaked data.

Never introduce a payment-release side effect. Avoid logging raw XML or account
data. Report security vulnerabilities privately according to [SECURITY.md](SECURITY.md),
not through public exploit reports.

[Architecture](docs/architecture.md) documents the trust boundaries and
[production-readiness](docs/production-readiness.md) tracks deliberate omissions.
