"""Cross-feature interactions TEST-INT-001..010 (RUN0 §J; V3 Part VIII)."""
from tests.helpers import check, ok, run

ERR = "error Bad { n: Int }\nerror Other { }\n"


# TEST-INT-001 typing x recoverable errors ------------------------------------------------
def test_int001_typed_catch_binding_and_return_annotation():
    r = ok(ERR + """
fn parse(s: Str) -> Int throws Bad { if s == "" { throw Bad(n: 0) }
 return s.length }
fn safe(s: Str) -> Int { return try parse(s) catch Bad as e => e.n - 1 }
fn main() { print(safe("abc"), safe("")) }""")
    assert r.lines == ["3 -1"]


def test_int001_handler_result_checked_against_return_annotation():
    # Known checker limitation: disagreeing branch types join to Dyn (no union types),
    # so this is not reported statically; the written return annotation still holds
    # at runtime (V3 5.3.8).
    r = run(ERR + """
fn parse(s: Str) -> Int throws Bad { throw Bad(n: 0) }
fn safe(s: Str) -> Int { return try parse(s) catch Bad => "zero" }
fn main() { print(safe("x")) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


def test_int001_capture_needs_parentheses_inside_operators():
    from lang.syntax.parser import parse_text
    r = parse_text("fn f() -> Result[Int, Bad] { return Ok(propagate capture g()) }")
    d = r.diagnostics[0]
    assert d.stable_code == "S.SYNTAX.MISPLACED_CONSTRUCT" and "(capture" in " ".join(d.help)


# TEST-INT-002 typing x Result -------------------------------------------------------------
def test_int002_capture_types_result_and_payload_checked():
    r = ok(ERR + """
fn parse(s: Str) -> Int throws Bad { if s == "" { throw Bad(n: 7) }
 return s.length }
fn both(a: Str, b: Str) -> Result[Int, Bad] {
    let x = propagate (capture parse(a))
    let y = propagate (capture parse(b))
    return Ok(x + y)
}
fn main() {
    print(both("ab", "c"))
    match both("ab", "") { Ok(v) => print(v), Err(e) => print("err", e.n) }
}""")
    assert r.lines == ["Ok(3)", "err 7"]


def test_int002_result_annotation_checked_at_return():
    r = run(ERR + """
fn mk() { return Ok("text") }
fn f() -> Result[Int, Bad] { return mk() }
fn main() { print(f()) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


# TEST-INT-003 draft/verified x type checking -------------------------------------------
def test_int003_static_mismatch_warns_in_draft_and_runtime_still_enforces():
    src = 'fn f(x: Int) -> Int { return x }\nfn main() { print(f("s")) }'
    d = run(src, "draft")
    assert "S.TYPE.STATIC_MISMATCH" in d.check_warnings and d.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    v = run(src, "verified")
    assert v.exit_code is None and "S.TYPE.STATIC_MISMATCH" in v.check_errors


# TEST-INT-004 draft/verified x effect obligations ---------------------------------------
def test_int004_unmarked_and_undeclared_effects():
    src = ERR + "fn f() -> Int throws Bad { throw Bad(n: 1) }\nfn g() -> Int { return f() }\nfn main() { print(g()) }"
    d = run(src, "draft")
    assert {"S.EFFECT.MISSING_TRY", "S.EFFECT.UNDECLARED_THROWS"} <= set(d.check_warnings)
    assert d.exit_code == 1  # propagates in draft
    v = run(src, "verified")
    assert {"S.EFFECT.MISSING_TRY", "S.EFFECT.UNDECLARED_THROWS"} <= set(v.check_errors)


def test_int004_written_throws_enforced_at_runtime_in_draft():
    r = run(ERR + """
fn dyn() { throw Other() }
fn f() -> Int throws Bad { dyn()
 return 1 }
fn main() { print(f()) }""", "draft")
    assert r.codes == ["A.EFFECT.UNDECLARED_EXCEPTION"]


# TEST-INT-005 variants x exhaustiveness ------------------------------------------------
def test_int005_nested_variants_exhaustiveness_witness():
    r = check(ERR + """
enum Shape { Circle(r: Float), Rect(w: Float, h: Float), Empty }
fn area(s: Shape?) -> Float { return match s {
    Some(Shape.Circle(r)) => r * r
    Some(Shape.Rect(w, h)) => w * h
    None => 0.0
} }""")
    d = next(d for d in r.check if d.stable_code == "S.MATCH.NON_EXHAUSTIVE")
    assert "Some(Shape.Empty)" in d.message


def test_int005_guards_do_not_count_and_runtime_backstop():
    src = """
enum Light { Red, Green }
fn go(l: Light, late: Bool) -> Bool { return match l { Light.Red if late => true, Light.Green => true } }
fn main() { print(go(Light.Green, false))
 print(go(Light.Red, false)) }"""
    r = run(src)
    assert "S.MATCH.NON_EXHAUSTIVE" in r.check_warnings
    assert r.lines == ["true"] and r.codes == ["A.MATCH.NO_ARM"]


# TEST-INT-006 dynamic x protocols x contracts (V3 8.1) ---------------------------------
PROTO = """
protocol Scorer {
    fn score(self, x: Int) -> Int
        ensures result >= 0
}
fn use_it(s: Scorer, x: Int) -> Int { return s.score(x) }
"""


def test_int006_missing_method_detected_at_boundary_before_use():
    r = run(PROTO + """
record Rock { w: Int }
fn mk() { return Rock(w: 1) }
fn main() { print("before")
 print(use_it(mk(), 1)) }""")
    assert r.lines == ["before"] and r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    assert "score" in r.diag.message


def test_int006_extra_throwing_effect_rejected():
    r = run(PROTO + ERR + """
record Risky { w: Int
 fn score(self, x: Int) -> Int throws Bad { throw Bad(n: x) } }
fn mk() { return Risky(w: 1) }
fn main() { print(use_it(mk(), 1)) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


def test_int006_inherited_postcondition_checked_at_runtime():
    r = run(PROTO + """
record Neg { w: Int
 fn score(self, x: Int) -> Int { return -x } }
fn mk() { return Neg(w: 1) }
fn main() { print(use_it(mk(), 1)) }""")
    assert r.codes == ["A.CONTRACT.POSTCONDITION_FAILED"]
    assert "Scorer" in r.diag.message


def test_int006_valid_frozen_implementation_runs():
    r = ok(PROTO + """
record Sq { w: Int
 fn score(self, x: Int) -> Int { return x * x } }
fn main() { let s = Sq(w: 0)
 print(use_it(s, 3) + use_it(s, 4)) }""")
    assert r.lines == ["25"]


# TEST-INT-007 protocols x structural conformance --------------------------------------
def test_int007_structural_without_declaration_and_added_precondition_nonconforming():
    r = ok("""
protocol Named { fn name(self) -> Str }
record Dog { n: Str
 fn name(self) -> Str { return self.n } }
fn greet(x: Named) -> Str { return "hi " + x.name() }
fn main() { print(greet(Dog(n: "rex"))) }""")
    assert r.lines == ["hi rex"]
    r = run("""
protocol Store { fn put(self, x: Int) -> Int }
record Picky { k: Int
 fn put(self, x: Int) -> Int requires x > 0 { return x } }
fn use_store(s: Store) -> Int { return s.put(1) }
fn mk() { return Picky(k: 0) }
fn main() { print(use_store(mk())) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"] and "precondition" in r.diag.message


# TEST-INT-008 mutable values x contracts ----------------------------------------------
def test_int008_old_of_primitive_projection_of_mutable_value():
    r = ok("""
fn add(xs: MutableList[Int], x: Int) ensures xs.length == old(xs.length) + 1 { xs.push(x) }
fn main() { let xs = MutableList[Int]()
 add(xs, 4)
 print(xs.length) }""")
    assert r.lines == ["1"]


def test_int008_postcondition_sees_post_state_of_mutable_argument():
    r = run("""
fn bad(xs: MutableList[Int]) ensures xs.length == old(xs.length) + 1 { xs.push(1)
 xs.push(2) }
fn main() { bad(MutableList[Int]()) }""")
    assert r.codes == ["A.CONTRACT.POSTCONDITION_FAILED"]


# TEST-INT-009 mutation x invariants x cancellation (V3 8.8) ---------------------------
ACCT = """
mutable record Account { balance: Int
 pending: Bool
 invariant balance >= 0
 async fn withdraw(self, amount: Int) {
    self.balance = self.balance - amount
    await sleep(1.seconds)
    self.balance = self.balance + amount
 }
}
"""


def test_int009_advisory_and_abandonment_supersedes_cancellation():
    r = run(ACCT + """
async fn main() {
    let a = Account(balance: 5, pending: false)
    let r = try within 10.millis { await a.withdraw(8)
     "done" } catch DeadlineExceeded => "timeout"
    print(r)
}""")
    assert "W.INVARIANT.ACROSS_AWAIT" in r.check_warnings
    assert r.codes == ["A.CONTRACT.INVARIANT_VIOLATED"]
    assert "cancelled" in r.diag.message


def test_int009_restored_invariant_lets_cancellation_proceed():
    r = run(ACCT + """
async fn main() {
    let a = Account(balance: 50, pending: false)
    let r = try within 10.millis { await a.withdraw(8)
     "done" } catch DeadlineExceeded => "timeout"
    print(r, a.balance)
}""")
    assert r.lines == ["timeout 42"]


# TEST-INT-010 resources x success/error/abandonment/cancellation ----------------------
RES = ERR + """
mutable record Log { lines: MutableList[Str] }
resource fn conn(log: Log, name: Str) yields Str {
    log.lines.push("open " + name)
    let exit = yield name
    log.lines.push("close " + name + " " + match exit { ScopeExit.Normal => "normal",
      ScopeExit.Failed => "failed", ScopeExit.Cancelled => "cancelled" })
}
"""


def test_int010_release_knows_exit_class():
    r = run(RES + """
fn work(log: Log) -> Int throws Bad { return use c = conn(log, "a") { throw Bad(n: 1) } }
async fn slow(log: Log) { use c = conn(log, "c") { await sleep(1.seconds) } }
async fn main() {
    let log = Log(lines: MutableList[Str]())
    let v = use c = conn(log, "ok") { c.length }
    let e = try work(log) catch Bad => -1
    let t = try within 5.millis { await slow(log)
     0 } catch DeadlineExceeded => -2
    print(v, e, t)
    for l in log.lines { print(l) }
}""")
    assert r.lines == ["2 -1 -2", "open ok", "close ok normal", "open a", "close a failed",
                       "open c", "close c cancelled"], r.text()


def test_int010_abandonment_skips_normal_release():
    r = run(RES + """
fn main() {
    let log = Log(lines: MutableList[Str]())
    defer { for l in log.lines { print(l) } }
    use c = conn(log, "x") { let xs = [1]
     print(xs[3]) }
}""")
    assert r.codes == ["A.INDEX.OUT_OF_RANGE"]
    assert r.lines == []  # neither provider continuation nor defer runs during abandonment
