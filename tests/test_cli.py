import json
import os
import subprocess
import sys
from pathlib import Path


def test_aggregate_cli_has_no_payment_identifiers():
    root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "iso20022_quality.cli", "--payment",
           str(root / "tests/fixtures/pain09.xml"), "--statement",
           str(root / "tests/fixtures/camt08.xml")]
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    out = subprocess.check_output(cmd, env=env, text=True)
    assert json.loads(out)["reconciliation_counts"]["MATCHED"] == 1
    assert "BE68539007547034" not in out
