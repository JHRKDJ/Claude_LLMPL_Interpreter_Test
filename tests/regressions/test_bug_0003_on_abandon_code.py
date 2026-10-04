"""BUG-0003: the runtime reported a restricted `onAbandon` action (a user method that is
not a built-in abandonment-safe release primitive, V3 5.5.11 / 7.9.4) under the
unrelated code A.RESOURCE.PROVIDER_OUTSIDE_USE. It must use its own stable code."""
from tests.helpers import run_unchecked

SRC = """
mutable record R { n: Int
 fn undo(self) { } }
resource fn p() yields R {
    let r = R(n: 1)
    onAbandon r.undo()
    yield r
}
fn main() { use x = p() { } }"""


def test_runtime_on_abandon_restriction_code():
    r = run_unchecked(SRC)
    assert r.codes == ["A.RESOURCE.ON_ABANDON_RESTRICTED"]
