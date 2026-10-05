"""BUG-0010 (found writing LocalFlow): a block ending in `continue`, `break`, `return`
or `throw` was typed as Unit instead of Never, so `let m = match o { Some(x) => x,
None => { continue } }` gave `m` the type Dyn and every later use lost precision
(false `S.MATCH.NON_EXHAUSTIVE` "open type" warnings on `m.get(k)` matches)."""
from tests.helpers import check


def test_diverging_arm_does_not_erase_the_type():
    r = check("""
error Bad { }
fn f(xs: List[Map[Str, Int]?]) -> Int throws Bad {
    let total = 0
    for x in xs {
        let m = match x {
            Some(v) => v
            None => {
                continue
            }
        }
        let n = match m.get("k") { Some(k) => k, None => 0 }
        total = total + n
    }
    let first = match xs.first() { Some(Some(v)) => v, _ => { throw Bad() } }
    return total + first.length
}""", "verified")
    assert r.check == [], r.text()
