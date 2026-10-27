from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from iso20022_quality import (
    is_valid_iban, normalize_iban, parse_camt053, parse_pain001, read_xml_file, reconcile,
)
from defusedxml.common import EntitiesForbidden
from xml.etree.ElementTree import ParseError
from iso20022_quality.xml import UnsupportedMessage

FIXTURES = Path(__file__).parent / "fixtures"
PAIN = read_xml_file(FIXTURES / "pain09.xml")
CAMT = read_xml_file(FIXTURES / "camt08.xml")


def test_iban_known_checksums_and_normalization():
    assert is_valid_iban("BE68 5390 0754 7034")
    assert is_valid_iban("NL91ABNA0417164300")
    assert normalize_iban("be68 5390 0754 7034") == "BE68539007547034"
    assert not is_valid_iban("BE68539007547035")
    assert not is_valid_iban("BE6853900754703")
    assert not is_valid_iban("BE68-5390-0754-7034")
    assert not is_valid_iban("")


def test_valid_fixture_and_control_sum_exact():
    result = parse_pain001(PAIN)
    good, quarantine = result.partition()
    assert len(good) == 3 and len(quarantine) == 0
    assert not result.diagnostics
    assert [p.amount for p in good] == [Decimal("100"), Decimal("50"), Decimal("20")]


def test_group_and_batch_count_mismatches_quarantine_whole_file():
    result = parse_pain001(PAIN.replace(b"<NbOfTxs>3</NbOfTxs>", b"<NbOfTxs>2</NbOfTxs>"))
    good, bad = result.partition()
    assert not good and len(bad) == 3
    assert sum(d.code == "TRANSACTION_COUNT_MISMATCH" for d in result.diagnostics) == 2


def test_header_control_sum_mismatch_quarantines_whole_batch():
    result = parse_pain001(PAIN.replace(b"<CtrlSum>170.00</CtrlSum>",
                                          b"<CtrlSum>170.01</CtrlSum>", 1))
    assert len(result.partition()[1]) == 3
    assert "CONTROL_SUM_MISMATCH" in {x.code for x in result.diagnostics}


def test_bad_creditor_iban_quarantines_only_one_record():
    xml = PAIN.replace(b"NL91ABNA0417164300", b"NL91ABNA0417164301", 1)
    good, bad = parse_pain001(xml).partition()
    assert len(good) == 2 and len(bad) == 1
    assert "INVALID_CREDITOR_IBAN" in {x.code for x in bad[0].issues}


def test_sepa_operational_currency_and_amount_rules():
    xml = PAIN.replace(b'Ccy="EUR">100.00', b'Ccy="USD">100.001')
    parsed = parse_pain001(xml)
    assert {x.code for x in parsed.payments[0].issues} >= {
        "SEPA_NON_EUR", "SEPA_AMOUNT_FRACTION"}
    assert parsed.partition()[1]


def test_nonsepa_base_profile_does_not_claim_eur_only():
    xml = PAIN.replace(b'Ccy="EUR">100.00', b'Ccy="USD">100.00')
    good, bad = parse_pain001(xml, profile="base").partition()
    assert len(good) == 3 and len(bad) == 0


def test_reconciliation_does_not_mask_discrepancies():
    file = parse_pain001(PAIN)
    statement = parse_camt053(CAMT)
    found = reconcile(file.payments, statement.entries)
    assert [x.status for x in found] == ["MATCHED", "AMOUNT_MISMATCH", "NO_BOOKING_FOUND"]
    assert found[0].entry.amount == Decimal("-100")


def test_reconciliation_rejects_ambiguous_refs():
    file = parse_pain001(PAIN)
    statement = parse_camt053(CAMT)
    duplicates = (statement.entries[0], replace(statement.entries[0], entry_reference="REPEAT"))
    assert reconcile(file.payments[:1], duplicates)[0].status == "AMBIGUOUS_MATCH"
    duplicate_payments = (file.payments[0], file.payments[0])
    assert all(r.status == "AMBIGUOUS_MATCH" for r in reconcile(duplicate_payments, duplicates[:1]))


def test_missing_end_to_end_does_not_match_other_missing_reference():
    file = parse_pain001(PAIN)
    statement = parse_camt053(CAMT)
    p = replace(file.payments[0], end_to_end_id="NOTPROVIDED")
    e = replace(statement.entries[0], end_to_end_id="NOTPROVIDED")
    assert reconcile([p], [e])[0].status == "UNMATCHABLE_REFERENCE"


def test_camt_aggregated_entry_not_fanned_out_or_matched():
    xml = CAMT.replace(b"</NtryDtls>",
        b"<TxDtls><Refs><EndToEndId>DEMO-E2E-003</EndToEndId></Refs></TxDtls></NtryDtls>", 1)
    parsed = parse_camt053(xml)
    assert parsed.entries[0].end_to_end_id == ""
    assert "AGGREGATED_ENTRY_NOT_MATCHABLE" in {x.code for x in parsed.entries[0].issues}
    assert reconcile(parse_pain001(PAIN).payments[:1], parsed.entries)[0].status == "NO_BOOKING_FOUND"


