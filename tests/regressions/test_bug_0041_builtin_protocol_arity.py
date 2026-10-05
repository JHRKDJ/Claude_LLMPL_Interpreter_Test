"""BUG-0041 (second audit, T10): protocol conformance of built-in values checked only
method names: a `List` passed as `protocol Getter { fn get(self) -> Int }` although
`List.get` takes one argument — verified mode accepted it and the failure surfaced
inside typed code as A.TYPE.ARITY (V3 5.3.6: the shape check covers "required methods,
compatible arities")."""
from tests.helpers import check, run

SRC = """
protocol Getter { fn get(self) -> Int }
fn use1(g: Getter) -> Int { print("entered")
  return g.get() }
fn main() { print(use1([1, 2, 3])) }"""


def test_static_rejection():
    assert "S.TYPE.STATIC_MISMATCH" in check(SRC, "verified").check_errors


def test_boundary_rejection_at_runtime():
    r = run(SRC)
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"] and "entered" not in r.stdout, r.text()


def test_conforming_builtin_still_accepted():
    r = run("""
protocol Sized { fn isEmpty(self) -> Bool }
fn empty(s: Sized) -> Bool { return s.isEmpty() }
fn main() { print(empty([1]), empty("")) }""", mode="verified")
    assert r.lines == ["false true"], r.text()
