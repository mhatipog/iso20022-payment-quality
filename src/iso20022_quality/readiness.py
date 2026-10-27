"""Privacy-conscious aggregate data-quality and legacy-migration readiness summaries."""

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import PaymentFile, Statement
from .reconcile import reconcile


@dataclass(frozen=True)
class ReadinessReport:
    files: int
    payments: int
    accepted: int
    quarantined: int
    bank_entries: int
    quality_error_counts: dict[str, int]
    reconciliation_counts: dict[str, int]
    duplicate_reference_groups: int
    reference_coverage_pct: float
    matched_pct_of_accepted: float | None


def assess_readiness(files: Iterable[PaymentFile], statements: Iterable[Statement] = ()) -> ReadinessReport:
    """Report observable data quality, not regulatory compliance or migration certification.

    No account numbers, counterparty data or transaction-level identifiers in the report.
    Matching is restricted to accepted payments. Duplicate E2E IDs per originating IBAN
    are a risk *signal*, not by themselves a validation failure.
    """
    files = tuple(files)
    statements = tuple(statements)
    accepted, quarantined = [], []
    issues = Counter()
    for file in files:
        good, bad = file.partition()
        accepted.extend(good)
        quarantined.extend(bad)
        issues.update(x.code for x in file.diagnostics if x.level == "error")
        issues.update(x.code for p in file.payments for x in p.issues if x.level == "error")
    counts = Counter((p.debtor_iban, p.end_to_end_id) for p in accepted
                     if p.debtor_iban and p.end_to_end_id and p.end_to_end_id != "NOTPROVIDED")
    duplicates = sum(1 for n in counts.values() if n > 1)
    usable_refs = sum(bool(p.debtor_iban and p.end_to_end_id
                           and p.end_to_end_id != "NOTPROVIDED") for p in accepted)
    entries = [entry for statement in statements for entry in statement.entries]
    for statement in statements:
        issues.update(f"CAMT_{d.code}" for d in statement.diagnostics if d.level == "error")
        issues.update(f"CAMT_{d.code}" for entry in statement.entries
                      for d in entry.issues if d.level == "error")
    statuses = Counter(r.status for r in reconcile(accepted, entries)) if entries else Counter()
    denom = len(accepted)
    return ReadinessReport(
        files=len(files), payments=len(accepted) + len(quarantined),
        accepted=len(accepted), quarantined=len(quarantined), bank_entries=len(entries),
        quality_error_counts=dict(sorted(issues.items())),
        reconciliation_counts=dict(sorted(statuses.items())),
        duplicate_reference_groups=duplicates,
        reference_coverage_pct=round(100 * usable_refs / denom, 2) if denom else 0.0,
        matched_pct_of_accepted=(round(100 * statuses["MATCHED"] / denom, 2)
                                 if denom and statements else None),
    )
