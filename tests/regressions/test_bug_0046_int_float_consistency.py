"""BUG-0046 (second audit, T15): Int/Float mixing was inconsistent. `1 == 1.0` and
`[1, 2].contains(1.0)` abandon (no implicit numeric coercion, SPEC-010), but
`Set.of(1).contains(1.0)` returned false and `{1: "a"}.get(1.0)` returned None; and the
checker called nested Int/Float comparisons (`Some(1) == Some(1.0)`) "always false"
although they abandon."""
from tests.helpers import check, run


def test_set_and_map_lookups_with_the_other_numeric_kind_abandon():
    for expr in ("Set.of(1).contains(1.0)", '{1: "a"}.get(1.0)', '{1.0: "a"}.containsKey(1)',
                 "MutableSet.of(2.0).contains(2)"):
        r = run("fn main() { print(" + expr + ") }")
        assert r.codes == ["A.TYPE.OPERAND_MISMATCH"], (expr, r.codes, r.lines)


def test_genuinely_absent_keys_still_return_normally():
    r = run('fn main() { print(Set.of(1).contains(2), {1: "a"}.get(2), Set.of(1.5).contains(1.5)) }')
    assert r.lines == ["false None true"], r.text()


def test_checker_names_nested_int_float_comparisons_as_invalid():
    for src in ("Some(1) == Some(1.0)", "[1] == [1.0]", "(1, 2) == (1.0, 2)"):
        r = check("fn f() -> Bool { return " + src + " }", "verified")
        assert "S.TYPE.INVALID_OPERATOR" in r.check_codes and "S.TYPE.ALWAYS_FALSE_EQUALITY" not in r.check_codes, src
