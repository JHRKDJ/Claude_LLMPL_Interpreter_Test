"""BUG-0019 (second audit, T01): arbitrary-precision Int broke at Python's 4300-digit
string-conversion limit (ValueError leaked as H.RUNTIME.INTERNAL_ERROR, exit 4, also
while *rendering* an unrelated abandonment's locals); `Int / Int` overflowing Float and
oversized format widths/precisions leaked OverflowError/ValueError the same way.
V3 6.2/7.3.3 (arbitrary precision), 2.7 (no Python leaks), 7.13.4 (safe rendering)."""
from tests.helpers import run


def test_big_ints_print_and_parse():
    r = run('fn main() { let x = 10.pow(5000)\n print(x.toStr().length)\n print("1".repeat(5000).toInt().unwrap() % 7) }')
    assert r.exit_code == 0, r.text()
    assert r.lines == ["5001", str(int("1" * 5000) % 7)]


def test_abandonment_with_big_local_still_renders():
    r = run("fn main() { let x = 10.pow(5000)\n assert false }")
    assert r.codes == ["A.ASSERT.FAILED"] and r.exit_code == 3
    from lang.diagnostics.render_text import render_all
    assert "…" in render_all(r.diags) or "digits" in render_all(r.diags)


def test_int_division_overflowing_float_abandons():
    r = run("fn main() { print(10.pow(400) / 3) }")
    assert r.codes == ["A.NUMERIC.INVALID_CONVERSION"], r.text()


def test_oversized_format_spec_abandons():
    for spec in ("{1:>99999999999999999999}", "{1.5:.99999999999}"):
        r = run('fn main() { print("' + spec + '") }')
        assert r.exit_code == 3 and r.codes and r.codes[0].startswith("A."), (spec, r.text())
