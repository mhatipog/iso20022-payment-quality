"""Link pain.002 observations to payment instructions without inventing finality."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from .models import Payment, PaymentStatus, StatusReport


@dataclass(frozen=True)
class PaymentLifecycle:
    payment: Payment
    state: str
    observations: tuple[PaymentStatus, ...] = ()


def link_payment_statuses(
    payments: Iterable[Payment],
    reports: Iterable[StatusReport],
) -> tuple[PaymentLifecycle, ...]:
    """Associate only unambiguous transaction statuses with their original instruction.

    Group- and payment-information-level statuses are *not* propagated onto every
    transaction, because e.g. PART cannot describe any single transaction.
    Status history is returned in input order. No wall-clock ordering, retry
    resolution, or settlement claim is inferred.
    """
    payments = tuple(payments)
    seen = Counter((p.message_id, p.payment_info_id, p.end_to_end_id, p.instruction_id)
                   for p in payments)
    statuses: dict[tuple[str, str, str], list[PaymentStatus]] = defaultdict(list)
    for report in reports:
        for status in report.statuses:
            if status.end_to_end_id and status.end_to_end_id != "NOTPROVIDED":
                key = (status.original_message_id, status.original_payment_info_id,
                       status.end_to_end_id)
                statuses[key].append(status)
    results = []
    for payment in payments:
        key4 = (payment.message_id, payment.payment_info_id,
                payment.end_to_end_id, payment.instruction_id)
        if not payment.end_to_end_id or payment.end_to_end_id == "NOTPROVIDED":
            results.append(PaymentLifecycle(payment, "UNMATCHABLE_REFERENCE"))
            continue
        if seen[key4] > 1:
            results.append(PaymentLifecycle(payment, "AMBIGUOUS_PAYMENT_KEY"))
            continue
        candidate = statuses.get(key4[:3], ())
        matching = tuple(x for x in candidate
                         if not x.original_instruction_id or
                         x.original_instruction_id == payment.instruction_id)
        if len({x.original_instruction_id for x in matching if x.original_instruction_id}) > 1:
            results.append(PaymentLifecycle(payment, "AMBIGUOUS_STATUS_REFERENCE", matching))
        elif matching:
            results.append(PaymentLifecycle(payment, "OBSERVED", matching))
        else:
            results.append(PaymentLifecycle(payment, "NO_TRANSACTION_STATUS"))
    return tuple(results)
