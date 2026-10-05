"""BUG-0029 (second audit, C07/F7): a closure capturing a resource borrow could escape
its scope — as the `use` scope's value, into an outer binding, a collection or a
record — with no diagnostic; misuse surfaced only if it was later called
(A.RESOURCE.USE_AFTER_RELEASE). V3 5.5.5/5.5.8: a resource may not be "captured by an
escaping closure". A closure capturing a borrow is itself borrow-like."""
from tests.helpers import check, run

PROV = """
resource fn connect(n: Int) yields Int {
    let e = yield n
}
"""


def test_closure_as_use_scope_value():
    src = PROV + "fn main() { let f = use c = connect(1) { fn() => c + 1 }\n print(\"got closure\") }"
    assert "S.RESOURCE.ESCAPE" in check(src, "verified").check_errors
    r = run(src)
    assert r.codes == ["A.RESOURCE.ESCAPE"] and "got closure" not in r.stdout, r.text()


def test_closure_stored_in_outer_binding_or_collection():
    for body in ("g = fn() => c + 1", "fs.push(fn() => c + 1)"):
        src = PROV + ("fn main() { let fs: MutableList[fn() -> Int] = MutableList.of()\n let g: fn() -> Int = fn() => 0\n"
                      "  use c = connect(1) { " + body + " }\n print(g()) }")
        assert "S.RESOURCE.ESCAPE" in check(src, "verified").check_errors, body


def test_non_escaping_uses_still_allowed():
    r = run(PROV + """
fn twice(f: borrow fn() -> Int) -> Int { return f() + f() }
fn main() { let v = use c = connect(5) {
    let xs = [1, 2].map(fn(x) => x + c)
    (fn() => c * 2)() + twice(fn() => c + 0) + xs[1] }
  print(v) }""")
    assert r.lines == ["27"], r.text()
