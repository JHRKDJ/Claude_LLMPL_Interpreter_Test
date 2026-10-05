"""BUG-0023 (second audit, C06/F6): when external cancellation coincided with a child's
recoverable failure, `firstSuccess` and `collect` groups raised plain cancellation and
the failure vanished (V3 5.12.11/8.11: preserve both — the failure is processed and the
cancellation stays pending). A `collect` body that threw also lost earlier unobserved
child failures (5.12.5: each contributes once)."""
from tests.helpers import run

ERR = """
error Boom { n: Int }
async fn failsoon() -> Int throws Boom { await sleep(1.millis)
  throw Boom(n: 1) }
async fn slow() -> Int throws Boom { await sleep(100.millis)
  return 2 }
"""


def test_first_success_failure_processed_then_cancellation_redelivered():
    r = run(ERR + """
async fn main() {
    let r = try within 5.millis {
        let v = try parallel firstSuccess { spawn failsoon()
            spawn slow() } catch AggregateException as e => { print("group failure processed:", e.entries.length)
               -1 }
        print("after group", v)
        await sleep(1.millis)
        v
    } catch DeadlineExceeded => 99
    print("result", r)
}""")
    assert r.lines == ["group failure processed: 1", "after group -1", "result 99"], r.text()


def test_collect_report_kept_when_cancellation_coincides():
    r = run(ERR + """
async fn main() {
    let r = try within 5.millis {
        let rep = parallel collect { spawn failsoon()
            spawn slow() }
        print("report", rep.outcomes.length)
        await sleep(1.millis)
        0
    } catch DeadlineExceeded => 99
    print("result", r)
}""")
    assert r.lines == ["report 2", "result 99"], r.text()


def test_collect_body_throw_keeps_child_failures():
    r = run(ERR + """
async fn main() {
    let n = try parallel collect { spawn failsoon()
        await sleep(2.millis)
        throw Boom(n: 2) } catch AggregateException as a => a.entries.map(fn(e) => (e.error as Boom).n)
    print(n)
}""")
    assert r.lines == ["[1, 2]"], r.text()
