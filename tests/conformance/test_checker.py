"""Static checker conformance: every row of the obligation table in
docs/semantics/typing_and_effects.md §3, in draft and in verified mode.

Each case is a small program expected to produce exactly one *targeted* diagnostic
code; the table records its severity in draft and in verified mode (None = absent).
Other diagnostics may accompany it only where listed in `also`.
"""
import pytest

from tests.helpers import check

E, W = "error", "warning"

CASES = [
    # --- legality rules: errors in both modes ---------------------------------
    ("throws_and_result", """
error Bad { }
fn f() -> Result[Int, Bad] throws Bad { return Ok(1) }
""", "S.EFFECT.THROWS_AND_RESULT", E, E),
    ("broad_fallback_multi", """
error A1 { }
error B1 { }
fn f(x: Int) -> Int throws A1, B1 { if x > 0 { throw A1() }
 throw B1() }
fn g() -> Int { return try f(1) else 0 }
""", "S.EFFECT.BROAD_FALLBACK", E, E),
    ("not_an_error_thrown", """
record P { x: Int }
fn f() { throw P(x: 1) }
""", "S.EFFECT.NOT_AN_ERROR", E, E),
    ("not_an_error_caught", """
record P { x: Int }
error Bad { }
fn f() -> Int throws Bad { throw Bad() }
fn g() -> Int { return try f() catch P => 0 catch Bad => 1 }
""", "S.EFFECT.NOT_AN_ERROR", E, E),
    ("provider_outside_use", """
resource fn tok() yields Int { yield 1 }
fn f() { let t = tok() }
""", "S.RESOURCE.PROVIDER_OUTSIDE_USE", E, E),
    ("on_abandon_restricted", """
mutable record R { n: Int
 fn undo(self) { } }
resource fn p() yields R { let r = R(n: 1)
 onAbandon r.undo()
 yield r }
""", "S.RESOURCE.ON_ABANDON_RESTRICTED", E, E),
    ("yield_outside_provider", """
fn f() { yield 1 }
""", "S.RESOURCE.YIELD_OUTSIDE_PROVIDER", E, E),
    ("await_outside_async", """
async fn a() -> Int { return 1 }
fn f() -> Int { return await a() }
""", "S.ASYNC.AWAIT_OUTSIDE_ASYNC", E, E),
    ("sync_calls_async", """
async fn a() -> Int { return 1 }
fn f() -> Int { return a() }
""", "S.ASYNC.SYNC_CALLS_ASYNC", E, E),
    ("spawn_outside_group", """
async fn a() -> Int { return 1 }
async fn f() { let h = spawn a() }
""", "S.TASK.SPAWN_OUTSIDE_GROUP", E, E),
    ("handle_escape_assign", """
async fn a() -> Int { return 1 }
async fn f() {
    let keep: Task[Int, Int]? = null
    parallel { let h = spawn a()
     keep = Some(h)
     await h }
}
""", "S.TASK.HANDLE_ESCAPE", E, E),
    ("handle_escape_value", """
async fn a() -> Int { return 1 }
async fn f() { let h = parallel { spawn a() } }
""", "S.TASK.HANDLE_ESCAPE", E, E),
    ("handle_escape_return", """
async fn a() -> Int { return 1 }
async fn f() { parallel { let h = spawn a()
 return h } }
""", "S.TASK.HANDLE_ESCAPE", E, E),
    ("select_now_requires_none_ready", """
async fn f(rx: ReceivePort[Int]) -> Int { return select now { receive x from rx => x } }
""", "S.SELECT.NONE_READY_PLACEMENT", E, E),
    ("select_impure_setup", """
fn mk() -> Int { return 1 }
async fn f(tx: SendPort[Int]) { select { send mk() to tx => () } }
""", "S.SELECT.IMPURE_SETUP", E, E),
    ("select_guard_not_bool", """
async fn f(rx: ReceivePort[Int]) -> Int { let g = 1
 return select { when g: receive x from rx => x } }
""", "S.SELECT.INVALID_GUARD", E, E),
    ("frozen_field_type", """
record Box { items: MutableList[Int] }
""", "S.TYPE.FROZEN_FIELD_TYPE", E, E),
    ("invariant_field_write", """
mutable record Acct { balance: Int
 invariant balance >= 0 }
fn f(a: Acct) { a.balance = 5 }
""", "S.CONTRACT.INVARIANT_FIELD_WRITE", E, E),
    ("contract_restricted_io", """
fn f(x: Int) -> Int requires print("x") == () { return x }
""", "S.CONTRACT.RESTRICTED", E, E),
    ("contract_restricted_index", """
fn f(xs: List[Int]) -> Int requires xs[0] > 0 { return 1 }
""", "S.CONTRACT.RESTRICTED", E, E),
    ("recursive_predicate", """
predicate even(n: Int) { n == 0 || odd(n - 1) }
predicate odd(n: Int) { n != 0 && even(n - 1) }
""", "S.CONTRACT.RECURSIVE_PREDICATE", E, E),
    ("old_not_snapshottable", """
fn f(xs: MutableList[Int]) ensures old(xs).length < xs.length { xs.push(1) }
""", "S.CONTRACT.OLD_NOT_SNAPSHOTTABLE", E, E),
    ("protocol_not_satisfied", """
protocol Named { fn name(self) -> Str }
record Rock satisfies Named { w: Int }
""", "S.PROTOCOL.NOT_SATISFIED", E, E),
    ("protocol_added_precondition", """
protocol Store { fn put(self, x: Int) }
mutable record S satisfies Store { n: Int
 fn put(self, x: Int) requires x > 0 { self.n = x } }
""", "S.PROTOCOL.ADDED_PRECONDITION", E, E),
    ("generic_arity", """
fn f(xs: List[Int, Int]) { }
""", "S.TYPE.GENERIC_ARITY", E, E),
    # --- verified obligations: warnings in draft, errors in verified ------------
    ("missing_try", """
error Bad { }
fn f() -> Int throws Bad { throw Bad() }
fn g() -> Int throws Bad { return f() }
""", "S.EFFECT.MISSING_TRY", W, E),
    ("undeclared_throws", """
error Bad { }
fn f() -> Int throws Bad { throw Bad() }
fn g() -> Int { return try f() }
""", "S.EFFECT.UNDECLARED_THROWS", W, E),
    ("static_mismatch_arg", """
fn f(x: Int) -> Int { return x }
fn g() -> Int { return f("s") }
""", "S.TYPE.STATIC_MISMATCH", W, E),
    ("static_mismatch_return", """
fn f() -> Int { return "s" }
""", "S.TYPE.STATIC_MISMATCH", W, E),
    ("unknown_field", """
record P { x: Int }
fn f(p: P) -> Int { return p.y }
""", "S.TYPE.UNKNOWN_FIELD", W, E),
    ("unknown_method", """
record P { x: Int }
fn f(p: P) -> Int { return p.size() }
""", "S.TYPE.UNKNOWN_METHOD", W, E),
    ("arity", """
fn f(x: Int) -> Int { return x }
fn g() -> Int { return f(1, 2) }
""", "S.TYPE.ARITY", W, E),
    ("invalid_operator", """
fn f() -> Int { return 1 + "a" }
""", "S.TYPE.INVALID_OPERATOR", W, E),
    ("frozen_mutation", """
record P { x: Int }
fn f(p: P) { p.x = 2 }
""", "S.TYPE.FROZEN_MUTATION", W, E),
    ("non_exhaustive_enum", """
enum Color { Red, Green, Blue }
fn f(c: Color) -> Int { return match c { Color.Red => 1, Color.Green => 2 } }
""", "S.MATCH.NON_EXHAUSTIVE", W, E),
    ("non_exhaustive_option", """
fn f(x: Int?) -> Int { return match x { Some(v) => v } }
""", "S.MATCH.NON_EXHAUSTIVE", W, E),
    ("non_exhaustive_open_type", """
fn f(x: Int) -> Int { return match x { 1 => 10, 2 => 20 } }
""", "S.MATCH.NON_EXHAUSTIVE", W, E),
    ("missing_await", """
async fn a() -> Int { return 1 }
async fn f() -> Int { return a() }
""", "S.ASYNC.MISSING_AWAIT", W, E),
    ("await_non_async", """
fn a() -> Int { return 1 }
async fn f() -> Int { return await a() }
""", "S.ASYNC.AWAIT_NON_ASYNC", W, E),
    ("resource_escape_let", """
resource fn tok() yields Int { yield 1 }
fn f() { use t = tok() { let alias = t } }
""", "S.RESOURCE.ESCAPE", W, E),
    ("borrow_param", """
resource fn tok() yields Int { yield 1 }
fn g(n: Int) -> Int { return n }
fn f() -> Int { return use t = tok() { g(t) } }
""", "S.RESOURCE.BORROW_PARAM", W, E),
    ("yield_count", """
resource fn twice() yields Int { yield 1
 yield 2 }
""", "S.RESOURCE.YIELD_COUNT", W, E),
    ("not_sendable_controller", """
async fn w(c: Channel[Int]) { }
async fn f() { let ch = Channel[Int].unbounded()
 parallel { spawn w(ch) } }
""", "S.TASK.NOT_SENDABLE", W, E),
    ("capture_mutable", """
async fn f() { let xs = MutableList[Int]()
 parallel { let h = spawn { xs.push(1) }
  await h } }
""", "S.TASK.CAPTURE_MUTABLE", W, E),
    ("uninitialised", """
fn f(c: Bool) -> Int { let x: Int
 if c { x = 1 }
 return x }
""", "S.NAME.UNINITIALISED", W, E),
    # --- verified-only obligations ----------------------------------------------
    ("missing_annotation_param", """
pub fn f(x) -> Int { return 1 }
""", "S.TYPE.MISSING_ANNOTATION", None, E),
    ("missing_annotation_return", """
pub fn f(x: Int) { return x }
""", "S.TYPE.MISSING_ANNOTATION", None, E),
    ("dynamic_call", """
fn f(g) -> Int { return g(1) }
""", "S.TYPE.DYNAMIC_CALL", None, E),
    # --- advisories: warnings in both modes ---------------------------------------
    ("catch_unreachable", """
error Bad { }
error Other { }
fn f() -> Int throws Bad { throw Bad() }
fn g() -> Int throws Bad { return try f() catch Other => 0 }
""", "S.EFFECT.CATCH_UNREACHABLE", W, W),
    ("useless_try", """
fn f() -> Int { return try 1 + 2 }
""", "W.EFFECT.USELESS_TRY", W, W),
    ("unreachable_arm", """
fn f(x: Int?) -> Int { return match x { _ => 0, Some(v) => v } }
""", "S.MATCH.UNREACHABLE_ARM", W, W),
    ("identity_equality", """
mutable record C { n: Int }
fn f(a: C, b: C) -> Bool { return a == b }
""", "W.TYPE.IDENTITY_EQUALITY", W, W),
    ("select_deadline_reset", """
async fn f(rx: ReceivePort[Int]) throws ChannelClosed { while true {
  select { receive x from rx => print(x)
   after 1.seconds => { break } } } }
""", "W.SELECT.DEADLINE_RESET", W, W),
    ("select_starvation", """
async fn f(a: ReceivePort[Int], b: ReceivePort[Int]) throws ChannelClosed { for i in 0..3 {
  select priority { receive x from a => print(x)
   receive y from b => print(y) } } }
""", "W.SELECT.STARVATION", W, W),
    ("select_closed_loop", """
async fn f(a: ReceivePort[Int]) { for i in 0..3 {
  select { receive x from a => print(x)
   closed a => print("closed") } } }
""", "W.SELECT.CLOSED_LOOP", W, W),
    ("select_busy_poll", """
async fn f(a: ReceivePort[Int]) { let n = 0
 while n < 10 {
  select now { receive x from a => print(x)
   closed a => print("c")
   none ready => () }
  n = n + 1 } }
""", "W.SELECT.BUSY_POLL", W, W),
    # V3 7.10.2: "verified analysis reports regions where no reachable cancellation
    # point is identifiable" -- every loop in verified; an unconditional loop always.
    ("no_cancellation_point_bounded", """
async fn f() { let i = 0
 while i < 1000000 { i = i + 1 } }
""", "W.CANCEL.NO_CANCELLATION_POINT", None, W),
    ("no_cancellation_point_for", """
async fn f() { let s = 0
 for i in 0..1000000 { s = s + i } }
""", "W.CANCEL.NO_CANCELLATION_POINT", None, W),
    ("no_cancellation_point_forever", """
async fn f() { let i = 0
 while true { i = i + 1 } }
""", "W.CANCEL.NO_CANCELLATION_POINT", W, W),
    ("large_mutable_record", """
mutable record Bag { a: Int
 b: Int
 c: Int
 d: Int
 e: Int
 f: Int
 g: Int
 h: Int
 i: Int
 j: Int
 k: Int
 l: Int
 m: Int }
""", "W.STATE.LARGE_MUTABLE_RECORD", W, W),
    ("pass_through", """
mutable record Db { rows: MutableList[Int] }
fn store(db: Db, x: Int) { db.rows.push(x) }
fn handler(db: Db, x: Int) { store(db, x) }
""", "W.STATE.PASS_THROUGH", W, W),
    ("invariant_across_await", """
mutable record Account { balance: Int
 pending: Bool
 invariant balance >= 0
 async fn withdraw(self, amount: Int) {
    self.balance = self.balance - amount
    await sleep(1.millis)
    self.pending = false } }
""", "W.INVARIANT.ACROSS_AWAIT", W, W),
]


