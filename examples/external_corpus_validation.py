"""Independent, reproducible ISO 20022 compatibility sample checks.

Only downloads public Apache-2.0 licensed synthetic examples from a PINNED
GitHub commit. Never sends local payment data to any external service.
This is NOT a validation against real bank production records or ISO XSD.
"""
from decimal import Decimal
import hashlib
import json
import re
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from iso20022_quality import parse_pain001

REV = "eef56caf0c93cee277cacce6f93181b4518b8669"
BASE = f"https://raw.githubusercontent.com/sebastienrousseau/pain001/{REV}/pain001/corpus/data/market/"
SAMPLES = {
    "ch/sepa-credit-transfer/ch.sepa.sct.pain.001.001.09.xml": 1,
    "cz/sepa-credit-transfer/cz.sepa.sct.pain.001.001.09.xml": 1,
    "de/sepa-instant/de.sepa.sct-inst.pain.001.001.09.xml": 1,
    "se/salary/se.bankgiro.salary.pain.001.001.09.xml": 2,
}


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "iso20022-compatibility-validation"}), timeout=15) as r:
        data = r.read(250_001)
    if len(data) > 250_000:
        raise ValueError("Public example exceeds expected size")
    return data


def main():
    output = {}
    namespace = "{urn:iso:std:iso:20022:tech:xsd:pain.001.001.09}"
    for path, expected_rows in SAMPLES.items():
        sample = fetch(BASE + path)
        provenance = fetch(BASE + path.removesuffix(".xml") + ".provenance.yaml").decode("utf-8")
        declared_hash = re.search(r"(?m)^sha256:\\s*([a-f0-9]{64})\\s*$", provenance)
        if not declared_hash:
            raise AssertionError("Missing independent provenance digest: " + path)
        if hashlib.sha256(sample).hexdigest() != declared_hash.group(1):
            raise AssertionError("Upstream fixture digest mismatch: " + path)
        root = ET.fromstring(sample)
        source_rows = root.findall(
            f"./{namespace}CstmrCdtTrfInitn/{namespace}PmtInf/{namespace}CdtTrfTxInf"
        )
        if len(source_rows) != expected_rows:
            raise AssertionError("Unexpected count in pinned source: " + path)
        header_sum = root.find(
            f"./{namespace}CstmrCdtTrfInitn/{namespace}GrpHdr/{namespace}CtrlSum"
        )
        parsed = parse_pain001(sample, profile="base")
        parsed_total = sum((p.amount for p in parsed.payments if p.amount is not None), Decimal(0))
        expected_total = Decimal(header_sum.text)
        assert len(parsed.payments) == len(source_rows) == expected_rows, path
        assert parsed_total == expected_total, (path, parsed_total, expected_total)
        assert not any(x.level == "error" for x in parsed.diagnostics), path
        assert all(p.amount is not None and p.amount > 0 for p in parsed.payments), path
        output[path] = {
            "records": len(parsed.payments), "total": str(parsed_total),
            "record_errors": sum(d.level == "error" for p in parsed.payments for d in p.issues),
            "source_commit": REV,
        }
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
