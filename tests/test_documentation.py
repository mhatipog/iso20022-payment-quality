"""Check that the documented, offline repository entry points do not rot."""

from pathlib import Path
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent


def test_relative_markdown_links_point_to_existing_files():
    pages = [
        ROOT / "README.md", ROOT / "PUBLISHING.md",
        ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md",
        *sorted((ROOT / "docs").glob("*.md")),
    ]
    for page in pages:
        assert page.is_file()
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", page.read_text(encoding="utf-8")):
            if link.startswith(("https://", "http://", "mailto:", "#")):
                continue
            relative = unquote(link.split("#", 1)[0])
            if not relative:
                continue
            assert (page.parent / relative).is_file(), (page, link)


def test_source_distribution_docs_use_actual_version():
    source = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version\s*=\s*"([^"]+)"', source, re.MULTILINE)
    assert version
    assert f"experimental {version.group(1)}" in (ROOT / "README.md").read_text(
        encoding="utf-8"
    ).lower()


def test_offline_verification_assets_exist():
    for name in (
        "scripts/verify.py", "examples/demo.py",
        "examples/migration_acceptance.py",
        "tests/fixtures/pain09.xml", "tests/fixtures/camt08.xml",
        "tests/fixtures/pain002_10.xml",
    ):
        assert (ROOT / name).is_file()
