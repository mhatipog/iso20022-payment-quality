"""Opt-in live compatibility smoke against publicly documented bank *examples*.

Run: python examples/public_bank_smoke.py
Only fetches two public example pages; does not transmit local payment files.
Not an XSD/conformance test and not a test on private production banking records.
"""

import json
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from iso20022_quality import parse_camt053, parse_pain001

SAMPLES = {
    "goldman-pain.001.001.09": (
        "https://developer.gs.com/docs/services/transaction-banking/pain001v9-sepact",
        parse_pain001,
    ),
    "goldman-camt.053.001.08": (
        "https://developer.gs.com/docs/services/transaction-banking/camt-053-eu-v8-sample",
        parse_camt053,
    ),
}


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def fetch_xml_example(url: str) -> str:
    with urlopen(
        Request(url, headers={"User-Agent": "iso20022-quality-doc-smoke/0.2"}), timeout=20
    ) as r:
        data = r.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("Public example page exceeds 2 MB limit")
    page = _PageText()
    page.feed(data.decode("utf-8"))
    text = "".join(page.parts)
    start = text.find("<?xml")
    if start == -1:
        # Some documentation sites omit the XML declaration.
        start = text.find("<Document ")
    end = text.find("</Document>", start)
    if start == -1 or end == -1:
        raise ValueError("No visible Document block found on the bank example page")
    return text[start : end + len("</Document>")]


def main():
    result = {}
    for name, (url, reader) in SAMPLES.items():
        xml = fetch_xml_example(url)
        parsed = reader(xml)
        records = parsed.payments if hasattr(parsed, "payments") else parsed.entries
        if not records:
            raise AssertionError(f"No banking records extracted from {name}")
        result[name] = {
            "record_count": len(records),
            "warning_count": sum(i.level == "warning" for x in records for i in x.issues),
            "error_count": sum(i.level == "error" for x in records for i in x.issues),
            "file_diagnostics": sorted({i.code for i in parsed.diagnostics}),
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
