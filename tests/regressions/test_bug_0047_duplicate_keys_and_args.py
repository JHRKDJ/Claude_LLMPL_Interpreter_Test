"""BUG-0047 (second audit, T14): `{"a": 1, "a": 2}` silently kept the last value
(Python dict-literal semantics) with no diagnostic, and `R(x: 1, x: 2)` passed verified
mode (abandoning only at run time). Both are near-certain mistakes; the language reports
them (V3 2.7: Python semantics must not become defaults by accident)."""
from tests.helpers import check, run


def test_duplicate_literal_map_key_is_a_static_error():
    r = check('fn f() -> Map[Str, Int] { return {"a": 1, "b": 2, "a": 3} }', "draft")
    assert "S.NAME.DUPLICATE" in r.check_errors, r.text()


def test_duplicate_runtime_key_in_a_literal_abandons():
    r = run('fn id(x) { return x }\nfn main() { print({id("k"): 1, id("k"): 2}) }')
    assert r.codes == ["A.MAP.DUPLICATE_KEY"], r.text()


def test_duplicate_named_argument_is_a_static_error():
    r = check("record R { x: Int }\nfn g(a: Int, b: Int) -> Int { return a }\n"
              "pub fn f() -> Int { let r = R(x: 1, x: 2)\n return g(a: 1, a: 2) }", "draft")
    assert r.check_errors.count("S.TYPE.ARITY") >= 2, r.text()
