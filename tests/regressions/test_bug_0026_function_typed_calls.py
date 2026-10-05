"""BUG-0026 (second audit, T06/T07): calling a value whose type comes from a written
function-type annotation checked nothing at run time: a wrong argument passed in draft,
a wrong result was used as the annotated type, and a narrowed callable
(`raw as fn(Int) -> Int throws E1`) could let E2 escape (V3 5.3.7: values are checked
when typed code "calls, returns"; 7.7.6: narrowing validates shape and effect)."""
from tests.helpers import run


def test_result_of_function_typed_parameter_checked():
    r = run("""
fn id(x) { return x }
fn apply(f: fn(Int) -> Int, n: Int) -> Str { let r = f(n)
  print("callback result used as Int:", r)
  return "done" }
fn main() { print(apply(id(fn(a) => "s"), 1)) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"], r.text()
    assert "callback result" not in r.stdout


def test_argument_to_function_typed_value_checked_in_draft():
    r = run("""
fn apply(f: fn(Int) -> Int) -> Int { return f("not an int") }
fn main() { print(apply(fn(x) => 3)) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"], r.text()


def test_narrowed_callable_effect_enforced():
    r = run("""
error E1 { }
error E2 { }
fn id(x) { return x }
fn thrower(n) { throw E2() }
fn main() { let t = id(thrower)
  let raw = id(fn(n) => t(n))
  let f = raw as fn(Int) -> Int throws E1
  let r = capture f(1)
  print("r =", r) }""")
    assert r.codes == ["A.EFFECT.UNDECLARED_EXCEPTION"], r.text()


def test_well_typed_callbacks_unaffected():
    r = run("""
error E1 { }
fn apply(f: fn(Int) -> Int throws E1, n: Int) -> Int throws E1 { return try f(n) }
fn main() { print(try apply(fn(x: Int) -> Int throws E1 { if x < 0 { throw E1() }
  return x * 2 }, 4) catch E1 => -1) }""")
    assert r.lines == ["8"], r.text()
