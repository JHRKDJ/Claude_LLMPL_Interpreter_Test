"""BUG-0045 (second audit, T14; LocalFlow review D4): Python numeric/text conventions
leaked as language defaults (V3 2.7): `round()` was floor(x + 0.5) (so
0.49999999999999994 → 1 and -2.5 → -2) while `roundTo`/format precision used banker's
rounding (2.5 → 2); floats displayed as `1e-05`/`1e+16`; `{5:07}` silently ignored the
zero flag; `toInt`/`toFloat` accepted surrounding whitespace and a leading `+` (Python
`int()`/`float()`), and NaN conversion messages showed Python's `nan`.
Policy (SPEC-010): rounding is half away from zero everywhere, on the exact binary value;
exponents display as `1e-5`/`1e16`; `0` in a width zero-pads numbers; numeric parsing
accepts exactly `-?digits` (Int) and `-?digits[.digits][e[-+]digits]` (Float)."""
from tests.helpers import run


def test_rounding_is_half_away_from_zero_everywhere():
    r = run('fn main() { print(2.5.round(), 3.5.round(), (-2.5).round(), 0.49999999999999994.round(), '
            '2.5.roundTo(0), 0.125.roundTo(2), "{2.5:.0}", "{0.125:.2}", "{-0.125:.2}") }')
    assert r.lines == ["3 4 -3 0 3.0 0.13 3 0.13 -0.13"], r.text()


def test_float_display_and_zero_padding():
    r = run('fn main() { print(1e-5, 1e16, 1.5e300, 0.1, 100.0, "{5:07}", "{-5:07}", "{2.5:08.2}", "{5:>7}") }')
    assert r.lines == ["1e-5 1e16 1.5e300 0.1 100.0 0000005 -000005 00002.50       5"], r.text()


def test_strict_numeric_parsing():
    r = run('fn main() { print(" 12 ".toInt(), "+5".toInt(), "1_000".toInt(), "-7".toInt(), "007".toInt())\n'
            ' print(" 1.5".toFloat(), "nan".toFloat(), "inf".toFloat(), "1e3".toFloat(), "-2.5".toFloat(), "1.".toFloat()) }')
    assert r.lines == ["None None None Some(-7) Some(7)", "None None None Some(1000.0) Some(-2.5) None"], r.text()


def test_nan_conversion_message_uses_language_display():
    r = run("import std.math\nfn main() { print(math.nan.toInt()) }")
    assert r.codes == ["A.NUMERIC.INVALID_CONVERSION"] and "NaN" in r.diag.message and "nan" not in r.diag.message
