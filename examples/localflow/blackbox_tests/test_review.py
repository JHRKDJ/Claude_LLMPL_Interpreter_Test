"""Fixtures from the final adversarial review (AUDIT-003): boundary and composition
cases written by an independent reviewer, compared with the oracle at byte level under
FIFO and one seeded random schedule."""
import pytest

from harness import FIXTURES, run_localflow, run_oracle, strip_messages

NAMES = sorted(p.stem for p in (FIXTURES / "review").glob("*.json"))


@pytest.mark.parametrize("sched", [(), ("--schedule=random", "--seed=5")], ids=["fifo", "random5"])
@pytest.mark.parametrize("name", NAMES)
def test_review_fixture_matches_oracle(name, sched, tmp_path):
    fx = FIXTURES / "review" / f"{name}.json"
    exp = run_oracle(fx, tmp_path / "expected")
    got, stderr = run_localflow(fx, tmp_path / "actual", sched)
    assert got.exit == exp.exit, stderr[-2000:]
    assert strip_messages(got.report) == strip_messages(exp.report)
    assert got.files == exp.files and got.stdout == exp.stdout
    assert got.tree == exp.tree and got.layout == exp.layout
