"""LocalFlow acceptance: oracle equality on every fixture + scenario-specific pins
(TEST_PLAN.md)."""
import json

import pytest

from harness import FIXTURES, run_localflow, run_oracle, strip_messages

FIXTURE_NAMES = sorted(p.stem for p in FIXTURES.glob("s*.json"))


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    cache = {}

    def get(name):
        if name not in cache:
            d = tmp_path_factory.mktemp(name)
            fx = FIXTURES / f"{name}.json"
            exp = run_oracle(fx, d / "expected")
            got, stderr = run_localflow(fx, d / "actual")
            cache[name] = (exp, got, stderr)
        return cache[name]
    return get


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_matches_oracle(name, results):
    exp, got, stderr = results(name)
    assert got.exit == exp.exit, stderr[-3000:]
    assert strip_messages(got.report) == strip_messages(exp.report), (
        json.dumps(strip_messages(got.report), indent=1)[:4000], stderr[-2000:])
    assert got.files == exp.files
    assert got.stdout == exp.stdout


def job(report, jid):
    return next(j for j in report["jobs"] if j["id"] == jid)


def test_s01_single(results):
    exp, got, _ = results("s01_single")
    j = job(got.report, "only")
    assert (j["status"], j["output"], j["start"], j["end"]) == ("SUCCEEDED", 6765, 0, 5)


def test_s02_chain_starts_after_dependency(results):
    _, got, _ = results("s02_chain")
    a, b, c = (job(got.report, x) for x in "abc")
    assert b["start"] == a["end"] and c["start"] == b["end"]


def test_s05_bounded_concurrency(results):
    _, got, _ = results("s05_bounded")
    spans = [(j["start"], j["end"], j["id"]) for j in got.report["jobs"]]
    for t in range(0, got.report["durationMs"]):
        running = [i for s, e, i in spans if s <= t < e]
        assert len(running) <= 3
        assert sum(1 for i in running if i in ("e1", "e2")) <= 1


def test_s08_cycle_lists_cycle_members(results):
    _, got, _ = results("s08_cycle")
    cyc = next(e for e in got.report["errors"] if e["code"] == "cycle")
    assert cyc["jobs"] == ["a", "b", "c", "d"] and got.exit == 10


def test_s09_retry_timeline(results):
    _, got, _ = results("s09_retry_success")
    j = job(got.report, "flaky")
    assert (j["attempts"], j["end"], j["output"]) == (3, 24, 42)


def test_s11_permanent_not_retried(results):
    _, got, _ = results("s11_permanent")
    assert job(got.report, "perm")["attempts"] == 1


def test_s15_failfast_cancels_and_keeps_same_instant_result(results):
    _, got, _ = results("s15_failfast")
    assert [job(got.report, x)["status"] for x in ("bad", "slow", "later", "same")] == [
        "FAILED", "CANCELLED", "NOT_RUN", "SUCCEEDED"]


def test_s16_cancellation_releases_resources(results):
    _, got, _ = results("s16_cancel_resource")
    assert job(got.report, "t")["status"] == "CANCELLED"
    assert got.files == {} and got.exit == 12


def test_s20_cleanup_failure_after_failure_keeps_primary(results):
    _, got, _ = results("s20_cleanup_fails")
    both = job(got.report, "both")["error"]
    assert both["class"] == "transform" and both["details"] == ["cleanup"]
    assert job(got.report, "only")["error"]["class"] == "cleanup"


def test_s21_concurrent_failures_all_reported(results):
    _, got, _ = results("s21_concurrent_failures")
    assert [job(got.report, x)["error"]["class"] for x in ("f1", "f2", "f3")] == [
        "permanent", "retries-exhausted", "permanent"]


def test_s26_repeated_runs_identical(tmp_path):
    fx = FIXTURES / "s26_deterministic.json"
    a, _ = run_localflow(fx, tmp_path / "a")
    b, _ = run_localflow(fx, tmp_path / "b")
    assert a.report == b.report and a.stdout == b.stdout


def test_s30f_internal_defect_stops_without_report(results):
    _, got, stderr = results("s30f_assert_defect")
    assert got.exit == 3 and got.report is None and "A.ASSERT.FAILED" in stderr
