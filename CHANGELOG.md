# Changelog

Project status: **experimental**. Versions describe the source package only,
unless a GitHub release or PyPI distribution is explicitly published.

## Unreleased — repository handoff

- Consolidated quickstart and trust-boundary documentation.
- Added offline smoke verification and coverage reporting, with a separate
  Spark integration gate and isolated wheel-install check.
- Clarified publication, security and production-readiness guidance.
- Made the illustrative Databricks example read-only; no append-on-replay path.

## 0.3.0 — 27 October 2026 (source package)

- Hardened numeric checks, duplicate identity handling, reconciliation cohorts,
  ambiguous references, returns, reversals and status association.
- Added independent control-total migration acceptance checks for bounded files.
- Added assertion-checked synthetic Spark benchmarks including million-row
  clean and adversarial scenarios; these are **not** banking production SLAs.
- Added offline fixtures and synthetic migration acceptance demonstration.

## 0.2.x — initial research prototypes

- Bounded ISO 20022 extraction, canonical record models, preliminary
  reconciliation and PySpark validation.
