"""Regression tests preventing false-positive payment matches."""

from dataclasses import replace
from pathlib import Path

import pytest

from iso20022_quality import link_payment_statuses, parse_camt053, parse_pain001, reconcile
from iso20022_quality.models import Diagnostic, PaymentStatus, StatusReport

FIX = Path(__file__).parent / "fixtures"
PAIN = (FIX / "pain09.xml").read_bytes()
CAMT = (FIX / "camt08.xml").read_bytes()


@pytest.mark.parametrize("bad", [b"1E2", b"+100", b"-0", b"NaN", b"Infinity", b"1,00"])
def test_xml_amount_rejects_exponents_and_shortcuts(bad):
    xml = PAIN.replace(b">100.00</InstdAmt>", b">" + bad + b"</InstdAmt>")
    parsed = parse_pain001(xml)
    assert "INVALID_AMOUNT" in {x.code for x in parsed.payments[0].issues}
    assert len(parsed.partition()[1]) == 3


def test_invalid_payment_is_not_marked_as_matched():
    p = parse_pain001(PAIN).payments[0]
    p = replace(p, issues=(Diagnostic("INVALID_CREDITOR_IBAN", "error", "transaction"),))
    e = parse_camt053(CAMT).entries[0]
    assert reconcile([p], [e])[0].status == "INVALID_SOURCE_RECORD"


def test_aggregate_and_return_are_not_matched():
    p = parse_pain001(PAIN).payments[0]
    e = parse_camt053(CAMT).entries[0]
    assert reconcile([p], [replace(e, transaction_count=3)])[0].status == (
        "AGGREGATED_ENTRY_NOT_MATCHABLE"
    )
    returned = replace(e, bank_transaction_code="PMNT/ICDT/ARET")
    assert reconcile([p], [returned])[0].status == "RETURN_REQUIRES_REVIEW"


def test_duplicate_reference_unqualified_status_is_ambiguous():
    p = replace(parse_pain001(PAIN).payments[0], instruction_id="INSTRUCTION-1")
    other = replace(p, instruction_id="INSTRUCTION-2")
    report = StatusReport(
        "pain.002.001.10", "report-id", p.message_id,
        (PaymentStatus("report-id", p.message_id, p.payment_info_id,
                       p.end_to_end_id, "", "ACCP"),), (),
    )
    assert [x.state for x in link_payment_statuses([p, other], [report])] == [
        "AMBIGUOUS_STATUS_REFERENCE", "AMBIGUOUS_STATUS_REFERENCE"
    ]
    report = replace(
        report, statuses=(replace(report.statuses[0], original_instruction_id=p.instruction_id),)
    )
    assert [x.state for x in link_payment_statuses([p, other], [report])] == [
        "OBSERVED", "NO_TRANSACTION_STATUS"
    ]


def test_statement_rejects_exponent_lexical_amount():
    entries = parse_camt053(CAMT.replace(b">100.00</Amt>", b">1E2</Amt>")).entries
    assert entries[0].amount is None
    assert any(d.code == "INVALID_ENTRY_AMOUNT" for d in entries[0].issues)
