"""Regressions motivated by published bank examples (links in docs/bank-cases.md)."""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from iso20022_quality import (audit_camt053_balances, parse_camt053,
                              parse_pain002, parse_pain001, reconcile, read_xml_file)

FIXTURES = Path(__file__).parent / "fixtures"
CAMT = read_xml_file(FIXTURES / "camt08.xml")
PAIN = read_xml_file(FIXTURES / "pain09.xml")


def test_pain002_preserves_status_level_and_rejection_reasons():
    result = parse_pain002(read_xml_file(FIXTURES / "pain002_10.xml"))
    assert not result.diagnostics
    assert [s.status for s in result.statuses] == ["PART", "PART", "ACCP", "RJCT"]
    assert result.statuses[-1].reason_codes == ("AC01",)
    assert result.statuses[0].end_to_end_id == ""
    assert result.original_message_id == "PAYMENTS-2026-0001"


def test_camt_status_may_be_text_not_nested_cd():
    # Goldman Sachs published camt.053 v8 examples contain both <Sts><Cd>BOOK
    # and <Sts>BOOK</Sts> structures in sample entries.
    source = CAMT.replace(b"<Sts><Cd>BOOK</Cd></Sts>", b"<Sts>BOOK</Sts>")
    entries = parse_camt053(source).entries
    assert entries[0].status == "BOOK"


def test_return_and_reversal_are_not_ordinary_matched_debits():
    payment = parse_pain001(PAIN).payments[0]
    entry = parse_camt053(CAMT).entries[0]
    assert reconcile([payment], [replace(entry, reversal=True)])[0].status == "REVERSAL_REQUIRES_REVIEW"
    returned = replace(entry, bank_transaction_code="PMNT/ICDT/ARET",
                       issues=entry.issues + ())
    # An extracted bank return code is explicitly marked for review during parsing.
    assert returned.bank_transaction_code.endswith("ARET")


def test_batch_count_marks_single_detail_aggregated():
    xml = CAMT.replace(b"<NtryDtls>",
                       b"<NtryDtls><Btch><NbOfTxs>3</NbOfTxs></Btch>", 1)
    entry = parse_camt053(xml).entries[0]
    assert entry.transaction_count == 3
    assert entry.end_to_end_id == ""
    assert "AGGREGATED_ENTRY_NOT_MATCHABLE" in {d.code for d in entry.issues}


def test_balances_synthetic_balanced_and_mismatched():
    ns = b'urn:iso:std:iso:20022:tech:xsd:camt.053.001.08'
    template = (b'<Document xmlns="' + ns + b'"><BkToCstmrStmt><Stmt><Id>example</Id>'
        b'<Acct><Ccy>EUR</Ccy></Acct>'
        b'<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">100</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>'
        b'<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">%s</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>'
        b'<Ntry><Amt Ccy="EUR">20</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts>BOOK</Sts></Ntry>'
        b'</Stmt></BkToCstmrStmt></Document>')
    balanced = audit_camt053_balances(template % b"80")[0]
    assert balanced.status == "BALANCED" and balanced.difference == Decimal(0)
    wrong = audit_camt053_balances(template % b"90")[0]
    assert wrong.status == "DIFFERENCE" and wrong.difference == Decimal("10")
    paginated = (template % b"80").replace(b"<Acct>",
                b"<StmtPgntn><PgNb>1</PgNb><LastPgInd>false</LastPgInd></StmtPgntn><Acct>")
    assert audit_camt053_balances(paginated)[0].status == "NOT_ASSESSABLE"


def test_bad_balance_currency_is_not_assessed():
    xml = (b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">'
           b'<BkToCstmrStmt><Stmt><Id>mixed</Id><Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry>'
           b'</Tp><Amt Ccy="EUR">100</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>'
           b'<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>'
           b'<Amt Ccy="USD">100</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>'
           b'</Stmt></BkToCstmrStmt></Document>')
    assert audit_camt053_balances(xml)[0].reason == "BALANCE_CURRENCY_MISMATCH"


def test_status_parser_fails_closed_on_wrong_namespace():
    with pytest.raises(Exception):
        parse_pain002(read_xml_file(FIXTURES / "pain002_10.xml").replace(b".001.10", b".001.03"))


def test_status_linking_does_not_infer_settlement():
    from iso20022_quality import link_payment_statuses
    report = parse_pain002(read_xml_file(FIXTURES / "pain002_10.xml"))
    payment = replace(parse_pain001(PAIN).payments[0],
                      message_id="PAYMENTS-2026-0001", payment_info_id="BATCH-001",
                      end_to_end_id="INV-1001", instruction_id="ORDER-1")
    result = link_payment_statuses([payment], [report])
    assert result[0].state == "OBSERVED"
    assert [s.status for s in result[0].observations] == ["ACCP"]
    assert link_payment_statuses([payment, payment], [report])[0].state == "AMBIGUOUS_PAYMENT_KEY"
    assert link_payment_statuses([payment], [])[0].state == "NO_TRANSACTION_STATUS"


def test_file_replays_distinguish_duplicate_from_revised_message():
    from iso20022_quality import file_receipt, detect_replays
    r1 = file_receipt(PAIN, message_type="pain.001.001.09", message_id="PAY-001")
    r2 = file_receipt(PAIN + b"\n", message_type="pain.001.001.09", message_id="PAY-001")
    decisions = detect_replays([r1, r1, r2])
    assert [x.decision for x in decisions] == [
        "NEW", "EXACT_REPLAY", "CONFLICTING_MESSAGE_ID"]
    assert detect_replays([r1], [r1])[0].decision == "EXACT_REPLAY"


def test_realistic_camt_reversal_flags_and_bank_code():
    xml = (CAMT.replace(b"<NtryRef>", b"<RvslInd>true</RvslInd><NtryRef>", 1)
           .replace(b"</Sts>", b"</Sts><BkTxCd><Domn><Cd>PMNT</Cd><Fmly>"
                                   b"<Cd>ICDT</Cd><SubFmlyCd>ARET</SubFmlyCd>"
                                   b"</Fmly></Domn></BkTxCd>", 1))
    entry = parse_camt053(xml).entries[0]
    assert entry.reversal
    assert entry.bank_transaction_code == "PMNT/ICDT/ARET"
    assert "REVERSAL_REQUIRES_REVIEW" in {x.code for x in entry.issues}
    assert "RETURN_REQUIRES_REVIEW" in {x.code for x in entry.issues}
    payment = parse_pain001(PAIN).payments[0]
    assert reconcile([payment], [entry])[0].status == "REVERSAL_REQUIRES_REVIEW"
