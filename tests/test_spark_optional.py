import pytest

pyspark = pytest.importorskip("pyspark")
from iso20022_quality.spark import partition_quality, reconcile_spark, validate_payments


@pytest.fixture(scope="module")
def spark():
    from pyspark.sql import SparkSession

    session = (
        SparkSession.builder.master("local[1]")
        .appName("iso20022-quality-tests")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


def test_native_payment_quality(spark):
    df = spark.createDataFrame(
        [
            ("P1", "BE68539007547034", "NL91ABNA0417164300", "12.50", "EUR", "REF1"),
            ("P2", "BE68539007547035", "NL91ABNA0417164300", "1.00", "EUR", "REF2"),
            ("P3", "BE68539007547034", "NL91ABNA0417164300", "1.001", "EUR", "REF3"),
            ("P4", "BE68539007547034", "NL91ABNA0417164300", "1.00", "USD", "REF4"),
        ],
        ["payment_id", "debtor_iban", "creditor_iban", "amount", "currency", "end_to_end_id"],
    )
    quality = validate_payments(df)
    valid, quarantine = partition_quality(quality)
    assert valid.count() == 1
    assert quarantine.count() == 3
    statuses = {x.payment_id: x.dq_errors for x in quality.collect()}
    assert "INVALID_DEBTOR_IBAN" in statuses["P2"]
    assert "SEPA_AMOUNT_FRACTION" in statuses["P3"]
    assert "SEPA_NON_EUR" in statuses["P4"]


def test_reconcile_in_spark_never_fans_out(spark):
    p = spark.createDataFrame(
        [
            ("P1", "R1", "BE68539007547034", "100.00", "EUR"),
            ("P2", "R2", "BE68539007547034", "50.00", "EUR"),
            ("P3", "R3", "BE68539007547034", "10.00", "EUR"),
        ],
        ["payment_id", "end_to_end_id", "debtor_iban", "amount", "currency"],
    )
    e = spark.createDataFrame(
        [
            ("E1", "R1", "BE68539007547034", "-100.00", "EUR", "BOOK"),
            ("E2", "R2", "BE68539007547034", "-49.99", "EUR", "BOOK"),
            ("E3", "R3", "BE68539007547034", "-10.00", "EUR", "BOOK"),
            ("E4", "R3", "BE68539007547034", "-10.00", "EUR", "BOOK"),
        ],
        ["entry_id", "end_to_end_id", "account_iban", "amount", "currency", "status"],
    )
    rows = reconcile_spark(p, e).collect()
    assert len(rows) == 3
    assert {r.payment_id: r.reconciliation_status for r in rows} == {
        "P1": "MATCHED",
        "P2": "AMOUNT_MISMATCH",
        "P3": "AMBIGUOUS_MATCH",
    }


def test_spark_refuses_reversals_returns_and_bad_input(spark):
    p = spark.createDataFrame(
        [
            ("P1", "R1", "BE68539007547034", "100.00", "EUR", True),
            ("P2", "R2", "BE68539007547034", "100.00", "EUR", True),
            ("P3", "R3", "BE68539007547034", "100.00", "EUR", False),
            ("P4", "R4", "BE68539007547034", "100.00", "EUR", True),
        ],
        ["payment_id", "end_to_end_id", "debtor_iban", "amount", "currency", "dq_valid"],
    )
    e = spark.createDataFrame(
        [
            ("E1", "R1", "BE68539007547034", "-100.00", "EUR", "BOOK", True, "", 1, True),
            (
                "E2",
                "R2",
                "BE68539007547034",
                "-100.00",
                "EUR",
                "BOOK",
                False,
                "PMNT/ICDT/ARET",
                1,
                True,
            ),
            ("E3", "R3", "BE68539007547034", "-100.00", "EUR", "BOOK", False, "", 1, True),
            ("E4", "R4", "BE68539007547034", "-100.00", "EUR", "BOOK", False, "", 3, True),
        ],
        [
            "entry_id",
            "end_to_end_id",
            "account_iban",
            "amount",
            "currency",
            "status",
            "reversal",
            "bank_transaction_code",
            "transaction_count",
            "dq_valid",
        ],
    )
    assert {x.payment_id: x.reconciliation_status for x in reconcile_spark(p, e).collect()} == {
        "P1": "REVERSAL_REQUIRES_REVIEW",
        "P2": "RETURN_REQUIRES_REVIEW",
        "P3": "INVALID_SOURCE_RECORD",
        "P4": "AGGREGATED_ENTRY_NOT_MATCHABLE",
    }


def test_ansi_mode_invalid_amounts_quarantine_not_crash(spark):
    from pyspark.sql import functions as F

    previous = spark.conf.get("spark.sql.ansi.enabled", "false")
    spark.conf.set("spark.sql.ansi.enabled", "true")
    try:
        p = spark.createDataFrame(
            [
                ("P1", "BAD", "BE68539007547034", "not-a-decimal", "EUR"),
                ("P2", "OVERFLOW", "BE68539007547034", "999999999999999999999", "EUR"),
                ("P3", "GOOD", "BE68539007547034", "12.50", "EUR"),
            ],
            ["payment_id", "end_to_end_id", "debtor_iban", "amount", "currency"],
        )
        e = spark.createDataFrame(
            [
                ("E1", "BAD", "BE68539007547034", "-12.50", "EUR", "BOOK"),
                ("E2", "OVERFLOW", "BE68539007547034", "-12.50", "EUR", "BOOK"),
                ("E3", "GOOD", "BE68539007547034", "-12.50", "EUR", "BOOK"),
            ],
            ["entry_id", "end_to_end_id", "account_iban", "amount", "currency", "status"],
        )
        results = {r.payment_id: r.reconciliation_status for r in reconcile_spark(p, e).collect()}
        assert results == {"P1": "INVALID_AMOUNT", "P2": "INVALID_AMOUNT", "P3": "MATCHED"}

        v = p.withColumn("creditor_iban", F.lit("NL91ABNA0417164300"))
        quality = {r.payment_id: r.dq_valid for r in validate_payments(v).collect()}
        assert quality == {"P1": False, "P2": False, "P3": True}
    finally:
        spark.conf.set("spark.sql.ansi.enabled", previous)


def test_duplicate_physical_identifiers_never_silently_match(spark):
    p = spark.createDataFrame(
        [
            ("P1", "REF1", "BE68539007547034", "10.00", "EUR"),
            ("P1", "REF2", "BE68539007547034", "11.00", "EUR"),
            ("P3", "REF3", "BE68539007547034", "12.00", "EUR"),
            ("P4", "REF4", "BE68539007547034", "13.00", "EUR"),
        ],
        ["payment_id", "end_to_end_id", "debtor_iban", "amount", "currency"],
    )
    e = spark.createDataFrame(
        [
            ("E1", "REF1", "BE68539007547034", "-10.00", "EUR", "BOOK"),
            ("E2", "REF2", "BE68539007547034", "-11.00", "EUR", "BOOK"),
            ("E3", "REF3", "BE68539007547034", "-12.00", "EUR", "BOOK"),
            ("E3", "REF4", "BE68539007547034", "-13.00", "EUR", "BOOK"),
        ],
        ["entry_id", "end_to_end_id", "account_iban", "amount", "currency", "status"],
    )
    rows = reconcile_spark(p, e).collect()
    assert len(rows) == 4
    assert sum(r.reconciliation_status == "DUPLICATE_PAYMENT_ID" for r in rows) == 2
    assert sum(r.reconciliation_status == "DUPLICATE_ENTRY_ID" for r in rows) == 2


def test_reject_floating_point_financial_columns(spark):
    df = spark.createDataFrame(
        [("BE68539007547034", "NL91ABNA0417164300", 12.5, "EUR", "REF1")],
        ["debtor_iban", "creditor_iban", "amount", "currency", "end_to_end_id"],
    )
    with pytest.raises(TypeError, match="floating point"):
        validate_payments(df)


def test_exact_spark_decimal_padding_and_excess_precision(spark):
    from decimal import Decimal

    values = spark.createDataFrame(
        [
            ("P1", "R1", "BE68539007547034", "NL91ABNA0417164300",
             Decimal("12.500000000000000000"), "EUR"),
            ("P2", "R2", "BE68539007547034", "NL91ABNA0417164300",
             Decimal("12.500000001000000000"), "EUR"),
        ],
        ["payment_id", "end_to_end_id", "debtor_iban", "creditor_iban", "amount", "currency"],
    )
    quality = {r.payment_id: r.dq_valid for r in validate_payments(values).collect()}
    assert quality == {"P1": True, "P2": False}

    entries = spark.createDataFrame(
        [("E1", "R1", "BE68539007547034", "-12.50", "EUR", "BOOK")],
        ["entry_id", "end_to_end_id", "account_iban", "amount", "currency", "status"],
    )
    results = {r.payment_id: r.reconciliation_status
               for r in reconcile_spark(values, entries).collect()}
    assert results == {"P1": "MATCHED", "P2": "INVALID_AMOUNT"}


def test_missing_statement_entry_identifier_cannot_be_matched(spark):
    payments = spark.createDataFrame(
        [("P1", "R1", "BE68539007547034", "12.50", "EUR"),
         ("P2", "R2", "BE68539007547034", "12.50", "EUR")],
        ["payment_id", "end_to_end_id", "debtor_iban", "amount", "currency"],
    )
    entries = spark.createDataFrame(
        [(None, "R1", "BE68539007547034", "-12.50", "EUR", "BOOK"),
         ("   ", "R2", "BE68539007547034", "-12.50", "EUR", "BOOK")],
        ["entry_id", "end_to_end_id", "account_iban", "amount", "currency", "status"],
    )
    outcomes = {r.payment_id: (r.reconciliation_status, r.candidate_entry_id)
                for r in reconcile_spark(payments, entries).collect()}
    assert outcomes == {
        "P1": ("INVALID_ENTRY_ID", None),
        "P2": ("INVALID_ENTRY_ID", None),
    }


def test_explicit_matching_scope_handles_reused_references(spark):
    payments = spark.createDataFrame(
        [("P1", "SHARED", "BE68539007547034", "12.50", "EUR", "BANK-A"),
         ("P2", "SHARED", "BE68539007547034", "13.50", "EUR", "BANK-B")],
        ["payment_id", "end_to_end_id", "debtor_iban", "amount", "currency", "cohort"],
    )
    entries = spark.createDataFrame(
        [("E1", "SHARED", "BE68539007547034", "-12.50", "EUR", "BOOK", "BANK-A"),
         ("E2", "SHARED", "BE68539007547034", "-13.50", "EUR", "BOOK", "BANK-B")],
        ["entry_id", "end_to_end_id", "account_iban", "amount", "currency", "status", "cohort"],
    )
    unscoped = {r.payment_id: r.reconciliation_status
                for r in reconcile_spark(payments, entries).collect()}
    assert unscoped == {"P1": "AMBIGUOUS_MATCH", "P2": "AMBIGUOUS_MATCH"}
    scoped = {r.payment_id: (r.reconciliation_status, r.candidate_entry_id)
              for r in reconcile_spark(
                  payments, entries, scope_columns=("cohort",)
              ).collect()}
    assert scoped == {"P1": ("MATCHED", "E1"), "P2": ("MATCHED", "E2")}


def test_missing_scope_cannot_match_and_contract_is_checked(spark):
    payments = spark.createDataFrame(
        [("P1", "R1", "BE68539007547034", "12.50", "EUR", None),
         ("P2", "R2", "BE68539007547034", "12.50", "EUR", " ")],
        ["payment_id", "end_to_end_id", "debtor_iban", "amount", "currency", "cohort"],
    )
    entries = spark.createDataFrame(
        [("E1", "R1", "BE68539007547034", "-12.50", "EUR", "BOOK", "BANK-A"),
         ("E2", "R2", "BE68539007547034", "-12.50", "EUR", "BOOK", "BANK-B")],
        ["entry_id", "end_to_end_id", "account_iban", "amount", "currency", "status", "cohort"],
    )
    outcomes = {r.payment_id: r.reconciliation_status
                for r in reconcile_spark(
                    payments, entries, scope_columns=("cohort",)
                ).collect()}
    assert outcomes == {"P1": "UNMATCHABLE_SCOPE", "P2": "UNMATCHABLE_SCOPE"}
    with pytest.raises(ValueError, match="both"):
        reconcile_spark(payments, entries, scope_columns=("unknown_cohort",))
    with pytest.raises(ValueError, match="reserved"):
        reconcile_spark(payments, entries, scope_columns=("amount",))
    with pytest.raises(TypeError, match="tuple"):
        reconcile_spark(payments, entries, scope_columns="cohort")
