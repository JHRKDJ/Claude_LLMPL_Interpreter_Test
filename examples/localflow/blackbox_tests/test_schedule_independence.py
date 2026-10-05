"""LF-002: LocalFlow's results must not depend on the order in which tasks that are
ready at the same logical instant run. Runs every fixture under seeded random
scheduling (V3 7.14.5 stress mode) and requires oracle equality."""
import pytest

from harness import FIXTURES, run_localflow, run_oracle, strip_messages

NAMES = sorted(p.stem for p in FIXTURES.glob("s*.json")) + \
    sorted("regressions/" + p.stem for p in (FIXTURES / "regressions").glob("*.json"))
SEEDS = (1, 2, 3)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", NAMES)
def test_random_schedule_matches_oracle(name, seed, tmp_path):
    fx = FIXTURES / f"{name}.json"
    exp = run_oracle(fx, tmp_path / "expected")
    got, stderr = run_localflow(fx, tmp_path / "actual", ("--schedule=random", f"--seed={seed}"))
    assert got.exit == exp.exit, stderr[-2000:]
    assert strip_messages(got.report) == strip_messages(exp.report)
    assert got.files == exp.files