def _sev(r, code):
    sevs = {d.severity for d in r.check if d.stable_code == code}
    if not sevs:
        return None
    return E if E in sevs else W


@pytest.mark.parametrize("name,src,code,draft,verified", CASES, ids=[c[0] for c in CASES])
def test_obligation_policy(name, src, code, draft, verified):
    rd = check(src, "draft")
    rv = check(src, "verified")
    assert _sev(rd, code) == draft, rd.text()
    assert _sev(rv, code) == verified, rv.text()


CLEAN = [
    ("handled_errors", """
error Bad { }
fn f(x: Int) -> Int throws Bad { if x < 0 { throw Bad() }
 return x }
pub fn g(x: Int) -> Int { return try f(x) catch Bad => 0 }
"""),
    ("typed_fallback_single_type", """
error Bad { }
fn f() -> Int throws Bad { throw Bad() }
pub fn g() -> Int { return try f() else 0 }
"""),
    ("propagation_declared", """
error Bad { }
fn f() -> Int throws Bad { throw Bad() }
pub fn g() -> Int throws Bad { return try f() }
"""),
    ("exhaustive_enum", """
enum Color { Red, Green, Blue }
pub fn f(c: Color) -> Int { return match c { Color.Red => 1, Color.Green => 2, Color.Blue => 3 } }
"""),
    ("exhaustive_result_nested", """
error Bad { }
pub fn f(r: Result[Int?, Bad]) -> Int { return match r { Ok(Some(v)) => v, Ok(None) => 0, Err(_) => -1 } }
"""),
    ("exhaustive_tuple_bools", """
pub fn f(a: Bool, b: Bool) -> Int { return match (a, b) { (true, true) => 3, (true, false) => 2,
  (false, _) => 0 } }
"""),
    ("catch_every_case_of_error_enum", """
error enum Lex { Eof, BadChar(c: Str) }
fn lex(n: Int) -> Str throws Lex { if n == 0 { throw Lex.Eof }
 throw Lex.BadChar(c: "%") }
pub fn f() -> Str { return try lex(0) catch Lex.Eof => "eof" catch Lex.BadChar as e => "bad" }
"""),
    ("effect_variable_forwarding", """
error Bad { }
fn apply[E](f: fn(Int) -> Int throws E, x: Int) -> Int throws E { return try f(x) }
fn risky(x: Int) -> Int throws Bad { throw Bad() }
fn safe(x: Int) -> Int { return x + 1 }
pub fn g() -> Int { return apply(safe, 1) }
pub fn h() -> Int throws Bad { return try apply(risky, 1) }
"""),
    ("structured_tasks", """
async fn work(n: Int) -> Int { await sleep(n.millis)
 return n }
pub async fn main() -> Int { return parallel { let a = spawn work(1)
 let b = spawn work(2)
 (await a) + (await b) } }
"""),
    ("collect_mode_no_aggregate", """
error Bad { }
async fn bad() -> Int throws Bad { throw Bad() }
pub async fn main() -> Int { let rep = parallel collect { spawn bad() }
 return 0 }
"""),
    ("resources_and_borrows", """
resource fn tok() yields Int { yield 1 }
fn g(n: borrow Int) -> Int { return n + 1 }
pub fn f() -> Int { return use t = tok() { g(t) } }
"""),
    ("contracts", """
predicate positive(x: Int) { x > 0 }
pub fn f(x: Int) -> Int requires positive(x) ensures result > x { return x + 1 }
pub fn g(xs: List[Int]) -> Int requires xs.length > 0 ensures result == old(xs.length) { return xs.length }
"""),
    ("cpu_loop_with_cancel_check", """
pub async fn f() -> Int { let s = 0
 for i in 0..1000 { s = s + i
  cancel.check() }
 return s }
"""),
    ("select_with_deadline_outside_loop", """
pub async fn f(rx: ReceivePort[Int]) -> Int throws ChannelClosed {
    let deadline = time.now() + 5.seconds
    return select { receive x from rx => x
     at deadline => 0 }
}
"""),
    ("select_closed_branch_handles_closure", """
pub async fn f(rx: ReceivePort[Int]) -> Int {
    return select { receive x from rx => x
     closed rx => -1 }
}
"""),
]


@pytest.mark.parametrize("name,src", CLEAN, ids=[c[0] for c in CLEAN])
def test_well_formed_programs_are_clean_in_verified_mode(name, src):
    r = check(src, "verified")
    assert r.check == [], r.text()
