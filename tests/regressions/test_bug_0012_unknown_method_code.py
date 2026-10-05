"""BUG-0012 (found by the diagnostic-code coverage audit): a call to a missing method
on a dynamically typed value, `p.go()`, abandoned with `A.TYPE.UNKNOWN_FIELD`; the
code-selection expression in `unknown_member` could never yield `UNKNOWN_METHOD`.
A missing member used as a call callee is an unknown *method* (the static checker
already reports `S.TYPE.UNKNOWN_METHOD` for the same source)."""
from tests.helpers import run


def test_missing_method_call_on_dyn_record():
    r = run("record P { x: Int }\nfn main() { let p: Dyn = P(x: 1)\n print(p.go()) }")
    assert r.codes == ["A.TYPE.UNKNOWN_METHOD"]


def test_missing_method_call_on_builtin_value():
    r = run("fn main() { let s: Dyn = \"abc\"\n print(s.frobnicate()) }")
    assert r.codes == ["A.TYPE.UNKNOWN_METHOD"]


def test_missing_field_read_is_still_unknown_field():
    r = run("record P { x: Int }\nfn main() { let p: Dyn = P(x: 1)\n print(p.y) }")
    assert r.codes == ["A.TYPE.UNKNOWN_FIELD"]
