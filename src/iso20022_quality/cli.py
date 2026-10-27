"""Small CLI emitting redacted, aggregate quality metrics as JSON."""

import argparse
import json
from dataclasses import asdict

from .readiness import assess_readiness
from .xml import parse_camt053, parse_pain001, read_xml_file


def main() -> None:
    parser = argparse.ArgumentParser(description="ISO 20022 payment-quality report")
    parser.add_argument(
        "--payment",
        metavar="FILE",
        action="append",
        required=True,
        help="pain.001.001.09 XML (repeat for multiple files)",
    )
    parser.add_argument(
        "--statement",
        metavar="FILE",
        action="append",
        default=[],
        help="camt.053.001.08 XML (repeat for multiple files)",
    )
    parser.add_argument("--profile", choices=("sepa_sct", "base"), default="sepa_sct")
    args = parser.parse_args()
    payments = [parse_pain001(read_xml_file(path), profile=args.profile) for path in args.payment]
    statements = [parse_camt053(read_xml_file(path)) for path in args.statement]
    print(json.dumps(asdict(assess_readiness(payments, statements)), indent=2))


if __name__ == "__main__":
    main()
