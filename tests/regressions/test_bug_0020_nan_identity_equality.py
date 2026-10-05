"""BUG-0020 (second audit, T02): `lang_eq` short-circuited on Python object identity, so
a frozen value containing NaN was equal to itself but not to a structurally identical
copy — reference identity became observable for frozen values (V3 5.1.1). Under the
IEEE NaN policy (SPEC-010) both comparisons are false."""
from tests.helpers import run


def test_frozen_values_containing_nan_compare_structurally():
    r = run("""
record R { f: Float }
enum E { V(x: Float) }
fn main() { let n = 0.0 / 0.0
  let a = [n]
  let b = [n]
  print(a == a, a == b)
  let r1 = R(f: n)
  print(r1 == r1, r1 == R(f: n))
  let t = (n, 1)
  print(t == t, E.V(x: n) == E.V(x: n))
  print(n == n, [1.5] == [1.5]) }""")
    assert r.lines == ["false false", "false false", "false false", "false true"]
