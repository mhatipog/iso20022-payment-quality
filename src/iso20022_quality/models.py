"""Immutable canonical records and diagnostics for reproducible pipelines."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Diagnostic:
    code: str
    level: str  # error | warning
    scope: str  # message | transaction | entry | statement
    index: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class Payment:
    message_id: str
    payment_info_id: str
    end_to_end_id: str
    instruction_id: str
    debtor_iban: str
    creditor_iban: str
    amount: Decimal | None
    currency: str
    execution_date: str
    issues: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class PaymentFile:
    version: str
    message_id: str
    payments: tuple[Payment, ...]
    diagnostics: tuple[Diagnostic, ...]

    def partition(self) -> tuple[tuple[Payment, ...], tuple[Payment, ...]]:
        """File-integrity errors quarantine the whole batch; row errors quarantine their row."""
        bad_file = any(d.level == "error" and d.scope == "message" for d in self.diagnostics)
        accepted, quarantined = [], []
        for payment in self.payments:
            (
                quarantined
                if bad_file or any(i.level == "error" for i in payment.issues)
                else accepted
            ).append(payment)
        return tuple(accepted), tuple(quarantined)


@dataclass(frozen=True)
class StatementEntry:
    statement_id: str
    account_iban: str
    entry_reference: str
    end_to_end_id: str
    amount: Decimal | None  # signed: DBIT negative, CRDT positive
    currency: str
    status: str
    booking_date: str
    issues: tuple[Diagnostic, ...] = ()
    reversal: bool = False
    bank_transaction_code: str = ""
    transaction_count: int = 0


@dataclass(frozen=True)
class Statement:
    version: str
    entries: tuple[StatementEntry, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class Reconciliation:
    payment: Payment
    status: str
    entry: StatementEntry | None = None
    detail: str = ""


@dataclass(frozen=True)
class PaymentStatus:
    """An observed pain.002 status, not a settlement guarantee."""

    message_id: str
    original_message_id: str
    original_payment_info_id: str
    end_to_end_id: str
    original_instruction_id: str
    status: str
    reason_codes: tuple[str, ...] = ()
    issues: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class StatusReport:
    version: str
    message_id: str
    original_message_id: str
    statuses: tuple[PaymentStatus, ...]
    diagnostics: tuple[Diagnostic, ...]
