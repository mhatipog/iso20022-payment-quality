"""Deterministic, synthetic reconciliation benchmark. No live financial data.

Run: python benchmarks/reconciliation.py --records 100000
Only measures matching in Python, not XML ingest, XSD, Spark or Databricks.
"""
import argparse
from collections import Counter
from decimal import Decimal
import json
import platform
from time import perf_counter

from iso20022_quality.models import Payment, StatementEntry
from iso20022_quality.reconcile import reconcile


def run(n: int):
    p, e = [], []
    amount = Decimal("25.50")
    for i in range(n):
        ref = f"SIM-{i:012d}"
        p.append(Payment("TEST", "BATCH", ref, ref, "BE68539007547034",
                         "NL91ABNA0417164300", amount, "EUR", "2026-10-28"))
        if i % 100:
            value = Decimal("-25.49") if i % 50 == 0 else -amount
            e.append(StatementEntry("STMT", "BE68539007547034", ref, ref,
                                    value, "EUR", "BOOK", "2026-10-29"))
    t = perf_counter()
    outcomes = Counter(item.status for item in reconcile(p, e))
    elapsed = perf_counter() - t
    expected = {"NO_BOOKING_FOUND": sum(i % 100 == 0 for i in range(n)),
                "AMOUNT_MISMATCH": sum(i % 50 == 0 and i % 100 != 0 for i in range(n))}
    expected["MATCHED"] = n - sum(expected.values())
    assert dict(outcomes) == expected, (outcomes, expected)
    return {"records": n, "seconds": round(elapsed, 4),
            "records_per_second": round(n / elapsed), "outcomes": dict(outcomes),
            "python": platform.python_version(), "machine": platform.platform(),
            "caveat": "local synthetic Python in-memory matching only"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=100000)
    args = parser.parse_args()
    if not 1 <= args.records <= 1_000_000:
        parser.error("--records must be in [1, 1000000]")
    print(json.dumps(run(args.records), sort_keys=True))
