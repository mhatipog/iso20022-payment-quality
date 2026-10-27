# Publication and safety checklist

Private staging was created through Repo Guardian on 27 October 2026. The release
is deliberately experimental and no proprietary customer/payment information is used.

Before enabling public visibility:

1. Transfer the exact tested source tree and verify the commit and CI.
2. Run `pytest -q` and, where available, `ruff check src tests examples`.
3. Run Spark integration with `pip install -e ".[spark,dev]"` and the full tests.
4. Run the opt-in `python examples/public_bank_smoke.py` against bank-published
   examples on an internet-connected runtime, then inspect limitations.
5. Review sample identifiers and Git history for leaked secrets or sensitive data.
6. Set PyPI URL and publish to PyPI only after a tagged release and packaging audit.

Official XSD and EPC/bank-specific conformance are independent; no claim of
production payment execution safety or comprehensive regulatory certification.
