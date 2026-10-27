"""Safety cases for the independent banking migration acceptance gate."""

from dataclasses import replace
from decimal import Decimal

import pytest

from iso20022_quality.migration_gate import (
    MigrationControls,
    assess_migration_gate,
)
from iso20022_quality.models import (
    Diagnostic,
    Payment,
    PaymentFile,
    Statement,
    StatementEntry,
)


def fixture():
    payments = (
        Payment(
            "SYNTHETIC", "BATCH", "E2E-1", "INSTR-1",
            "BE68539007547034", "NL91ABNA0417164300",
            Decimal("10.00"), "EUR", "2026-10-27",
        ),
        Payment(
            "SYNTHETIC", "BATCH", "E2E-2", "INSTR-2",
            "BE68539007547034", "NL91ABNA0417164300",
            Decimal("20.00"), "EUR", "2026-10-27",
        ),
    )
    entries = (
        StatementEntry(
            "STMT-1", "BE68539007547034", "BANK-1", "E2E-1",
            Decimal("-10.00"), "EUR", "BOOK", "2026-10-28",
        ),
        StatementEntry(
            "STMT-1", "BE68539007547034", "BANK-2", "E2E-2",
            Decimal("-20.00"), "EUR", "BOOK", "2026-10-28",
        ),
    )
    controls = MigrationControls(
        reference="INDEPENDENT-LEGACY-INVENTORY-20261027",
        payment_count=2,
        payment_total=Decimal("30.00"),
        statement_entry_count=2,
        statement_debit_total=Decimal("30.00"),
    )
    return PaymentFile("pain.001.001.09", "SYNTHETIC", payments, ()), Statement(
        "camt.053.001.08", entries, ()
    ), controls


def assess(file, statement, controls):
    return assess_migration_gate([file], [statement], controls)


def test_independent_controls_allow_only_exact_complete_scope():
    file, statement, controls = fixture()
    result = assess(file, statement, controls)
    assert result.decision == "PASS_TECHNICAL_CHECKS"
    assert result.blocking_codes == ()
    assert result.matched_count == 2
    assert result.payment_total == Decimal("30.00")
    assert result.matched_debit_total == Decimal("30.00")
    assert result.reconciliation_counts == {"MATCHED": 2}
    # Reordering is not a financial-data error.
    assert assess(replace(file, payments=file.payments[::-1]),
                  replace(statement, entries=statement.entries[::-1]),
                  controls) == result


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("payment_count", 3, "SOURCE_PAYMENT_COUNT_MISMATCH"),
        ("payment_total", Decimal("30.01"), "SOURCE_PAYMENT_TOTAL_MISMATCH"),
        ("statement_entry_count", 3, "SOURCE_STATEMENT_COUNT_MISMATCH"),
        ("statement_debit_total", Decimal("30.01"), "SOURCE_STATEMENT_TOTAL_MISMATCH"),
    ],
)
def test_independent_source_disagreements_fail_closed(field, value, reason):
    file, statement, controls = fixture()
    result = assess(file, statement, replace(controls, **{field: value}))
    assert result.decision == "BLOCKED"
    assert reason in result.blocking_codes


def test_missing_payment_can_not_pass_even_with_matching_bank_subset():
    file, statement, controls = fixture()
    result = assess(
        replace(file, payments=file.payments[:1]),
        replace(statement, entries=statement.entries[:1]),
        controls,
    )
    assert result.decision == "BLOCKED"
    assert "SOURCE_PAYMENT_COUNT_MISMATCH" in result.blocking_codes
    assert "SOURCE_PAYMENT_TOTAL_MISMATCH" in result.blocking_codes


def test_duplicate_bank_entry_not_treated_as_valid_one_to_one_reconciliation():
    file, statement, controls = fixture()
    extra = replace(statement.entries[0], entry_reference="BANK-1-REPLAY")
    result = assess(file, replace(statement, entries=statement.entries + (extra,)), controls)
    assert result.decision == "BLOCKED"
    assert "RECONCILIATION_EXCEPTIONS" in result.blocking_codes
    assert "UNACCOUNTED_STATEMENT_ENTRIES" in result.blocking_codes


