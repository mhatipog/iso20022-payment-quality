"""Conservative, one-to-one payment to booked-bank-entry candidate matching."""

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Iterable

from .iban import normalize_iban
from .models import Payment, Reconciliation, StatementEntry


def reconcile(payments: Iterable[Payment], entries: Iterable[StatementEntry]) -> tuple[Reconciliation, ...]:
    """Match debits to credit-transfer instructions by reference AND debtor account.

    A match is bookkeeping evidence, not proof of final settlement. Ambiguous references
    never pick an arbitrary winner. NOTPROVIDED is not a usable payment key.
    """
    payments = tuple(payments)
    by_key: dict[tuple[str, str], list[StatementEntry]] = defaultdict(list)
    for entry in entries:
        if entry.end_to_end_id and entry.end_to_end_id != "NOTPROVIDED" and entry.account_iban:
            key = (entry.end_to_end_id, normalize_iban(entry.account_iban))
            by_key[key].append(entry)
    payment_counts = Counter(
        (p.end_to_end_id, normalize_iban(p.debtor_iban)) for p in payments
        if p.end_to_end_id and p.end_to_end_id != "NOTPROVIDED" and p.debtor_iban
    )
    results = []
    for payment in payments:
        key = (payment.end_to_end_id, normalize_iban(payment.debtor_iban))
        if not payment.end_to_end_id or payment.end_to_end_id == "NOTPROVIDED" or not payment.debtor_iban:
            results.append(Reconciliation(payment, "UNMATCHABLE_REFERENCE"))
            continue
        candidates = by_key.get(key, [])
        if not candidates:
            results.append(Reconciliation(payment, "NO_BOOKING_FOUND"))
        elif len(candidates) > 1 or payment_counts[key] > 1:
            results.append(Reconciliation(payment, "AMBIGUOUS_MATCH", detail="Reference is not unique within account"))
        else:
            entry = candidates[0]
            if payment.amount is None or entry.amount is None:
                status = "INVALID_AMOUNT"
            elif payment.currency != entry.currency:
                status = "CURRENCY_MISMATCH"
            elif entry.amount >= Decimal(0):
                status = "DIRECTION_MISMATCH"
            elif entry.amount != -payment.amount:
                status = "AMOUNT_MISMATCH"
            elif entry.reversal or "REVERSAL_REQUIRES_REVIEW" in {d.code for d in entry.issues}:
                status = "REVERSAL_REQUIRES_REVIEW"
            elif "RETURN_REQUIRES_REVIEW" in {d.code for d in entry.issues}:
                status = "RETURN_REQUIRES_REVIEW"
            elif entry.status != "BOOK":
                status = "NOT_BOOKED"
            elif any(d.level == "error" for d in entry.issues + payment.issues):
                status = "INVALID_SOURCE_RECORD"
            else:
                status = "MATCHED"
            results.append(Reconciliation(payment, status, entry))
    return tuple(results)
