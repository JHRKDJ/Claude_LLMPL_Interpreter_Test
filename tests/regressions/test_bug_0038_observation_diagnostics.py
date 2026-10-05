"""BUG-0038 (second audit, C16/F16): a child exception that the body had caught
(`try await h catch Boom => 0`) was listed in a later TaskGroupFailure as
`R.ERROR.UNHANDLED ... threw`, and an awaited abandoned child appeared twice (as the
cause of A.TASK.AWAITED_ABANDONED and again as a group child). V3 8.10: "No failure is
displayed twice"; a handled failure is context, not an unhandled error."""
from tests.helpers import run


def test_handled_child_failure_is_labelled_handled():
    r = run("""
error Boom { n: Int }
async fn bad() -> Int throws Boom { await sleep(1.millis)
  throw Boom(n: 1) }
async fn ab() -> Int { await sleep(5.millis)
  assert false, "late abandon"
  return 0 }
async fn main() {
    parallel {
        let h = spawn bad()
        let g = spawn ab()
        let x = try await h catch Boom => 0
        print("handled", x)
        await g
    }
}""")
    d = r.diag
    assert d.stable_code == "A.TASK.GROUP_FAILURE"
    kids = [c.stable_code for c in d.children]
    assert "R.ERROR.UNHANDLED" not in kids and "I.TASK.HANDLED_FAILURE" in kids, kids
    handled = [c for c in d.children if c.stable_code == "I.TASK.HANDLED_FAILURE"][0]
    assert handled.severity == "info" and "Boom" in handled.message


def test_awaited_abandoned_child_shown_once():
    r = run("""
async fn ab() -> Int { await sleep(1.millis)
  assert false, "child broke"
  return 1 }
async fn main() {
    let rep = parallel collect {
        let h = spawn ab()
        let r = capture await h
        print("body continues", r)
    }
}""")
    def count(d):
        n = 1 if d.stable_code == "A.ASSERT.FAILED" else 0
        return n + sum(count(c) for c in list(d.causes) + list(d.children))
    assert sum(count(d) for d in r.diags) == 1, r.text()
