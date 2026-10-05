"""BUG-0009 (found writing LocalFlow): (a) a tuple type written as a type argument in
value position — `MutableList[(Str, Int)]()` — was typed as `Dyn` elements, which made
`match xs.last() { Some((a, _)) => …, None => … }` a false non-exhaustive warning;
(b) tuple destructuring `let (a, b) = e` of a statically non-tuple value (e.g. the
`T?` returned by `pop()`) was not reported, although it can only abandon."""
from tests.helpers import check, run


def test_tuple_type_argument_gives_precise_element_type():
    r = check("""
fn f() -> Int {
    let work = MutableList[(Str, Int)]()
    work.push(("a", 1))
    return match work.last() { Some((name, n)) => n, None => 0 }
}""", "verified")
    assert r.check == [], r.text()


def test_destructuring_a_non_tuple_is_reported():
    r = check("""
fn f() -> Int {
    let work = MutableList[(Str, Int)]()
    let (a, b) = work.pop()
    return b
}""", "verified")
    assert "S.TYPE.STATIC_MISMATCH" in r.check_errors


def test_runtime_still_abandons_when_unchecked():
    r = run("""
fn main() { let work = MutableList[(Str, Int)]()
 work.push(("a", 1))
 let (a, b) = work.pop()
 print(b) }""")
    assert r.codes and r.codes[0].startswith("A.")