def test_wrong_namespace_fails_closed():
    with pytest.raises(UnsupportedMessage):
        parse_pain001(PAIN.replace(b"pain.001.001.09", b"pain.001.001.03"))
    with pytest.raises(UnsupportedMessage):
        parse_camt053(CAMT.replace(b"camt.053.001.08", b"camt.053.001.02"))


def test_xml_bomb_and_bounded_file_rejected(tmp_path):
    bomb = b'<!DOCTYPE doc [<!ENTITY x "EXPANDED">]><doc>&x;</doc>'
    with pytest.raises(EntitiesForbidden):
        parse_pain001(bomb)
    big = tmp_path / "big.xml"
    big.write_bytes(b"x" * 25)
    with pytest.raises(ValueError):
        read_xml_file(big, max_bytes=10)


def test_partial_date_and_amount_malformation_are_recorded():
    xml = (PAIN.replace(b"2026-10-28", b"2026-27-28")
           .replace(b'>100.00</InstdAmt>', b'>nan</InstdAmt>'))
    parsed = parse_pain001(xml)
    assert {"INVALID_AMOUNT", "INVALID_EXECUTION_DATE"} <= {
        x.code for x in parsed.payments[0].issues}


def test_malformed_xml_and_xml_limit_fail():
    with pytest.raises(ParseError):
        parse_pain001(b"<notxml>")
    with pytest.raises(ValueError):
        parse_pain001(b" " * (16 * 1024 * 1024 + 1))


def test_readiness_aggregate_redacts_transaction_data():
    from dataclasses import asdict
    from iso20022_quality import assess_readiness
    p = parse_pain001(PAIN)
    s = parse_camt053(CAMT)
    report = assess_readiness([p], [s])
    assert report.files == 1 and report.payments == 3 and report.accepted == 3
    assert report.matched_pct_of_accepted == 33.33
    assert report.reference_coverage_pct == 100.0
    assert report.reconciliation_counts == {
        "AMOUNT_MISMATCH": 1, "MATCHED": 1, "NO_BOOKING_FOUND": 1}
    assert "BE68539007547034" not in str(asdict(report))
    assert "DEMO-E2E-001" not in str(asdict(report))


def test_invalid_payment_is_not_marked_migration_ready():
    from iso20022_quality import assess_readiness
    xml = PAIN.replace(b"NL91ABNA0417164300", b"NL91ABNA0417164301", 1)
    report = assess_readiness([parse_pain001(xml)])
    assert report.accepted == 2 and report.quarantined == 1
    assert report.quality_error_counts.get("INVALID_CREDITOR_IBAN") == 1


def test_missing_mandatory_header_count_is_a_batch_failure():
    xml = PAIN.replace(b"<NbOfTxs>3</NbOfTxs>", b"", 1)
    parsed = parse_pain001(xml)
    assert "MISSING_TRANSACTION_COUNT" in {x.code for x in parsed.diagnostics}
    assert len(parsed.partition()[1]) == 3


def test_reconciliation_requires_same_account_and_debit_direction():
    payments = parse_pain001(PAIN).payments
    entry = parse_camt053(CAMT).entries[0]
    other_account = replace(entry, account_iban="NL91ABNA0417164300")
    assert reconcile(payments[:1], [other_account])[0].status == "NO_BOOKING_FOUND"
    credit = replace(entry, amount=Decimal("100.00"))
    assert reconcile(payments[:1], [credit])[0].status == "DIRECTION_MISMATCH"
    pending = replace(entry, status="PDNG")
    assert reconcile(payments[:1], [pending])[0].status == "NOT_BOOKED"


def test_reconciliation_currency_mismatch_cannot_be_recorded_as_matched():
    payment = parse_pain001(PAIN).payments[0]
    entry = replace(parse_camt053(CAMT).entries[0], currency="USD")
    assert reconcile([payment], [entry])[0].status == "CURRENCY_MISMATCH"


def test_decimal_exact_sum_not_float_approximation():
    xml = PAIN.replace(b"<CtrlSum>170.00</CtrlSum>", b"<CtrlSum>170.0000000001</CtrlSum>", 1)
    assert "CONTROL_SUM_MISMATCH" in {d.code for d in parse_pain001(xml).diagnostics}


def test_xml_entity_is_rejected_even_when_root_matches_supported_version():
    from defusedxml.common import EntitiesForbidden
    malicious = (b'<!DOCTYPE Document [<!ENTITY x "not-a-real-payment">]>'
                 b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">'
                 b'<CstmrCdtTrfInitn><GrpHdr><MsgId>&x;</MsgId></GrpHdr>'
                 b'</CstmrCdtTrfInitn></Document>')
    with pytest.raises(EntitiesForbidden):
        parse_pain001(malicious)


def test_notprovided_reference_warning_not_failure_and_no_false_zero_percent():
    from iso20022_quality import assess_readiness
    xml = PAIN.replace(b"DEMO-E2E-001", b"NOTPROVIDED")
    parsed = parse_pain001(xml)
    assert len(parsed.partition()[0]) == 3
    assert "UNMATCHABLE_REFERENCE" in {i.code for i in parsed.payments[0].issues}
    report = assess_readiness([parsed])
    assert report.reference_coverage_pct == 66.67
    assert report.matched_pct_of_accepted is None
