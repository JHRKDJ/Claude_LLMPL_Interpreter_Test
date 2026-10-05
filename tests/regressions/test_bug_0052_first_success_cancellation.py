"""BUG-0052 (found through LocalFlow review fixture f42: an external job whose mirrors
are `hang` and `permanent`, with a timeout). A `parallel firstSuccess` group cancelled
from outside after one child had failed recoverably threw `AggregateException`, as if
every child had failed. V3 7.10.7 throws AggregateException only "if all children fail
recoverably"; a child that was cancelled did not fail, and "external cancellation
remains pending and is preserved", so the cancellation propagates (here the deadline
becomes DeadlineExceeded)."""
from tests.helpers import run

SRC = """
error Bad {}

async fn hang() -> Int {
    await sleep(1000.hours)
    return 1
}

async fn bad(ms: Int) -> Int throws Bad {
    await sleep(ms.millis)
    throw Bad()
}

async fn main() {
    let r = try within time.now() + 6.millis {
        try parallel firstSuccess {
            BODY
        }
    }
        catch DeadlineExceeded => "deadline"
        catch AggregateException as agg => "aggregate {agg.entries.length}"
    print(r)
}
"""


def test_deadline_wins_when_a_child_was_still_running():
    r = run(SRC.replace("BODY", "spawn hang()\n            spawn bad(2)"))
    assert r.stdout == "deadline\n", r.text()


def test_all_children_failing_is_still_an_aggregate():
    r = run(SRC.replace("BODY", "spawn bad(1)\n            spawn bad(2)"))
    assert r.stdout == "aggregate 2\n", r.text()


def test_success_still_wins_over_an_earlier_failure():
    src = SRC.replace("BODY", "spawn bad(1)\n            spawn ok()").replace(
        "async fn main()", "async fn ok() -> Int {\n    await sleep(3.millis)\n    return 7\n}\n\nasync fn main()")
    r = run(src.replace('catch DeadlineExceeded => "deadline"', 'catch DeadlineExceeded => 0').replace(
        'catch AggregateException as agg => "aggregate {agg.entries.length}"', "catch AggregateException => -1"))
    assert r.stdout == "7\n", r.text()
