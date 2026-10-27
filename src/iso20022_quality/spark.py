"""Spark SQL-native quality and reconciliation; no Python UDFs or driver collects.

This is the data-lake (canonical records) layer, not an XML XSD engine. Spark 3.4+.
"""

from .iban import IBAN_LENGTHS


def _iban_sql(name: str) -> str:
    """Generate safe SQL using static input names and a hard-coded length registry."""
    assert name in ("debtor_iban", "creditor_iban")
    iban = f"upper(replace(coalesce(cast(`{name}` as string), ''), ' ', ''))"
    rotated = f"concat(substring({iban}, 5), substring({iban}, 1, 4))"
    ch = f"ascii(substring({rotated}, i, 1))"
    # Single modulo operation per original character; letters represent two decimal digits.
    remainder = (
        f"aggregate(sequence(1, length({iban})), cast(0 as bigint), "
        f"(r, i) -> pmod(r * IF({ch} between 65 and 90, 100, 10) + "
        f"IF({ch} between 65 and 90, {ch} - 55, {ch} - 48), 97))"
    )
    cases = " ".join(f"WHEN '{country}' THEN {length}" for country, length in IBAN_LENGTHS.items())
    expected = f"(case substring({iban}, 1, 2) {cases} else length({iban}) end)"
    return (
        f"({iban} rlike '^[A-Z]{{2}}[0-9]{{2}}[A-Z0-9]{{11,30}}$' "
        f"and length({iban}) = {expected} and {remainder} = 1)"
    )


def validate_payments(df, *, profile: str = "sepa_sct"):
    """Attach dq_errors, dq_warnings and dq_valid to a canonical payment DataFrame.

    Required: debtor_iban, creditor_iban, amount, currency, end_to_end_id.
    Numeric input: at most 16 digits before and 8 after decimal; no silent rounding.
    The 'base' profile does not mandate debtor/creditor IBANs (accounts can be non-IBAN).
    """
    if profile not in ("sepa_sct", "base"):
        raise ValueError("profile must be 'sepa_sct' or 'base'")
    required = {"debtor_iban", "creditor_iban", "amount", "currency", "end_to_end_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing canonical columns: {', '.join(sorted(missing))}")
    collisions = {"dq_errors", "dq_warnings", "dq_valid"} & set(df.columns)
    if collisions:
        raise ValueError(f"Output columns already exist: {', '.join(sorted(collisions))}")
    from pyspark.sql import functions as F

    amount = F.trim(F.col("amount").cast("string"))
    currency = F.upper(F.trim(F.coalesce(F.col("currency").cast("string"), F.lit(""))))
    reference = F.trim(F.coalesce(F.col("end_to_end_id").cast("string"), F.lit("")))
    # String validation before casting prevents silent numeric rounding to scale=8.
    amount_format_ok = amount.rlike(r"^[0-9]{1,16}(\.[0-9]{1,8})?$")
    amount_decimal = F.when(amount_format_ok, amount.cast("decimal(24,8)"))
    invalid_amount = (~amount_format_ok) | amount_decimal.isNull() | (amount_decimal <= 0)
    rules = [
        (reference == "", "MISSING_END_TO_END_ID"),
        (invalid_amount, "INVALID_AMOUNT"),
        (~currency.rlike(r"^[A-Z]{3}$"), "INVALID_CURRENCY"),
    ]
    if profile == "sepa_sct":
        rules += [
            (currency != "EUR", "SEPA_NON_EUR"),
            (~F.expr(_iban_sql("debtor_iban")), "INVALID_DEBTOR_IBAN"),
            (~F.expr(_iban_sql("creditor_iban")), "INVALID_CREDITOR_IBAN"),
            (amount.rlike(r"\.[0-9]{3,}$"), "SEPA_AMOUNT_FRACTION"),
        ]
    else:
        for col, code in [
            ("debtor_iban", "INVALID_DEBTOR_IBAN"),
            ("creditor_iban", "INVALID_CREDITOR_IBAN"),
        ]:
            has_iban = F.trim(F.coalesce(F.col(col).cast("string"), F.lit(""))) != ""
            rules.append((has_iban & ~F.expr(_iban_sql(col)), code))
    errors = F.filter(
        F.array(*[F.when(test, F.lit(code)) for test, code in rules]), lambda s: s.isNotNull()
    )
    warnings = F.filter(
        F.array(F.when(reference == "NOTPROVIDED", F.lit("UNMATCHABLE_REFERENCE"))),
        lambda s: s.isNotNull(),
    )
    return (
        df.withColumn("dq_errors", errors)
        .withColumn("dq_warnings", warnings)
        .withColumn("dq_valid", F.size(F.col("dq_errors")) == 0)
    )


def partition_quality(df):
    """Return (valid, quarantined) without collecting records on the Spark driver."""
    from pyspark.sql import functions as F

    if "dq_valid" not in df.columns:
        raise ValueError("Pass the DataFrame through validate_payments first")
    return df.filter(F.col("dq_valid")), df.filter(~F.col("dq_valid"))


