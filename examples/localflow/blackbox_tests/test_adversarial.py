"""Adversarial acceptance cases (TEST_PLAN.md §Adversarial review): behaviours a
plausible-but-wrong implementation could get wrong. Oracle equality under FIFO and
random scheduling, plus pinned expectations that do not rely on the oracle."""
import pytest

from harness import FIXTURES, run_localflow, run_oracle, strip_messages

NAMES = sorted(p.stem for p in (FIXTURES / "adversarial").glob("*.json"))


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    cache = {}

    def get(name, sched=()):
        key = (name, sched)
        if key not in cache:
            d = tmp_path_factory.mktemp(name)
            fx = FIXTURES / "adversarial" / f"{name}.json"
            cache[key] = (run_oracle(fx, d / "e"), run_localflow(fx, d / "a", sched))
        return cache[key]
    return get


@pytest.mark.parametrize("sched", [(), ("--schedule=random", "--seed=7")], ids=["fifo", "random7"])
@pytest.mark.parametrize("name", NAMES)
def test_adversarial_matches_oracle(name, sched, runs):
    exp, (got, stderr) = runs(name, sched)
    assert got.exit == exp.exit, stderr[-2000:]
    assert strip_messages(got.report) == strip_messages(exp.report)
    assert got.files == exp.files and got.stdout == exp.stdout
    assert got.tree == exp.tree and got.layout == exp.layout


def jobs(runs, name):
    _, (got, _) = runs(name)
    return {j["id"]: j for j in got.report["jobs"]}, got


def test_a01_backoff_keeps_the_slot(runs):
    js, _ = jobs(runs, "a01_slot_held_during_backoff")
    assert js["flaky"]["end"] == 14 and js["waiter"]["start"] == 14


def test_a02_group_limit_does_not_block_other_jobs(runs):
    js, _ = jobs(runs, "a02_group_head_does_not_block")
    assert js["free1"]["start"] == 0 and js["g2"]["start"] == 10


def test_a03_cancellation_during_backoff(runs):
    js, got = jobs(runs, "a03_cancel_during_backoff")
    assert js["flaky"]["status"] == "CANCELLED" and js["flaky"]["attempts"] == 1
    assert js["after"]["status"] == "NOT_RUN" and got.exit == 12


def test_a04_cancellation_wins_over_failfast_at_the_same_instant(runs):
    js, got = jobs(runs, "a04_failfast_and_cancel_same_instant")
    assert got.report["status"] == "CANCELLED" and js["bad"]["status"] == "FAILED"


def test_a05_timeouts_are_inclusive_and_retried(runs):
    js, _ = jobs(runs, "a05_timeout_retry_boundaries")
    assert (js["t"]["attempts"], js["t"]["error"]["class"], js["t"]["end"]) == (3, "timeout", 21)
    assert js["u"]["status"] == "SUCCEEDED"


def test_a06_skips_propagate_and_conditions_select_branch(runs):
    js, _ = jobs(runs, "a06_skipped_inputs_and_chains")
    assert js["onlyIfBig"]["skipReason"] == "condition" and js["sum"]["skipReason"] == "upstream-skipped"
    assert js["sum2"]["output"] == 3 + 1


def test_a08_root_cause_follows_blocked_chain(runs):
    js, _ = jobs(runs, "a08_blocked_rootcause_through_chain")
    assert js["leaf"]["blockedBy"] == "m2" and js["leaf"]["rootCause"] == ["f1", "f2"]


def test_a10_cancellation_reaches_nested_resources(runs):
    js, got = jobs(runs, "a10_cancel_while_sub_and_transform")
    sub = js["s"]["subreport"]
    assert sub["status"] == "CANCELLED"
    assert {j["id"]: j["status"] for j in sub["jobs"]} == {"t": "CANCELLED", "c": "SUCCEEDED"}
    assert got.files == {}


def test_a11_all_problems_reported_together(runs):
    _, got = jobs(runs, "a11_duplicates_and_missing_and_cycle_together")
    codes = [(e["code"], e["job"]) for e in got.report["errors"]]
    assert codes == [("missing-dependency", "b"), ("duplicate-id", "a"), ("malformed", "x"), ("cycle", None)]