def test_extra_unrelated_bank_entry_blocks_without_raw_identifiers():
    file, statement, controls = fixture()
    extra = replace(statement.entries[0], entry_reference="EXTRA", end_to_end_id="OTHER")
    result = assess(file, replace(statement, entries=statement.entries + (extra,)), controls)
    assert result.decision == "BLOCKED"
    assert "UNACCOUNTED_STATEMENT_ENTRIES" in result.blocking_codes
    assert "SOURCE_STATEMENT_COUNT_MISMATCH" in result.blocking_codes
    assert "EXTRA" not in str(result)
    assert "BE68539007547034" not in str(result)


def test_invalid_payment_and_file_wide_quarantine_block():
    file, statement, controls = fixture()
    bad = replace(
        file.payments[0],
        issues=(Diagnostic("INVALID_IBAN", "error", "transaction"),),
    )
    result = assess(replace(file, payments=(bad, file.payments[1])), statement, controls)
    assert result.decision == "BLOCKED"
    assert result.quarantined_count == 1
    assert "QUARANTINED_PAYMENTS" in result.blocking_codes

    result = assess(
        replace(file, diagnostics=(Diagnostic("CONTROL_SUM_MISMATCH", "error", "message"),)),
        statement, controls,
    )
    assert result.quarantined_count == 2
    assert result.decision == "BLOCKED"
    assert "PAYMENT_FILE_INTEGRITY_ERROR" in result.blocking_codes


def test_pending_returned_and_invalid_statement_entries_never_pass():
    file, statement, controls = fixture()
    for edited in (
        replace(statement.entries[0], status="PDNG"),
        replace(statement.entries[0], reversal=True),
        replace(statement.entries[0], bank_transaction_code="PMNT/ICDT/ARET"),
        replace(
            statement.entries[0],
            issues=(Diagnostic("BAD_BANK_ENTRY", "error", "entry"),),
        ),
    ):
        result = assess(
            file, replace(statement, entries=(edited, statement.entries[1])), controls
        )
        assert result.decision == "BLOCKED"
        assert "RECONCILIATION_EXCEPTIONS" in result.blocking_codes


def test_bank_side_amount_error_and_missing_booking_block():
    file, statement, controls = fixture()
    mismatch = replace(statement.entries[1], amount=Decimal("-19.99"))
    result = assess(
        file, replace(statement, entries=(statement.entries[0], mismatch)), controls
    )
    assert result.decision == "BLOCKED"
    assert "RECONCILIATION_EXCEPTIONS" in result.blocking_codes
    assert "SOURCE_STATEMENT_TOTAL_MISMATCH" in result.blocking_codes

    result = assess(file, replace(statement, entries=statement.entries[:1]), controls)
    assert "RECONCILIATION_EXCEPTIONS" in result.blocking_codes


def test_missing_inputs_never_pass_vacuously():
    file, statement, controls = fixture()
    result = assess_migration_gate([], [], controls)
    assert result.decision == "BLOCKED"
    assert "MISSING_SOURCE_EVIDENCE" in result.blocking_codes
    assert "EMPTY_ACCEPTED_SCOPE" in result.blocking_codes


def test_controls_reject_fake_precision_and_untraceable_evidence():
    _, _, controls = fixture()
    with pytest.raises(ValueError, match="evidence"):
        replace(controls, reference=" ")
    with pytest.raises(ValueError, match="positive integer"):
        replace(controls, payment_count=True)
    with pytest.raises(ValueError, match="finite positive Decimal"):
        replace(controls, statement_debit_total=float("nan"))
    with pytest.raises(TypeError, match="MigrationControls"):
        assess_migration_gate([], [], {"payment_count": 1})