def reconcile_spark(payments_df, entries_df):
    """Conservatively match canonical payments to bank statement entries in Spark.

    payments require: payment_id (unique), end_to_end_id, debtor_iban, amount, currency.
    entries require: entry_id (unique), end_to_end_id, account_iban, amount (signed),
    currency, status. Optional entry fields: reversal (boolean),
    bank_transaction_code (e.g. PMNT/ICDT/ARET), transaction_count (int),
    dq_valid (boolean). Optional payment field: dq_valid (boolean).
    Unique IDs are a caller invariant; references need not be unique.
    Aggregating entries BEFORE joining preserves one output row per payment.
    """
    from pyspark.sql import functions as F

    pcols = {"payment_id", "end_to_end_id", "debtor_iban", "amount", "currency"}
    ecols = {"entry_id", "end_to_end_id", "account_iban", "amount", "currency", "status"}
    if pcols - set(payments_df.columns) or ecols - set(entries_df.columns):
        raise ValueError("Missing payment or statement canonical columns")
    p = payments_df.select(
        F.col("payment_id"),
        F.col("end_to_end_id").alias("ref"),
        F.upper(F.regexp_replace(F.col("debtor_iban"), " ", "")).alias("account"),
        F.col("amount").cast("decimal(24,8)").alias("payment_amount"),
        F.col("currency").alias("payment_currency"),
        (F.col("dq_valid") if "dq_valid" in payments_df.columns else F.lit(True)).alias(
            "payment_valid"
        ),
    )
    e = entries_df.select(
        F.col("entry_id"),
        F.col("end_to_end_id").alias("ref"),
        F.upper(F.regexp_replace(F.col("account_iban"), " ", "")).alias("account"),
        F.col("amount").cast("decimal(24,8)").alias("entry_amount"),
        F.col("currency").alias("entry_currency"),
        F.col("status").alias("entry_status"),
        (F.col("reversal") if "reversal" in entries_df.columns else F.lit(False)).alias(
            "entry_reversal"
        ),
        (
            F.col("transaction_count") if "transaction_count" in entries_df.columns else F.lit(1)
        ).alias("entry_transaction_count"),
        (
            F.col("bank_transaction_code")
            if "bank_transaction_code" in entries_df.columns
            else F.lit("")
        ).alias("entry_bank_code"),
        (F.col("dq_valid") if "dq_valid" in entries_df.columns else F.lit(True)).alias(
            "entry_valid"
        ),
    )
    keys = ["ref", "account"]
    p_counts = p.groupBy(*keys).agg(F.count("*").alias("n_payments"))
    e_counts = e.groupBy(*keys).agg(
        F.count("*").alias("n_entries"),
        F.min("entry_id").alias("candidate_entry_id"),
        F.min("entry_amount").alias("candidate_amount"),
        F.min("entry_currency").alias("candidate_currency"),
        F.min("entry_status").alias("candidate_status"),
        F.min("entry_reversal").alias("candidate_reversal"),
        F.min("entry_transaction_count").alias("candidate_transaction_count"),
        F.min("entry_bank_code").alias("candidate_bank_code"),
        F.min("entry_valid").alias("candidate_valid"),
    )
    joined = p.join(p_counts, keys, "left").join(e_counts, keys, "left")
    matchable = (
        F.col("ref").isNotNull()
        & (F.trim(F.col("ref")) != "")
        & (F.col("ref") != "NOTPROVIDED")
        & F.col("account").isNotNull()
        & (F.col("account") != "")
    )
    status = (
        F.when(~matchable, "UNMATCHABLE_REFERENCE")
        .when(F.col("n_entries").isNull(), "NO_BOOKING_FOUND")
        .when((F.col("n_entries") > 1) | (F.col("n_payments") > 1), "AMBIGUOUS_MATCH")
        .when(
            ~F.coalesce(F.col("payment_valid"), F.lit(False))
            | ~F.coalesce(F.col("candidate_valid"), F.lit(False)),
            "INVALID_SOURCE_RECORD",
        )
        .when(
            F.coalesce(F.col("candidate_transaction_count"), F.lit(1)) > 1,
            "AGGREGATED_ENTRY_NOT_MATCHABLE",
        )
        .when(
            F.col("payment_amount").isNull() | F.col("candidate_amount").isNull(), "INVALID_AMOUNT"
        )
        .when(
            ~F.col("payment_currency").eqNullSafe(F.col("candidate_currency")), "CURRENCY_MISMATCH"
        )
        .when(F.col("candidate_amount") >= 0, "DIRECTION_MISMATCH")
        .when(F.col("candidate_amount") != -F.col("payment_amount"), "AMOUNT_MISMATCH")
        .when(F.coalesce(F.col("candidate_reversal"), F.lit(False)), "REVERSAL_REQUIRES_REVIEW")
        .when(F.col("candidate_bank_code").rlike("/(ARET|RRTN)$"), "RETURN_REQUIRES_REVIEW")
        .when(~F.col("candidate_status").eqNullSafe(F.lit("BOOK")), "NOT_BOOKED")
        .otherwise("MATCHED")
    )
    return joined.select(
        "payment_id",
        status.alias("reconciliation_status"),
        F.when(status != "AMBIGUOUS_MATCH", F.col("candidate_entry_id")).alias(
            "candidate_entry_id"
        ),
    )
