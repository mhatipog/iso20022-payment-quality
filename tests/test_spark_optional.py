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
