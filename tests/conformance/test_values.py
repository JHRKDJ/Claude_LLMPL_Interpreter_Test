"""Values and data model (V3 5.1, 6.2, 7.3; SPEC-008/009/010)."""
from tests.helpers import ok, run


def test_int_arbitrary_precision():
    r = ok("""fn main() { print(2.pow(100)) }""")
    assert r.lines == [str(2 ** 100)]


def test_int_division_yields_float_and_div_floors():
    r = ok("""fn main() { print(7 / 2, 7.div(2), (-7).div(2), -7 % 3, 7 % -3) }""")
    assert r.lines == ["3.5 3 -4 2 -2"]


def test_no_mixed_numeric_arithmetic():
    r = run("""fn main() { let x = 1 + 2.0 }""")
    assert r.codes == ["A.TYPE.OPERAND_MISMATCH"]
    assert "toFloat" in r.text()


def test_int_float_equality_abandons():
    r = run("""fn main() { print(1 == 1.0) }""")
    assert r.codes == ["A.TYPE.OPERAND_MISMATCH"]


def test_cross_type_equality_is_false():
    r = ok("""fn main() { print(1 == "1", "a" == null, true == 1) }""")
    assert r.lines == ["false false false"]


def test_no_truthiness_in_conditions():
    r = run("""fn main() { if 1 { print("x") } }""")
    assert r.codes == ["A.TYPE.NON_BOOL_CONDITION"]
    r = run("""fn main() { let xs = [1]
 if xs { print("x") } }""")
    assert r.codes == ["A.TYPE.NON_BOOL_CONDITION"]


def test_boolean_operators_require_bools():
    r = run("""fn main() { print(true && 1) }""")
    assert r.codes == ["A.TYPE.OPERAND_MISMATCH"]
    r = ok("""fn main() { print(true && false, true || false, !true) }""")
    assert r.lines == ["false true false"]


def test_short_circuit():
    r = ok("""
fn boom() -> Bool { assert false
 return true }
fn main() { print(false && boom(), true || boom()) }""")
    assert r.lines == ["false true"]


def test_float_ieee_and_display():
    r = ok("""fn main() { print(1.0 / 0.0, -1.0 / 0.0, (0.0 / 0.0).isNaN(), 0.1 + 0.2, 2.0) }""")
    assert r.lines == ["Infinity -Infinity true 0.30000000000000004 2.0"]


def test_nan_map_key_abandons():
    r = run("""fn main() { let m = {0.0 / 0.0: 1} }""")
    assert r.codes == ["A.NUMERIC.NAN_KEY"]


def test_division_by_zero_int_abandons_checked_alternative():
    r = run("""fn main() { print(1.div(0)) }""")
    assert r.codes == ["A.NUMERIC.DIVISION_BY_ZERO"]
    r = ok("""fn main() { print(1.checkedDiv(0), 7.checkedDiv(2)) }""")
    assert r.lines == ["None Some(3)"]


def test_strings_interpolation_and_escapes():
    r = ok('''fn main() {
    let n = 3
    let pi = 3.14159
    print("n={n} next={n + 1} \\{literal\\} pi={pi:.2} [{n:>4}] [{"ab":<4}]")
}''')
    assert r.lines == ["n=3 next=4 {literal} pi=3.14 [   3] [ab  ]"]


def test_string_concat_requires_strings():
    r = run('''fn main() { let s = "a" + 1 }''')
    assert r.codes == ["A.TYPE.OPERAND_MISMATCH"]
    assert "interpolation" in r.text()


def test_string_code_points():
    r = ok('''fn main() { let s = "héllo"
 print(s.length, s[1], s.chars().length, s.slice(1, 3)) }''')
    assert r.lines == ["5 é 5 él"]


def test_negative_index_is_out_of_range():
    r = run("""fn main() { let xs = [1, 2, 3]
 print(xs[-1]) }""")
    assert r.codes == ["A.INDEX.OUT_OF_RANGE"]
    assert "negative" in r.text()


def test_checked_get():
    r = ok("""fn main() { let xs = [1, 2, 3]
 print(xs.get(5), xs.get(0)) }""")
    assert r.lines == ["None Some(1)"]


