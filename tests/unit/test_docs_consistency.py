"""Implementation contracts must stay true to the code: required header, every
diagnostic code they cite is registered, every test file they cite exists."""
import re
from pathlib import Path

from lang.diagnostics.codes import CODES

ROOT = Path(__file__).resolve().parents[2]
DOCS = sorted((ROOT / "docs" / "semantics").glob("*.md"))
HEADER = ("This file is an implementation contract derived from V3.\nIt has no authority over V3.\n"
          "If this file conflicts with V3, V3 wins.")


def test_contracts_exist():
    assert len(DOCS) >= 12


def test_every_contract_has_the_required_header():
    for d in DOCS:
        assert HEADER in d.read_text(), d.name


def test_cited_codes_are_registered():
    bad = []
    for d in DOCS:
        for c in re.findall(r"`([ASWRCH]\.[A-Z_]+\.[A-Z_]+)`", d.read_text()):
            if c not in CODES:
                bad.append(f"{d.name}: {c}")
    assert not bad, bad


def test_cited_test_files_exist():
    bad = []
    for d in DOCS:
        for f in re.findall(r"`(tests/[\w/]+\.py)", d.read_text()):
            if not (ROOT / f).exists():
                bad.append(f"{d.name}: {f}")
    assert not bad, bad
