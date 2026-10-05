"""BUG-0028 (second audit, T03): invariant field control covered only direct
assignment `x.f = v`; an invariant field holding a *mutable* value could be mutated
from outside the record's methods (`b.items.push(1)`, `a.inner.v = -50`) or aliased
(`let alias = b.items`), silently breaking the invariant until some later method
entry blamed the record. V3 5.10.7: such fields change only through operations that
participate in invariant checks (SPEC-014 control mechanism)."""
from tests.helpers import check, run

BAG = """
mutable record Bag { items: MutableList[Int]
    invariant items.length <= 2
    fn add(self, x: Int) { self.items.push(x) }
    fn snapshot(self) -> List[Int] { return self.items.freeze() } }
"""


def test_outside_access_to_mutable_invariant_field_rejected_statically():
    r = check(BAG + "pub fn f(b: Bag) { b.items.push(1) }", "draft")
    assert "S.CONTRACT.INVARIANT_FIELD_ACCESS" in r.check_errors, r.text()
    r = check(BAG + "pub fn f(b: Bag) -> Int { let alias = b.items\n return alias.length }", "draft")
    assert "S.CONTRACT.INVARIANT_FIELD_ACCESS" in r.check_errors


def test_runtime_backstop_through_dyn():
    r = run(BAG + """
fn id(x) { return x }
fn main() { let b: Dyn = id(Bag(items: MutableList[Int]()))
  b.items.push(1)
  print("not reached") }""")
    assert r.codes == ["A.CONTRACT.INVARIANT_FIELD_ACCESS"], r.text()


def test_nested_mutable_record_field():
    r = check("""
mutable record Inner { v: Int }
mutable record Acc { inner: Inner
    invariant inner.v >= 0 }
pub fn f(a: Acc) { a.inner.v = -50 }""", "draft")
    assert "S.CONTRACT.INVARIANT_FIELD_ACCESS" in r.check_errors, r.text()


def test_methods_and_frozen_invariant_fields_unaffected():
    r = run(BAG + """
mutable record Counter { n: Int
    invariant n >= 0
    fn inc(self) { self.n = self.n + 1 } }
fn main() { let b = Bag(items: MutableList[Int]())
  b.add(1)
  print(b.snapshot())
  let c = Counter(n: 0)
  c.inc()
  print(c.n) }""")
    assert r.lines == ["[1]", "1"], r.text()
