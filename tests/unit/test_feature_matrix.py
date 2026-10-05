"""FEATURE_MATRIX.md evidence stays real: every row has a final state, and every test
reference in the Tests column names an existing test file and (where given) at least
one existing test function (`*` is a wildcard)."""
import fnmatch
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATRIX = (ROOT / "FEATURE_MATRIX.md").read_text()
ROWS = re.findall(r"^\| ([A-Z]{2,3}-\d\d) \|(.*)\|$", MATRIX, re.M)
PREFIX = {"c": "tests/conformance", "n": "tests/negative", "i": "tests/interactions", "t": "tests/tooling",
          "u": "tests/unit"}


def _functions(path: Path) -> list[str]:
    return re.findall(r"^def (test_\w+)", path.read_text(), re.M)


def test_every_row_has_a_final_state():
    for rid, rest in ROWS:
        state = [c.strip() for c in rest.split("|")][5]
        assert state in ("COMPLETE", "DEFERRED", "OUT_OF_SCOPE"), (rid, state)


def test_test_references_resolve():
    checked = 0
    for rid, rest in ROWS:
        tests_cell = [c.strip() for c in rest.split("|")][4]
        for ref in re.split(r";\s*", tests_cell):
            m = re.match(r"([cnitu])/(test_\w+)(?:::(.+))?$", ref.strip())
            if m:
                path = ROOT / PREFIX[m.group(1)] / f"{m.group(2)}.py"
                if not path.exists():  # a bare test-function reference, e.g. i/test_int013_*
                    fns = [f for p in (ROOT / PREFIX[m.group(1)]).glob("test_*.py") for f in _functions(p)]
                    assert any(fnmatch.fnmatch(f, m.group(2) + "*") for f in fns), (rid, ref)
                    checked += 1
                    continue
                if m.group(3):
                    fns = _functions(path)
                    for pat in re.split(r",\s*", m.group(3)):
                        pat = re.sub(r"\s*\(.*\)$", "", pat)
                        assert any(fnmatch.fnmatch(f, "test_" + pat) or fnmatch.fnmatch(f, pat) for f in fns), \
                            (rid, ref, pat)
                checked += 1
            m = re.match(r"r/(\d{4})", ref.strip())
            if m:
                assert list((ROOT / "tests/regressions").glob(f"test_bug_{m.group(1)}_*.py")), (rid, ref)
    assert checked > 150
