"""Run `python examples/demo.py` after `pip install -e .` (all data synthetic)."""
from pathlib import Path
from collections import Counter

from iso20022_quality import parse_pain001, parse_camt053, reconcile, read_xml_file

fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
file = parse_pain001(read_xml_file(fixtures / "pain09.xml"))
statement = parse_camt053(read_xml_file(fixtures / "camt08.xml"))
valid, quarantine = file.partition()
print(f"Payment quality: accepted={len(valid)} quarantined={len(quarantine)}")
print("Statement matching:", dict(Counter(r.status for r in reconcile(valid, statement.entries))))
