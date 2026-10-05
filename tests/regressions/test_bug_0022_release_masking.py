"""BUG-0022 (second audit, C05/F5): normal provider release was masked only when the
scope body itself had been cancelled. A cancellation arriving *during* the release of a
normally-completed body (e.g. a race loser) interrupted the release at its first await,
leaking the resource (V3 5.5.9, 6.7, 8.5: release runs under masking)."""
from tests.helpers import run


def test_release_completes_when_cancellation_arrives_during_it():
    r = run("""
async resource fn conn() yields Int {
    let exit = yield 1
    print("release start", exit)
    await sleep(10.millis)
    print("release finished")
}
async fn quick() -> Int { await sleep(1.millis)
   return 1 }
async fn user() -> Int {
    use c = await conn() { print("body done") }
    await sleep(100.millis)
    return 2
}
async fn main() {
    let w = parallel race { spawn quick()
       spawn user() }
    print("winner", w, time.now())
}""")
    assert r.lines == ["body done", "release start ScopeExit.Normal", "release finished", "winner 1 Instant(10ms)"], \
        r.text()
