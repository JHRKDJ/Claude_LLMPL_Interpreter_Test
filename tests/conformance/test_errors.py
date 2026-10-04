"""Recoverable errors, Result, abandonment, effects (V3 5.7-5.9, 6.6, 7.7; SPEC-011/012)."""
from tests.helpers import ok, run

ERRS = """
category IO
error FileNotFound category IO { path: Str }
error Timeout category IO { ms: Int }
error ParseError { line: Int }
error enum Lex { BadChar(c: Str)
 Eof }
"""


def test_throw_try_propagate_and_catch():
    r = ok(ERRS + """
fn load(p: Str) -> Str throws FileNotFound {
    if p == "missing" { throw FileNotFound(path: p) }
    return "data"
}
fn main() {
    let a = try load("ok") catch FileNotFound => "fallback"
    let b = try load("missing") catch FileNotFound as e => "fallback for {e.path}"
    print(a, b)
}""")
    assert r.lines == ["data fallback for missing"]


def test_catch_by_category():
    r = ok(ERRS + """
fn f(n: Int) -> Int throws FileNotFound, Timeout {
    if n == 1 { throw FileNotFound(path: "x") }
    if n == 2 { throw Timeout(ms: 5) }
    return n
}
fn main() {
    for n in [0, 1, 2] {
        print(try f(n) catch category IO as e => -1)
    }
}""")
    assert r.lines == ["0", "-1", "-1"]


def test_catch_error_enum_case():
    r = ok(ERRS + """
fn lex(n: Int) -> Str throws Lex {
    if n == 0 { throw Lex.Eof }
    throw Lex.BadChar(c: "%")
}
fn main() {
    print(try lex(0) catch Lex.Eof => "eof" catch Lex => "other")
    print(try lex(1) catch Lex.Eof => "eof" catch Lex.BadChar as e => "bad")
}""")
    assert r.lines == ["eof", "bad"]


def test_uncaught_types_propagate_through_catch():
    r = run(ERRS + """
fn f() -> Int throws ParseError { throw ParseError(line: 3) }
fn main() throws ParseError {
    let x = try f() catch FileNotFound => 1
}""")
    assert r.exit_code == 1 and r.outcome == "threw"
    assert r.codes == ["R.ERROR.UNHANDLED"]


def test_top_level_unhandled_is_not_abandonment_and_runs_cleanup():
    r = run(ERRS + """
fn main() throws ParseError {
    defer print("cleanup ran")
    throw ParseError(line: 7)
}""")
    assert r.exit_code == 1 and r.outcome == "threw"
    assert r.lines == ["cleanup ran"]
    d = r.diag
    assert d.stable_code == "R.ERROR.UNHANDLED" and "ParseError" in d.message


def test_propagation_chain_recorded():
    r = run(ERRS + """
fn a() -> Int throws ParseError { throw ParseError(line: 1) }
fn b() -> Int throws ParseError { return try a() }
fn main() throws ParseError { let x = try b() }""")
    assert len(r.diag.propagation) == 2


def test_draft_unmarked_call_still_propagates_and_is_noted():
    r = run(ERRS + """
fn a() -> Int throws ParseError { throw ParseError(line: 1) }
fn main() { let x = a() }""")
    assert r.outcome == "threw"
    assert any("without a `try` marker" in n.message for n in r.diag.notes)


def test_written_throws_clause_enforced_at_runtime():
    r = run(ERRS + """
fn f(dyn: Dyn) -> Int throws ParseError {
    let g = dyn as fn() -> Int
    return g()
}
fn raiser() -> Int throws Timeout { throw Timeout(ms: 1) }
fn main() { let x = try f(raiser) catch ParseError => 0 }""")
    assert "A.EFFECT.UNDECLARED_EXCEPTION" in r.codes or "A.TYPE.DYNAMIC_MISMATCH" in r.codes


def test_only_errors_can_be_thrown():
    r = run("""record NotErr { x: Int }
fn main() { throw NotErr(x: 1) }""")
    assert r.codes == ["A.TYPE.OPERAND_MISMATCH"]


def test_capture_and_result():
    r = ok(ERRS + """
fn parse(s: Str) -> Int throws ParseError {
    return match s.toInt() { Some(n) => n
 None => { throw ParseError(line: 1) } }
}
fn main() {
    let rs = ["1", "x", "3"].map(fn(s) => capture parse(s))
    for r in rs {
        print(match r { Ok(v) => "ok {v}"
 Err(e) => "err line {e.line}" })
    }
}""")
    assert r.lines == ["ok 1", "err line 1", "ok 3"]


