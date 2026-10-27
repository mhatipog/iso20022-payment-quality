"""Synthetic migration acceptance exercise with known independent reference totals.

Run from the project root:
    python examples/migration_acceptance.py
No real customer, bank or source-system data are used.
"""
from dataclasses import asdict, replace
from decimal import Decimal
import json
from pathlib import Path

from iso20022_quality import (
    MigrationControls,
    assess_migration_gate,
    parse_camt053,
    parse_pain001,
    read_xml_file,
)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    file = parse_pain001(read_xml_file(root / "tests/fixtures/pain09.xml"))
    statement = parse_camt053(read_xml_file(root / "tests/fixtures/camt08.xml"))

    # Synthetic controls are intentionally independent, hardcoded fixture facts:
    # three instructions totaling EUR 170 and three expected booked debits.
    # In a real migration the controls MUST come from a source system inventory,
    # NOT from parsing the files being checked.
    controls = MigrationControls(
        reference="SYNTHETIC-EXTERNAL-INVENTORY",
        payment_count=3,
        payment_total=Decimal("170.00"),
        statement_entry_count=3,
        statement_debit_total=Decimal("170.00"),
    )
    before = assess_migration_gate([file], [statement], controls)

    # Create a separate, explicitly synthetic "remediated" bank fixture.
    # Never alter financial evidence this way in production.
    correct_second = replace(statement.entries[1], amount=Decimal("-50.00"))
    additional = replace(
        statement.entries[0],
        entry_reference="ENTRY-003",
        end_to_end_id="DEMO-E2E-003",
        amount=Decimal("-20.00"),
    )
    remediated = replace(
        statement, entries=(statement.entries[0], correct_second, additional)
    )
    after = assess_migration_gate([file], [remediated], controls)
    assert before.decision == "BLOCKED"
    assert after.decision == "PASS_TECHNICAL_CHECKS"

    print(json.dumps(
        {"original_statement": asdict(before), "synthetic_corrected_statement": asdict(after)},
        default=str, sort_keys=True, indent=2,
    ))


if __name__ == "__main__":
    main()
