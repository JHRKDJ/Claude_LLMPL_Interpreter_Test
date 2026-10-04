"""BUG-0002: a task group whose children were cancelled by *external* cancellation
must propagate cancellation after quiescence (V3 7.10.4 "External cancellation only:
propagate cancellation after quiescence"; 7.10.5 collect likewise), not return
normally as if every child had succeeded."""
from tests.helpers import ok


def test_failfast_external_cancel_propagates():
    r = ok("""
async fn sleeper() { await sleep(1.seconds) }
async fn group() { parallel { spawn sleeper() } }
async fn main() {
    let r = try within 5.millis {
        group()
        print("group returned normally (wrong)")
        "no"
    } catch DeadlineExceeded => "deadline"
    print(r)
}""")
    assert r.lines == ["deadline"]


def test_collect_external_cancel_propagates():
    r = ok("""
async fn sleeper() -> Int { await sleep(1.seconds)
 return 1 }
async fn main() {
    let r = try within 5.millis {
        let rep = parallel collect { spawn sleeper() }
        print("collect returned a report (wrong)")
        "no"
    } catch DeadlineExceeded => "deadline"
    print(r)
}""")
    assert r.lines == ["deadline"]


def test_completed_group_returns_and_cancellation_stays_pending():
    # Nothing in the group was affected by the cancellation: it returns normally and
    # the pending cancellation is delivered at the next cancellation point.
    r = ok("""
async fn quick() -> Int { return 3 }
async fn main() {
    let r = try within 0.millis {
        let v = parallel { let h = spawn quick()
 await h }
        print("group value {v}")
        await sleep(1.millis)
        "no"
    } catch DeadlineExceeded => "deadline"
    print(r)
}""")
    assert r.lines[-1] == "deadline"