def test_frozen_list_persistent_updates():
    r = ok("""fn main() {
    let first = [1, 2, 3]
    let second = first.appended(4)
    print(first, second)
}""")
    assert r.lines == ["[1, 2, 3] [1, 2, 3, 4]"]


def test_frozen_collections_reject_mutation():
    r = run("""fn main() { let xs = [1, 2]
 xs[0] = 5 }""")
    assert r.codes == ["A.TYPE.FROZEN_MUTATION"]


def test_mutable_list_identity_and_aliasing():
    r = ok("""fn main() {
    let a = MutableList.of(1, 2)
    let b = a
    b.push(3)
    print(a, a == b, a == MutableList.of(1, 2, 3))
}""")
    assert r.lines == ["MutableList[1, 2, 3] true false"]


def test_freeze_snapshot_isolation():
    r = ok("""fn main() {
    let m = MutableList.of(1, 2)
    let f = m.freeze()
    m.push(3)
    let c = f.mutableCopy()
    c.push(9)
    print(f, m, c)
}""")
    assert r.lines == ["[1, 2] MutableList[1, 2, 3] MutableList[1, 2, 9]"]


def test_frozen_list_cannot_contain_mutable():
    r = run("""fn main() { let m = MutableList.of(1)
 let xs = [m] }""")
    assert r.codes == ["A.TYPE.FROZEN_MUTATION"]


def test_map_insertion_order_and_order_insensitive_equality():
    r = ok("""fn main() {
    let a = {"x": 1, "y": 2}
    let b = {"y": 2, "x": 1}
    print(a.keys(), b.keys(), a == b)
    let c = a.inserted("z", 3).removed("x")
    print(c, a)
}""")
    assert r.lines == ['["x", "y"] ["y", "x"] true', '{"y": 2, "z": 3} {"x": 1, "y": 2}']


def test_map_missing_key_abandons_get_checked():
    r = run("""fn main() { let m = {"a": 1}
 print(m["b"]) }""")
    assert r.codes == ["A.MAP.MISSING_KEY"]


def test_maps_not_directly_iterable():
    r = run("""fn main() { for k in {"a": 1} { print(k) } }""")
    assert r.codes == ["A.TYPE.NOT_ITERABLE"]
    r = ok("""fn main() { for (k, v) in {"a": 1, "b": 2}.entries() { print(k, v) } }""")
    assert r.lines == ["a 1", "b 2"]


def test_int_and_float_keys_are_distinct():
    r = ok("""fn main() { let m = MutableMap[Dyn, Int]()
 m[1] = 10
 m[1.0] = 20
 m[true] = 30
 print(m.length, m[1], m[1.0], m[true]) }""")
    assert r.lines == ["3 10 20 30"]


def test_mutable_keys_rejected():
    r = run("""fn main() { let s = MutableSet.of(MutableList.of(1)) }""")
    assert r.codes == ["A.TYPE.FROZEN_MUTATION"] or r.codes == ["A.TYPE.UNHASHABLE"]


def test_modification_during_iteration_abandons():
    r = run("""fn main() {
    let xs = MutableList.of(1, 2, 3)
    for x in xs { xs.push(x) }
}""")
    assert r.codes == ["A.COLLECTION.MODIFIED_DURING_ITERATION"]


def test_tuples_and_destructuring():
    r = ok("""fn main() {
    let t = (1, "a")
    let (n, s) = t
    print(t, t.0, t.1, n, s)
}""")
    assert r.lines == ['(1, "a") 1 a 1 a']


def test_ranges():
    r = ok("""fn main() { print((0..3).toList(), (1..=3).toList(), (0..10).contains(5)) }""")
    assert r.lines == ["[0, 1, 2] [1, 2, 3] true"]


def test_sorting_requires_comparable_same_types():
    r = ok("""fn main() { print([3, 1, 2].sorted(), ["b", "a"].sorted()) }""")
    assert r.lines == ['[1, 2, 3] ["a", "b"]']
    r = run("""fn main() { print([1, "a"].sorted()) }""")
    assert r.codes == ["A.TYPE.OPERAND_MISMATCH"]


def test_durations():
    r = ok("""fn main() { let d = 1500.millis
 print(d, 2.seconds + 250.millis, d.millis) }""")
    assert r.lines == ["1500ms 2250ms 1500"]
