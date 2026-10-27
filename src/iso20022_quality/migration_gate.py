"""An independently controlled *technical* migration acceptance gate.

The caller supplies controls from a separate source-system inventory. This
module has no payment-authorising, settlement or Delta write side effects.
A PASS means only that specified completeness and reconciliation checks
passed for the supplied, explicitly scoped evidence.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from .models import PaymentFile, Statement
from .reconcile import reconcile


@dataclass(frozen=True)
class MigrationControls:
    """Independent reference totals for one COMPLETE reconciliation cohort.

    Reference controls MUST NOT be calculated from the very ISO files being
    checked. Only a source-system export/audit ledger can supply independent
    evidence. statement_* refer to a pre-scoped bank transaction population,
    not a bank's entire account statement including unrelated entries.
    """

    reference: str
    payment_count: int
    payment_total: Decimal
    statement_entry_count: int
    statement_debit_total: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError("An external evidence reference is required")
        for field in ("payment_count", "statement_entry_count"):
            number = getattr(self, field)
            if type(number) is not int or number < 1:
                raise ValueError(f"{field} must be a positive integer")
        for field in ("payment_total", "statement_debit_total"):
            number = getattr(self, field)
            if not isinstance(number, Decimal) or not number.is_finite() or number <= 0:
                raise ValueError(f"{field} must be a finite positive Decimal")


@dataclass(frozen=True)
class MigrationGateResult:
    """Privacy-conscious result: no IBANs, payment identifiers or customer data."""

    decision: str  # PASS_TECHNICAL_CHECKS | BLOCKED
    blocking_codes: tuple[str, ...]
    payment_count: int
    accepted_count: int
    quarantined_count: int
    statement_entry_count: int
    matched_count: int
    payment_total: Decimal
    matched_debit_total: Decimal
    reconciliation_counts: dict[str, int]


def assess_migration_gate(
    files: Iterable[PaymentFile],
    statements: Iterable[Statement],
    controls: MigrationControls,
) -> MigrationGateResult:
    """Check a fully-scoped payment migration against independent control totals.

    Deny by default: ANY quarantine, unmatched/ambiguous reference, unexpected
    statement entry, count or amount discrepancy, or reported source error
    blocks PASS. Only accepted instructions can match bank statement debits.

    Controls' independence and scope are governance responsibilities, not
    something this function can cryptographically prove.
    """
    if not isinstance(controls, MigrationControls):
        raise TypeError("controls must be a MigrationControls instance")
    files = tuple(files)
    statements = tuple(statements)
    payments = [payment for file in files for payment in file.payments]
    entries = [entry for statement in statements for entry in statement.entries]
    accepted = []
    quarantined = []
    reasons: set[str] = set()

    if not files or not statements:
        reasons.add("MISSING_SOURCE_EVIDENCE")

    for file in files:
        good, bad = file.partition()
        accepted.extend(good)
        quarantined.extend(bad)
        if any(d.level == "error" for d in file.diagnostics):
            reasons.add("PAYMENT_FILE_INTEGRITY_ERROR")
    if quarantined:
        reasons.add("QUARANTINED_PAYMENTS")
    if any(
        d.level == "error"
        for statement in statements
        for d in statement.diagnostics
    ) or any(
        d.level == "error" for entry in entries for d in entry.issues
    ):
        reasons.add("STATEMENT_QUALITY_ERROR")

    # EndToEndId/amount/account alone cannot prove the identity of each bank
    # entry. ISO statements can omit NtryRef; callers must provide a stable,
    # source-derived canonical entry identity before migration acceptance.
    # NtryRef is unique only within its statement, not across all statements.
    evidence_keys = [
        (entry.statement_id.strip(), entry.entry_reference.strip())
        for entry in entries
        if entry.statement_id and entry.entry_reference
        and entry.statement_id.strip() and entry.entry_reference.strip()
    ]
    if len(evidence_keys) != len(entries):
        reasons.add("MISSING_STATEMENT_ENTRY_ID")
    if any(count > 1 for count in Counter(evidence_keys).values()):
        reasons.add("DUPLICATE_STATEMENT_ENTRY_ID")

    if len(payments) != controls.payment_count:
        reasons.add("SOURCE_PAYMENT_COUNT_MISMATCH")
    if len(entries) != controls.statement_entry_count:
        reasons.add("SOURCE_STATEMENT_COUNT_MISMATCH")

    valid_amounts = all(
        isinstance(p.amount, Decimal) and p.amount.is_finite() and p.amount > 0
        for p in payments
    )
    if not valid_amounts:
        reasons.add("INVALID_PAYMENT_AMOUNT")
    payment_total = sum(
        (p.amount for p in payments
         if isinstance(p.amount, Decimal) and p.amount.is_finite()),
        Decimal(0),
    )
    if payment_total != controls.payment_total:
        reasons.add("SOURCE_PAYMENT_TOTAL_MISMATCH")

    results = reconcile(accepted, entries) if accepted and entries else ()
    counts = Counter(r.status for r in results)
    matched = tuple(r for r in results if r.status == "MATCHED")
    if len(matched) != len(accepted):
        reasons.add("RECONCILIATION_EXCEPTIONS")
    # A scoped bank feed cannot have unexplained extra entries and still PASS.
    # This also detects duplicate/return entries that are not assigned to
    # exactly one validated instruction.
    if len(matched) != len(entries):
        reasons.add("UNACCOUNTED_STATEMENT_ENTRIES")
    if not accepted or not entries:
        reasons.add("EMPTY_ACCEPTED_SCOPE")

    matched_debit_total = sum((-r.entry.amount for r in matched), Decimal(0))
    if matched_debit_total != controls.statement_debit_total:
        reasons.add("SOURCE_STATEMENT_TOTAL_MISMATCH")
    if matched_debit_total != payment_total:
        reasons.add("MATCHED_VALUE_CONSERVATION_FAILED")

    return MigrationGateResult(
        decision="BLOCKED" if reasons else "PASS_TECHNICAL_CHECKS",
        blocking_codes=tuple(sorted(reasons)),
        payment_count=len(payments),
        accepted_count=len(accepted),
        quarantined_count=len(quarantined),
        statement_entry_count=len(entries),
        matched_count=len(matched),
        payment_total=payment_total,
        matched_debit_total=matched_debit_total,
        reconciliation_counts=dict(sorted(counts.items())),
    )
