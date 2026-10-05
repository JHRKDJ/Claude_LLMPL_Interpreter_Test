"""BUG-0024 (second audit, T04): a `MutableList[Str]` was accepted by a parameter
annotated `MutableList[Int]` (the boundary ignored the collection's runtime element
type), and typed code then pushed a dynamically produced Str into it unchecked.
V3 5.3.2/7.6.3: written annotations are enforced; "writing checks before insertion"."""
from tests.helpers import run


def test_element_type_metadata_checked_at_boundary():
    r = run("""
fn id(x) { return x }
fn addTo(xs: MutableList[Int]) { xs.push(1) }
fn main() { let raw = MutableList[Str]()
  addTo(id(raw)) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"], r.text()


def test_write_into_typed_collection_checked():
    r = run("""
fn id(x) { return x }
fn addTo(xs: MutableList[Int]) { xs.push(id("zzz"))
  print("after push:", xs) }
fn main() { let raw = MutableList.of()
  addTo(raw) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"], r.text()
    assert "after push" not in r.stdout


def test_map_write_checked_and_well_typed_writes_pass():
    r = run("""
fn id(x) { return x }
fn put(m: MutableMap[Str, Int], k: Str) { m.set(k, id(k)) }
fn ok(m: MutableMap[Str, Int]) { m.set("a", 1)
  print(m) }
fn main() { let m = MutableMap[Str, Int]()
  ok(m)
  put(m, "b") }""")
    assert r.lines == ['MutableMap{"a": 1}'], r.text()
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
