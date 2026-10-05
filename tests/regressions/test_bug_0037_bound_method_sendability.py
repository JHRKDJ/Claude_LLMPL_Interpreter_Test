"""BUG-0037 (second audit, C14/F14): a bound method of a mutable record (`c.bump`) was
silently graph-copied across a task boundary, while the equivalent closure
`fn() => c.bump()` was rejected. A bound method closes over its receiver, so the same
rule applies: closures with mutable captures are rejected (V3 5.11)."""
from tests.helpers import run


def test_bound_method_of_mutable_receiver_rejected():
    r = run("""
mutable record Counter { n: Int
    fn bump(self) -> Int { self.n = self.n + 1
        return self.n } }
async fn run(f: fn() -> Int) -> Int { return f() }
async fn main() {
    let c = Counter(n: 0)
    let v = parallel { let h = spawn run(c.bump)
        await h }
    print(v, c.n)
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"], r.text()
    assert "bound method of a mutable value" in r.diag.message


def test_bound_method_of_frozen_receiver_shared():
    r = run("""
record P { x: Int
    fn get(self) -> Int { return self.x } }
async fn run(f: fn() -> Int) -> Int { return f() }
async fn main() {
    let p = P(x: 4)
    print(parallel { let h = spawn run(p.get)
        await h })
}""")
    assert r.lines == ["4"], r.text()
