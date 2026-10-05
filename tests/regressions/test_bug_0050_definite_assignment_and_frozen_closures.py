"""BUG-0050 (second audit, T20).

1. Definite assignment ignored `break`: after `while true { z = 5; break }` the only way
   out of the loop has assigned `z`, yet verified mode reported S.NAME.UNINITIALISED
   (a false positive that forces dead initialisers, V3 5.4).
2. A closure that captures mutable state is not frozen (V3 5.1.3), and the runtime
   abandons when one is stored in a frozen list, map or record; the checker already
   knows such closures (TFn.unsendable) but accepted them there in verified mode.
"""
from tests.helpers import check, run

LOOP = """
fn f(n: Int) -> Int {
    let z: Int
    while true {
        if n > 3 {
            z = n
            break
        }
        z = 0
        break
    }
    return z
}

fn main() {
    print(f(5))
}
"""


def test_assignment_before_every_break_of_a_forever_loop_is_definite():
    r = check(LOOP, "verified")
    assert "S.NAME.UNINITIALISED" not in r.check_codes, r.text()
    assert run(LOOP).stdout == "5\n"


def test_a_break_path_without_assignment_is_still_reported():
    src = LOOP.replace("        z = 0\n", "")
    r = check(src, "verified")
    assert "S.NAME.UNINITIALISED" in r.check_errors, r.text()


def test_conditional_loop_does_not_count_as_definite():
    src = "fn f(n: Int) -> Int {\n let z: Int\n while n > 0 {\n z = 1\n break\n }\n return z\n}"
    r = check(src, "verified")
    assert "S.NAME.UNINITIALISED" in r.check_errors, r.text()


MUT = "    let m = MutableList[Int].of(1)\n    let g = fn() -> Int => m.length\n"


def test_mutable_capturing_closure_in_frozen_list_is_static():
    src = "fn main() {\n" + MUT + "    let xs = [g]\n    print(xs.length)\n}\n"
    r = check(src, "verified")
    assert "S.TYPE.FROZEN_MUTATION" in r.check_errors, r.text()


def test_mutable_capturing_closure_in_frozen_map_and_record_is_static():
    src = ("record Holder {\n    f: fn() -> Int\n}\n\nfn main() {\n" + MUT +
           "    let h = Holder(f: g)\n    let mp = {\"k\": g}\n    print(mp.length)\n}\n")
    r = check(src, "verified")
    assert r.check_errors.count("S.TYPE.FROZEN_MUTATION") == 2, r.text()


def test_frozen_capturing_closure_in_frozen_list_is_accepted():
    src = "fn main() {\n    let k = 3\n    let g = fn() -> Int => k\n    let xs = [g]\n    print(xs[0]())\n}\n"
    r = check(src, "verified")
    assert "S.TYPE.FROZEN_MUTATION" not in r.check_codes, r.text()
    assert run(src).stdout == "3\n"
