"""LocalFlow application regressions (fixtures/regressions/), oracle equality."""
import pytest

from harness import FIXTURES, run_localflow, run_oracle, strip_messages

NAMES = sorted(p.stem for p in (FIXTURES / "regressions").glob("*.json"))


@pytest.mark.parametrize("name", NAMES)
def test_regression_matches_oracle(name, tmp_path):
    fx = FIXTURES / "regressions" / f"{name}.json"
    exp = run_oracle(fx, tmp_path / "expected")
    got, stderr = run_localflow(fx, tmp_path / "actual")
    assert got.exit == exp.exit, stderr[-2000:]
    assert strip_messages(got.report) == strip_messages(exp.report)
    assert got.files == exp.files and got.stdout == exp.stdout
    assert got.tree == exp.tree and got.layout == exp.layout