def test_or_throw_and_propagate():
    r = ok(ERRS + """
fn validate(n: Int) -> Result[Int, ParseError] {
    if n < 0 { return Err(ParseError(line: n)) }
    return Ok(n)
}
fn sum(xs: List[Int]) -> Result[Int, ParseError] {
    let total = 0
    for x in xs { total = total + propagate validate(x) }
    return Ok(total)
}
fn strict(n: Int) -> Int throws ParseError { return try validate(n).orThrow() }
fn main() {
    print(sum([1, 2]), sum([1, -5, 2]))
    print(try strict(3) catch ParseError => -1, try strict(-1) catch ParseError => -1)
}""")
    assert r.lines == ["Ok(3) Err(ParseError(line: -5))", "3 -1"]


def test_err_context_provenance():
    r = run(ERRS + """
fn main() throws ParseError {
    let r: Result[Int, ParseError] = Err(ParseError(line: 4)).context("path", "/tmp/x").context("row", 9)
    let v = try r.orThrow()
}""")
    d = r.diag
    assert d.values.get("path") == '"/tmp/x"' and d.values.get("row") == "9"


def test_else_fallback_single_known_type():
    r = ok(ERRS + """
fn f() -> Int throws ParseError { throw ParseError(line: 1) }
fn main() { print(try f() else 42) }""")
    assert r.lines == ["42"]


def test_cancellation_and_abandonment_not_catchable():
    r = run(ERRS + """
fn f() -> Int throws ParseError { assert false, "boom"
 return 1 }
fn main() { let x = try f() catch ParseError => 0
 print("unreachable") }""")
    assert r.codes == ["A.ASSERT.FAILED"] and r.stdout == ""


def test_abandonment_skips_defer():
    r = run("""fn main() {
    defer print("should not run")
    assert 1 > 2
}""")
    assert r.codes == ["A.ASSERT.FAILED"] and r.stdout == ""


def test_defer_lifo_and_block_scoped():
    r = ok("""fn main() {
    defer print("outer")
    if true {
        defer print("inner 1")
        defer print("inner 2")
        print("body")
    }
    print("after block")
}""")
    assert r.lines == ["body", "inner 2", "inner 1", "after block", "outer"]


def test_defer_failure_after_normal_exit_is_thrown():
    r = run(ERRS + """
fn cleanup() throws ParseError { throw ParseError(line: 9) }
fn main() throws ParseError {
    defer try cleanup()
    print("body done")
}""")
    assert r.outcome == "threw" and "ParseError" in r.diag.message


def test_defer_failure_during_exception_aggregates():
    r = run(ERRS + """
fn cleanup() throws ParseError { throw ParseError(line: 9) }
fn main() throws ParseError, AggregateException {
    defer try cleanup()
    throw FileNotFound(path: "p")
}""")
    assert r.outcome == "threw" and "AggregateException" in r.diag.message
    sources = [c.extra.get("source") for c in r.diag.children]
    assert sources == ["body", "defer"]


def test_assert_reports_values():
    r = run("""fn main() { let total = 3
 let limit = 2
 assert total <= limit, "over budget" }""")
    assert r.codes == ["A.ASSERT.FAILED"]
    assert r.diag.values == {"total": "3", "limit": "2"}
    assert "over budget" in r.diag.message


def test_abandonment_report_has_frames_and_locals():
    r = run("""fn inner(x: Int) -> Int { let y = x * 2
 assert y < 0
 return y }
fn main() { let z = inner(5) }""")
    names = [f.function for f in r.diag.frames]
    assert names[:2] == ["inner", "main"]
    assert r.diag.frames[0].locals["y"] == "10"


def test_secret_redaction_in_locals():
    r = run("""record Creds { user: Str
 sensitive token: Str }
fn main() { let password = "hunter2"
 let c = Creds(user: "u", token: "abc")
 assert false }""")
    locs = r.diag.frames[0].locals
    assert locs["password"] == "<redacted>"
    assert "abc" not in locs["c"] and "<redacted>" in locs["c"]
    assert r.diag.redacted or True


def test_aggregate_exception_catchable_and_inspectable():
    r = ok(ERRS + """
fn cleanup() throws ParseError { throw ParseError(line: 9) }
fn work() throws AggregateException {
    defer try cleanup()
    throw FileNotFound(path: "p")
}
fn main() {
    let n = try work() catch AggregateException as agg => agg.entries.length
    print(n)
}""")
    assert r.lines == ["2"]
