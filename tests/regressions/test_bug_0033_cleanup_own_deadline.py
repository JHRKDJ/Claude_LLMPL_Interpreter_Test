"""BUG-0033 (second audit, C11/F11): cancellation masking during cleanup also
suppressed deadlines the cleanup itself opened, so a cleanup could not bound its own
duration with `within` (V3 5.6.3/7.10.11: masking delays the *pending* cancellation;
safe cleanup duration is domain-specific, i.e. bounded by the program)."""
from tests.helpers import run


def test_cleanup_can_bound_itself_with_within():
    r = run("""
async fn worker() {
    defer {
        let r = try within 2.millis { await sleep(1000.millis)
             "slept" } catch DeadlineExceeded => "cleanup bounded itself"
        print(r, time.now())
    }
    await sleep(1000.millis)
}
async fn main() {
    let r = try within 1.millis { await worker() } catch DeadlineExceeded => "timeout"
    print(r, time.now())
}""")
    assert r.lines == ["cleanup bounded itself Instant(3ms)", "timeout Instant(3ms)"], r.text()


def test_outer_cancellation_still_masked_during_cleanup():
    r = run("""
async fn worker() {
    defer { await sleep(5.millis)
        print("cleanup completed", time.now()) }
    await sleep(1000.millis)
}
async fn main() {
    let r = try within 1.millis { await worker() } catch DeadlineExceeded => "timeout"
    print(r, time.now())
}""")
    assert r.lines == ["cleanup completed Instant(6ms)", "timeout Instant(6ms)"], r.text()
