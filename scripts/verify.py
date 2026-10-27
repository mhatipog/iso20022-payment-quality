"""One-command, offline repository verification (Python >=3.10).

Dependencies are installed ahead of time with `pip install -e '.[dev]'`.
The scripts and fixtures are part of the source checkout, not the wheel.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run offline banking quality checks")
    parser.add_argument(
        "--spark", action="store_true",
        help="also run real PySpark integration tests (requires pip install -e '.[spark,dev]')",
    )
    args = parser.parse_args()

    run(sys.executable, "-m", "ruff", "check", "src", "tests", "examples", "scripts")
    run(
        sys.executable, "-m", "pytest", "-q",
        "--ignore=tests/test_spark_optional.py",
        "--cov=iso20022_quality", "--cov-fail-under=90", "--cov-report=term-missing",
        "--cov-report=xml:coverage.xml",
    )
    run(sys.executable, "examples/demo.py")
    run(sys.executable, "examples/migration_acceptance.py")
    run(
        sys.executable, "-m", "iso20022_quality.cli",
        "--payment", "tests/fixtures/pain09.xml",
        "--statement", "tests/fixtures/camt08.xml",
    )
    if args.spark:
        run(sys.executable, "-m", "pytest", "-q", "tests/test_spark_optional.py")


if __name__ == "__main__":
    main()
