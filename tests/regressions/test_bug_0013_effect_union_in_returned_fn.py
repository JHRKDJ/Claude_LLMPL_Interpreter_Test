"""BUG-0013 (found by the V3 coverage reread, 7.7.5 `compose` example): error-set
variables were not substituted into a *returned* function type, so
`compose(parse, half)` had type `fn(Str) -> Int` with no effect: `try f(s)` was a
false W.EFFECT.USELESS_TRY, and a function declaring `throws Bad` while calling the
composed function (which may throw `Worse`) was not reported in verified mode."""
from tests.helpers import check, run

PRELUDE = """
error Bad { }
error Worse { }
fn compose[A, B, C, E1, E2](first: fn(A) -> B throws E1, second: fn(B) -> C throws E2) -> fn(A) -> C throws E1 | E2 {
    return fn(a: A) -> C throws E1 | E2 { return try second(try first(a)) }
}
fn parse(s: Str) -> Int throws Bad {
    return match s.toInt() { Some(n) => n, None => { throw Bad() } }
}
fn half(n: Int) -> Int throws Worse {
    if n % 2 != 0 { throw Worse() }
    return n.div(2)
}
fn double(n: Int) -> Int { return n * 2 }
"""


def test_union_effect_is_instantiated_and_complete_declaration_is_clean():
    r = check(PRELUDE + """
pub fn run(s: Str) -> Int throws Bad, Worse {
    let f = compose(parse, half)
    return try f(s)
}""", "verified")
    assert r.check == [], r.text()


def test_missing_member_of_union_is_reported():
    r = check(PRELUDE + """
pub fn wrong(s: Str) -> Int throws Bad {
    let f = compose(parse, half)
    return try f(s)
}""", "verified")
    assert "S.EFFECT.UNDECLARED_THROWS" in r.check_errors, r.text()


def test_partially_effect_free_composition():
    r = check(PRELUDE + """
pub fn partial(s: Str) -> Int throws Bad {
    let h = compose(parse, double)
    return try h(s)
}
pub fn pure(n: Int) -> Int {
    let g = compose(double, double)
    return g(n)
}""", "verified")
    assert r.check == [], r.text()


def test_runtime_behaviour():
    r = run(PRELUDE + """
fn main() {
    let f = compose(parse, half)
    print(try f("8") catch Bad => -1 catch Worse => -2)
    print(try f("7") catch Bad => -1 catch Worse => -2)
    print(try f("x") catch Bad => -1 catch Worse => -2)
}""")
    assert r.lines == ["4", "-2", "-1"]
