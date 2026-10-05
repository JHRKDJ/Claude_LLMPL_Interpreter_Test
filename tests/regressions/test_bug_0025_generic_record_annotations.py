"""BUG-0025 (second audit, T05): annotations naming a generic record instantiation were
never enforced at run time: `Box[Int](v: "s")` built a Box holding a Str, and typed code
reading `b.v` with `b: Box[Int]` used a Str as an Int (V3 5.3.2/5.3.7; IMPL-006 says
concrete type arguments remain enforced)."""
from tests.helpers import run


def test_explicit_type_arguments_checked_at_construction():
    r = run("record Box[T] { v: T }\nfn main() { let b = Box[Int](v: \"s\")\n print(b) }")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"], r.text()


def test_field_read_through_generic_annotation_checked():
    r = run("""
record Box[T] { v: T }
fn id(x) { return x }
fn wrap(b: Box[Int]) -> List[Int] { let n = b.v
  return [n, n] }
fn main() { print(wrap(id(Box(v: "not an int")))) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"], r.text()


def test_well_typed_generic_records_unaffected():
    r = run("""
record Box[T] { v: T }
fn get(b: Box[Int]) -> Int { return b.v + 1 }
fn main() { print(get(Box[Int](v: 1)), get(Box(v: 2)), Box[Str](v: "x").v) }""")
    assert r.lines == ["2 3 x"], r.text()
