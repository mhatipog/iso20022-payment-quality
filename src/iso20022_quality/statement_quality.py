"""Explicit, conservative statement arithmetic checks for camt.053.001.08.

Do not treat an individual page as an entire statement. Unbooked entries, absent
balances and inconsistent currencies make a statement *not assessable* rather
than a false positive for a balance mismatch.
"""

from dataclasses import dataclass
from decimal import Decimal

from .xml import CAMT08, _all, _decimal, _find, _root, _text


@dataclass(frozen=True)
class BalanceAudit:
    statement_id: str
    currency: str
    opening: Decimal | None
    closing: Decimal | None
    net_booked: Decimal | None
    difference: Decimal | None
    status: str  # BALANCED | DIFFERENCE | NOT_ASSESSABLE
    reason: str = ""


def _balance(stmt, code: str) -> tuple[Decimal | None, str]:
    values = []
    for bal in _all(stmt, "Bal", CAMT08):
        if _text(bal, "Tp/CdOrPrtry/Cd", CAMT08) != code:
            continue
        amt = _find(bal, "Amt", CAMT08)
        currency = amt.get("Ccy", "") if amt is not None else ""
        value = _decimal((amt.text or "").strip()) if amt is not None else None
        direction = _text(bal, "CdtDbtInd", CAMT08)
        if value is None or direction not in ("CRDT", "DBIT"):
            return None, ""
        values.append((value if direction == "CRDT" else -value, currency))
    if len(values) != 1:
        return None, ""
    return values[0]


def audit_camt053_balances(data: bytes | str) -> tuple[BalanceAudit, ...]:
    """Check OPBD + sum(booked entries) == CLBD where the statement is complete.

    A statement's pagination must have a single final page; incomplete/fragmented
    pages cannot safely be balanced. This is an arithmetic signal only, not a
    certification of financial completeness or clearing/settlement.
    """
    root = _root(data, CAMT08, "camt.053.001.08")
    report = _find(root, "BkToCstmrStmt", CAMT08)
    if report is None:
        raise ValueError("Missing BkToCstmrStmt payload")
    results = []
    for stmt in _all(report, "Stmt", CAMT08):
        stmt_id = _text(stmt, "Id", CAMT08)
        opening, opening_ccy = _balance(stmt, "OPBD")
        closing, closing_ccy = _balance(stmt, "CLBD")
        currency = opening_ccy or closing_ccy or _text(stmt, "Acct/Ccy", CAMT08)
        reason = ""
        if opening is None or closing is None:
            reason = "MISSING_UNIQUE_BOOKED_BALANCES"
        elif not currency or opening_ccy != closing_ccy:
            reason = "BALANCE_CURRENCY_MISMATCH"
        # A statement page with LastPgInd=false cannot establish complete movement.
        elif _text(stmt, "StmtPgntn/LastPgInd", CAMT08).lower() == "false" or (
                _text(stmt, "StmtPgntn/PgNb", CAMT08) not in ("", "1")):
            reason = "PAGINATED_OR_INCOMPLETE_STATEMENT"
        movement = Decimal("0")
        for entry in _all(stmt, "Ntry", CAMT08):
            amount = _find(entry, "Amt", CAMT08)
            value = _decimal((amount.text or "").strip()) if amount is not None else None
            entry_ccy = amount.get("Ccy", "") if amount is not None else ""
            status = _text(entry, "Sts/Cd", CAMT08) or _text(entry, "Sts", CAMT08)
            direction = _text(entry, "CdtDbtInd", CAMT08)
            if status != "BOOK" or value is None or value < 0 or entry_ccy != currency or (
                    direction not in ("CRDT", "DBIT")):
                reason = reason or "INCOMPLETE_OR_MIXED_BOOKINGS"
                continue
            movement += value if direction == "CRDT" else -value
        if reason:
            results.append(BalanceAudit(stmt_id, currency, opening, closing, None,
                                        None, "NOT_ASSESSABLE", reason))
        else:
            difference = closing - opening - movement
            results.append(BalanceAudit(stmt_id, currency, opening, closing,
                                        movement, difference,
                                        "BALANCED" if difference == 0 else "DIFFERENCE"))
    return tuple(results)
