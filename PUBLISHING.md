# Publication, release and handoff

**Current public repository:** https://github.com/mhatipog/iso20022-payment-quality

The repository is already public. Earlier private staging was temporary; do not
repeat those steps. The code is currently an **experimental 0.3.0 development
package**, not a certified or published PyPI distribution. Do not imply that a
green CI run establishes EPC compliance, banking production readiness or a
payment execution guarantee.

## Reproduce a checkout

```bash
python -m pip install -e '.[dev]'
python scripts/verify.py
python examples/migration_acceptance.py
```

For Spark integration, `python -m pip install -e '.[spark,dev]'` followed by
`python scripts/verify.py --spark`. The offline suite and checked-in fixtures
require no bank endpoints. External bank documentation is an optional,
network-dependent, manually invoked smoke check.

## Before creating a versioned release

1. Check the [verification guide](docs/verification.md), functional CI and packaging
   smoke from the **exact proposed release commit**; review changes and dependencies.
2. Confirm the README version and `pyproject.toml` version agree, and that the
   changelog documents functional changes and limitations.
3. Reproduce both offline demos; review synthetic fixtures, commit history and
   release artifacts for secrets or confidential information.
4. Run the version-compatible Spark jobs. The million-record benchmark is manually
   triggered; record GitHub Action job links and runtime configuration.
5. Obtain authorization and licenses before incorporating EPC/ISO specifications,
   official schema assets or bank-owned examples. None is bundled here.
6. Tag only the approved, tested commit and publish a GitHub release with installation,
   supported versions, actual test results and known limitations.
7. **PyPI is not published yet.** A later PyPI release must use approved account
   permissions, clean build artifacts and verified release provenance; do not claim
   installation via PyPI until uploaded and independently verified.

## Production deployment remains separate

A deployment needs trusted XML ingestion, official scheme/bank conformance checks,
independent controls, complete reconciliation cohorts, atomic/idempotent storage,
access controls, audit logs, rollback testing and institution approval.
See [production-readiness](docs/production-readiness.md).

Never use the library to initiate, approve or move payments.
