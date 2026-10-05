"""BUG-0048 (second audit, T17): dynamic-type diagnostics fell short of V3 5.3.12/7.6.5:
same-named nominal types from different modules rendered as "expects User, received
User"; Option/Result values were described only as "Option"/"Result"; a failed `as`
narrowing to a function type said only "value is Function"; a nested mismatch found in
typed code did not point at the boundary where the value entered; built-in argument
names appeared as `arg0`."""
from tests.helpers import check, run


def test_same_named_types_are_qualified():
    r = run("import a\nfn want(u: User) -> Int { return 1 }\nrecord User { n: Int }\nfn id(x) { return x }\n"
            "fn main() { print(want(id(a.make()))) }",
            files={"a.lang": "pub record User { n: Int }\npub fn make() -> User { return User(n: 1) }\n"})
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    assert "a.User" in r.diag.message and "main.User" in r.diag.message, r.diag.message


def test_option_payload_described():
    r = run("fn id(x) { return x }\nfn want(o: Int?) -> Int { return 0 }\nfn main() { print(want(id(Some(\"s\")))) }")
    assert "Some(Str)" in r.diag.message, r.diag.message


def test_narrowing_failure_gives_the_reason():
    r = run("fn id(x) { return x }\nfn main() { let f = id(fn(a, b) => a) as fn(Int) -> Int\n print(1) }")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"] and "parameter" in r.diag.message, r.diag.message


def test_nested_mismatch_points_at_the_entry_boundary():
    r = run("""
fn id(x) { return x }
fn sum(xs: List[Int]) -> Int {
    let t = 0
    for x in xs { t = t + x }
    return t
}
fn main() { print(sum(id([1, "two"]))) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    labels = [l.message for l in r.diag.secondary]
    assert any("entered" in m for m in labels), labels


def test_builtin_argument_positions():
    r = check("fn f() -> List[Int] { return [3, 1].sortedBy(5) }", "verified")
    d = [x for x in r.check if x.stable_code == "S.TYPE.STATIC_MISMATCH"][0]
    assert "arg0" not in d.message and "argument 1" in d.message, d.message
