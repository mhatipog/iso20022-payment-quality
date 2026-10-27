"""Conservative canonical extraction for specific ISO 20022 message versions.

Extracted records and operational diagnostics are deliberately NOT full XSD validation,
nor certification against an EPC implementation guideline or a bank-specific profile.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import fromstring

from .iban import is_valid_iban, normalize_iban
from .models import (Diagnostic, Payment, PaymentFile, PaymentStatus, StatusReport,
                     Statement, StatementEntry)

PAIN09 = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
CAMT08 = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
PAIN00210 = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.10"
MAX_XML_BYTES = 16 * 1024 * 1024  # intentionally bounded input; split oversized batches upstream


class UnsupportedMessage(ValueError):
    """An unsupported message version or envelope was supplied."""


def read_xml_file(path: str | Path, *, max_bytes: int = MAX_XML_BYTES) -> bytes:
    """Read a bounded XML file; disallow accidental multi-GB expansion in ET parsing."""
    with open(path, "rb") as file:
        data = file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("XML exceeds max_bytes; split or stream-source the batch first")
    return data


def _root(data: bytes | str, namespace: str, expected: str) -> Element:
    if len(data.encode("utf-8") if isinstance(data, str) else data) > MAX_XML_BYTES:
        raise ValueError("XML exceeds the 16 MiB safety limit")
    root = fromstring(data)  # rejects DTD entity expansion and external entities
    if root.tag != f"{{{namespace}}}Document":
        raise UnsupportedMessage(f"Expected ISO 20022 {expected} Document namespace")
    return root


def _find(node: Element | None, path: str, ns: str) -> Element | None:
    if node is None:
        return None
    return node.find("/".join(f"{{{ns}}}{segment}" for segment in path.split("/")))


def _all(node: Element | None, path: str, ns: str) -> list[Element]:
    if node is None:
        return []
    return node.findall("/".join(f"{{{ns}}}{segment}" for segment in path.split("/")))


def _text(node: Element | None, path: str, ns: str) -> str:
    field = _find(node, path, ns)
    return (field.text or "").strip() if field is not None else ""


def _decimal(raw: str) -> Decimal | None:
    try:
        num = Decimal(raw)
        return num if num.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _date_valid(raw: str) -> bool:
    if not raw:
        return False
    try:
        date.fromisoformat(raw)
        return True
    except ValueError:
        try:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False


def _issue(code: str, scope: str, index: int | None = None, *, level: str = "error", detail: str = "") -> Diagnostic:
    return Diagnostic(code, level, scope, index, detail)


def _check_summary(
    node: Element, ns: str, count: int, total: Decimal, scope: str, diagnostics: list[Diagnostic],
    *, required_count: bool = False
) -> None:
    declared = _text(node, "NbOfTxs", ns)
    if not declared and required_count:
        diagnostics.append(_issue("MISSING_TRANSACTION_COUNT", scope))
    elif declared and (not re.fullmatch(r"[0-9]{1,15}", declared) or int(declared) != count):
        diagnostics.append(_issue("TRANSACTION_COUNT_MISMATCH", scope))
    ctrl = _text(node, "CtrlSum", ns)
    if ctrl:
        actual = _decimal(ctrl)
        if actual is None or actual != total:
            diagnostics.append(_issue("CONTROL_SUM_MISMATCH", scope))


def parse_pain001(data: bytes | str, *, profile: str = "sepa_sct") -> PaymentFile:
    """Parse pain.001.001.09 credit transfers into canonical payment records.

    `sepa_sct` adds operational EUR / IBAN / amount checks, NOT the complete EPC rules.
    `base` retains generic ISO currency and account forms as far as extracted.
    File-level header mismatches quarantine all returned rows, never silently accepted.
    """
    if profile not in ("sepa_sct", "base"):
        raise ValueError("profile must be 'sepa_sct' or 'base'")
    root = _root(data, PAIN09, "pain.001.001.09")
    doc = _find(root, "CstmrCdtTrfInitn", PAIN09)
    if doc is None:
        raise UnsupportedMessage("Missing CstmrCdtTrfInitn payload")
    header = _find(doc, "GrpHdr", PAIN09)
    if header is None:
        raise UnsupportedMessage("Missing mandatory group header")
    message_id = _text(header, "MsgId", PAIN09)
    diagnostics: list[Diagnostic] = []
    if not message_id:
        diagnostics.append(_issue("MISSING_MESSAGE_ID", "message"))
    if not _date_valid(_text(header, "CreDtTm", PAIN09)):
        diagnostics.append(_issue("INVALID_CREATION_DATETIME", "message"))
    payments: list[Payment] = []
    for payment_info in _all(doc, "PmtInf", PAIN09):
        payment_info_id = _text(payment_info, "PmtInfId", PAIN09)
        debtor = normalize_iban(_text(payment_info, "DbtrAcct/Id/IBAN", PAIN09))
        execution_date = (_text(payment_info, "ReqdExctnDt/Dt", PAIN09)
                          or _text(payment_info, "ReqdExctnDt/DtTm", PAIN09))
        batch: list[Payment] = []
        for transaction in _all(payment_info, "CdtTrfTxInf", PAIN09):
            index = len(payments) + len(batch)
            issues: list[Diagnostic] = []
            def fail(
                condition: bool,
                code: str,
                *,
                target: list[Diagnostic] = issues,
                transaction_index: int = index,
            ) -> None:
                if condition:
                    target.append(_issue(code, "transaction", transaction_index))
            e2e = _text(transaction, "PmtId/EndToEndId", PAIN09)
            instr = _text(transaction, "PmtId/InstrId", PAIN09)
            creditor = normalize_iban(_text(transaction, "CdtrAcct/Id/IBAN", PAIN09))
            amount_node = _find(transaction, "Amt/InstdAmt", PAIN09)
            amount = _decimal((amount_node.text or "").strip()) if amount_node is not None else None
            currency = (amount_node.get("Ccy", "") if amount_node is not None else "").upper()
            fail(not e2e, "MISSING_END_TO_END_ID")
            if e2e == "NOTPROVIDED":
                issues.append(_issue("UNMATCHABLE_REFERENCE", "transaction", index,
                                     level="warning"))
            fail(amount is None or amount <= 0, "INVALID_AMOUNT")
            fail(not bool(re.fullmatch(r"[A-Z]{3}", currency)), "INVALID_CURRENCY")
            fail(bool(execution_date) and not _date_valid(execution_date), "INVALID_EXECUTION_DATE")
            if profile == "sepa_sct":
                fail(currency != "EUR", "SEPA_NON_EUR")
                fail(not is_valid_iban(debtor), "INVALID_DEBTOR_IBAN")
                fail(not is_valid_iban(creditor), "INVALID_CREDITOR_IBAN")
                fail(amount is not None and amount.as_tuple().exponent < -2,
                     "SEPA_AMOUNT_FRACTION")
                fail(not execution_date, "MISSING_EXECUTION_DATE")
            batch.append(Payment(message_id, payment_info_id, e2e, instr, debtor,
                                 creditor, amount, currency, execution_date, tuple(issues)))
        if not payment_info_id:
            diagnostics.append(_issue("MISSING_PAYMENT_INFO_ID", "message"))
        _check_summary(payment_info, PAIN09, len(batch),
                       sum((p.amount for p in batch if p.amount is not None), Decimal(0)),
                       "message", diagnostics)
        payments.extend(batch)
    if not payments:
        diagnostics.append(_issue("NO_TRANSACTIONS", "message"))
    _check_summary(header, PAIN09, len(payments),
                   sum((p.amount for p in payments if p.amount is not None), Decimal(0)),
                   "message", diagnostics, required_count=True)
    return PaymentFile("pain.001.001.09", message_id, tuple(payments), tuple(diagnostics))


def parse_camt053(data: bytes | str) -> Statement:
    """Parse camt.053.001.08 booked entries, preserving Ntry granularity.

    Do NOT fan out Ntry/Amt to each TxDtls; an entry can contain multiple transactions.
    Such aggregate entries are explicitly withheld from one-to-one matching.
    """
    root = _root(data, CAMT08, "camt.053.001.08")
    doc = _find(root, "BkToCstmrStmt", CAMT08)
    if doc is None:
        raise UnsupportedMessage("Missing BkToCstmrStmt payload")
    diagnostics: list[Diagnostic] = []
    entries: list[StatementEntry] = []
    for stmt in _all(doc, "Stmt", CAMT08):
        stmt_id = _text(stmt, "Id", CAMT08)
        account = normalize_iban(_text(stmt, "Acct/Id/IBAN", CAMT08))
        if not stmt_id:
            diagnostics.append(_issue("MISSING_STATEMENT_ID", "statement"))
        if account and not is_valid_iban(account):
            diagnostics.append(_issue("INVALID_STATEMENT_IBAN", "statement"))
        for entry in _all(stmt, "Ntry", CAMT08):
            idx = len(entries)
            issues: list[Diagnostic] = []
            amount_node = _find(entry, "Amt", CAMT08)
            amount = _decimal((amount_node.text or "").strip()) if amount_node is not None else None
            currency = (amount_node.get("Ccy", "") if amount_node is not None else "").upper()
            direction = _text(entry, "CdtDbtInd", CAMT08)
            status = _text(entry, "Sts/Cd", CAMT08) or _text(entry, "Sts", CAMT08)
            reference = _text(entry, "NtryRef", CAMT08)
            booked_on = _text(entry, "BookgDt/Dt", CAMT08) or _text(entry, "BookgDt/DtTm", CAMT08)
            transactions = _all(entry, "NtryDtls/TxDtls", CAMT08)
            reported_counts = [_text(d, "Btch/NbOfTxs", CAMT08)
                               for d in _all(entry, "NtryDtls", CAMT08)]
            count_values = [int(x) for x in reported_counts if x.isdigit()]
            transaction_count = max(len(transactions), max(count_values, default=0))
            reversal_raw = _text(entry, "RvslInd", CAMT08).lower()
            reversal = reversal_raw == "true"
            bank_tx_code = "/".join(x for x in (
                _text(entry, "BkTxCd/Domn/Cd", CAMT08),
                _text(entry, "BkTxCd/Domn/Fmly/Cd", CAMT08),
                _text(entry, "BkTxCd/Domn/Fmly/SubFmlyCd", CAMT08)) if x)
            if reversal_raw not in ("", "true", "false"):
                issues.append(_issue("INVALID_REVERSAL_FLAG", "entry", idx))
            e2e = (_text(transactions[0], "Refs/EndToEndId", CAMT08)
                   if len(transactions) == 1 and transaction_count <= 1 else "")
            if transaction_count > 1:
                issues.append(_issue("AGGREGATED_ENTRY_NOT_MATCHABLE", "entry", idx,
                                     level="warning"))
            if not e2e or e2e == "NOTPROVIDED":
                issues.append(_issue("MISSING_MATCH_REFERENCE", "entry", idx, level="warning"))
            if amount is None or amount < 0:
                issues.append(_issue("INVALID_ENTRY_AMOUNT", "entry", idx))
            if direction not in ("DBIT", "CRDT"):
                issues.append(_issue("INVALID_DIRECTION", "entry", idx))
            if not re.fullmatch(r"[A-Z]{3}", currency):
                issues.append(_issue("INVALID_CURRENCY", "entry", idx))
            if not status:
                issues.append(_issue("MISSING_BOOKING_STATUS", "entry", idx))
            if reversal:
                issues.append(_issue("REVERSAL_REQUIRES_REVIEW", "entry", idx,
                                     level="warning"))
            if bank_tx_code.endswith(("/ARET", "/RRTN")):
                issues.append(_issue("RETURN_REQUIRES_REVIEW", "entry", idx,
                                     level="warning"))
            if booked_on and not _date_valid(booked_on):
                issues.append(_issue("INVALID_BOOKING_DATE", "entry", idx))
            signed_amount = ((-amount if direction == "DBIT" else amount)
                             if amount is not None and direction in ("DBIT", "CRDT") else None)
            entries.append(StatementEntry(stmt_id, account, reference, e2e,
                                          signed_amount, currency, status, booked_on,
                                          tuple(issues), reversal,
                                          bank_tx_code, transaction_count))
    if not entries:
        diagnostics.append(_issue("NO_ENTRIES", "statement", level="warning"))
    return Statement("camt.053.001.08", tuple(entries), tuple(diagnostics))


def parse_pain002(data: bytes | str) -> StatusReport:
    """Read pain.002.001.10 transaction statuses without claiming funds have settled.

    The parser supports group-level, payment-information and transaction status
    observations. A missing TxInfAndSts is not a rejected transaction: group
    statuses are returned with an empty transaction reference instead.
    """
    ns = PAIN00210
    root = _root(data, ns, "pain.002.001.10")
    report = _find(root, "CstmrPmtStsRpt", ns)
    if report is None:
        raise UnsupportedMessage("Missing CstmrPmtStsRpt payload")
    header = _find(report, "GrpHdr", ns)
    message_id = _text(header, "MsgId", ns)
    original = _find(report, "OrgnlGrpInfAndSts", ns)
    original_msg = _text(original, "OrgnlMsgId", ns)
    diagnostics = []
    if not message_id:
        diagnostics.append(_issue("MISSING_MESSAGE_ID", "message"))
    if not original_msg:
        diagnostics.append(_issue("MISSING_ORIGINAL_MESSAGE_ID", "message"))
    statuses = []

    def reason_codes(node: Element) -> tuple[str, ...]:
        codes = []
        for reason in _all(node, "StsRsnInf", ns):
            code = _text(reason, "Rsn/Cd", ns) or _text(reason, "Rsn/Prtry", ns)
            if code:
                codes.append(code)
        return tuple(codes)

    group_status = _text(original, "GrpSts", ns)
    if group_status:
        statuses.append(PaymentStatus(message_id, original_msg, "", "", "",
                                      group_status, reason_codes(original)))
    for batch in _all(report, "OrgnlPmtInfAndSts", ns):
        batch_id = _text(batch, "OrgnlPmtInfId", ns)
        batch_status = _text(batch, "PmtInfSts", ns)
        if batch_status:
            statuses.append(PaymentStatus(message_id, original_msg, batch_id, "", "",
                                          batch_status, reason_codes(batch)))
        for index, tx in enumerate(_all(batch, "TxInfAndSts", ns)):
            e2e = _text(tx, "OrgnlEndToEndId", ns)
            instr = _text(tx, "OrgnlInstrId", ns)
            status = _text(tx, "TxSts", ns)
            issues = () if status else (_issue("MISSING_TRANSACTION_STATUS", "transaction", index),)
            statuses.append(PaymentStatus(message_id, original_msg, batch_id, e2e, instr,
                                          status, reason_codes(tx), issues))
    if not statuses:
        diagnostics.append(_issue("NO_STATUS_OBSERVATIONS", "message", level="warning"))
    return StatusReport("pain.002.001.10", message_id, original_msg,
                        tuple(statuses), tuple(diagnostics))
