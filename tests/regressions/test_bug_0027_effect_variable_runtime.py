"""BUG-0027 (second audit, T08): a written `throws E` where E is an error-set variable
was treated as permissive at run time, so a generic higher-order function could let an
unrelated error escape (V3 5.3.2, 5.8.2, 7.7.5: written effects are enforced; E is bound
by the callback actually passed)."""
from tests.helpers import run

SRC = """
error Cb { }
error Other { }
fn mapAll[T, U, E](xs: List[T], f: fn(T) -> U throws E) -> List[U] throws E {
    if xs.length > 1 { throw Other() }
    return xs.map(fn(x) => try f(x))
}
fn ok(n: Int) -> Int throws Cb { if n < 0 { throw Cb() }
  return n }
"""


def test_error_outside_bound_effect_variable_abandons():
    r = run(SRC + "fn main() { print(capture mapAll([1, 2], ok)) }")
    assert r.codes == ["A.EFFECT.UNDECLARED_EXCEPTION"], r.text()


def test_callback_error_forwarded_through_effect_variable():
    r = run(SRC + "fn main() { print(capture mapAll([-1], ok)) }")
    assert r.lines == ["Err(Cb())"], r.text()


def test_effect_free_callback_binds_empty_set():
    r = run(SRC + "fn main() { print(capture mapAll([1, 2], fn(n) => n)) }")
    assert r.codes == ["A.EFFECT.UNDECLARED_EXCEPTION"], r.text()


def test_unknown_callback_effect_stays_permissive():
    # the callback invokes a Dyn value, so its effect is unknown: E cannot be bound
    r = run(SRC + "fn id(x) { return x }\nfn main() { let d = id(fn(n) => n)\n"
            "print(capture mapAll([1, 2], fn(n) => d(n))) }")
    assert r.lines == ["Err(Other())"], r.text()
