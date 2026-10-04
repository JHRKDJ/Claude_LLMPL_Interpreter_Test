"""Cross-feature interactions TEST-INT-021..030 (RUN0 §J; V3 Part VIII)."""
from tests.helpers import check, ok, run

ERR = "error Bad { n: Int }\n"


# TEST-INT-021 channels x graph copy x backpressure (V3 8.12) ------------------------
def test_int021_message_copied_at_commit_not_aliased():
    r = ok("""
mutable record Box { items: MutableList[Int] }
async fn main() {
    let ch = Channel[Box].buffered(2)
    let tx = ch.sender()
    let rx = ch.receiver()
    let b = Box(items: MutableList.of(1))
    try await tx.send(b) catch ChannelClosed => ()
    b.items.push(2)
    let got = try await rx.receive() catch ChannelClosed => Box(items: MutableList[Int]())
    print(got.items, b.items)
}""")
    assert r.lines == ["MutableList[1] MutableList[1, 2]"]


def test_int021_full_bounded_channel_blocks_sender_until_capacity():
    r = ok("""
async fn producer(tx: SendPort[Int]) throws ChannelClosed {
    for i in 0..3 { await tx.send(i)
     print("sent", i) }
}
async fn main() {
    let ch = Channel[Int].buffered(1)
    let rx = ch.receiver()
    parallel {
        spawn producer(ch.sender())
        await sleep(5.millis)
        print("draining")
        for i in 0..3 { let v = try await rx.receive() catch ChannelClosed => -1 }
    }
}""")
    assert r.lines[:2] == ["sent 0", "draining"]


def test_int021_large_copy_advisory():
    r = ok("""
async fn consume(xs: MutableList[Int]) -> Int { return xs.length }
async fn main() {
    let big = MutableList[Int]()
    for i in 0..20000 { big.push(i) }
    print(parallel { let h = spawn consume(big)
     await h })
}""")
    assert r.lines == ["20000"]
    assert "W.TASK.LARGE_COPY" in [w.stable_code for w in r.warnings]


# TEST-INT-022 closure x select loops x fairness diagnostics (V3 8.13, 8.14) ---------
def test_int022_closed_branch_in_loop_advisory_and_explicit_exit():
    src = """
async fn drain(rx: ReceivePort[Int]) -> Int {
    let total = 0
    while true {
        let done = select { receive x from rx => { total = total + x
          false }
         closed rx => true }
        if done { break }
    }
    return total
}
async fn main() {
    let ch = Channel[Int].unbounded()
    let tx = ch.sender()
    for i in 1..=3 { try await tx.send(i) catch ChannelClosed => () }
    ch.close()
    print(await drain(ch.receiver()))
}"""
    r = ok(src)
    assert r.lines == ["6"]
    assert "W.SELECT.CLOSED_LOOP" not in r.check_codes  # the closed branch changes the loop's exit


def test_int022_select_ring_buffer_bounded_and_attached_to_failure():
    r = run("""
async fn main() {
    let ch = Channel[Int].unbounded()
    let tx = ch.sender()
    let rx = ch.receiver()
    for i in 0..100 { try await tx.send(i) catch ChannelClosed => ()
     let v = try select { receive x from rx => x } catch ChannelClosed => -1 }
    let xs = [1]
    print(xs[5])
}""")
    assert r.codes == ["A.INDEX.OUT_OF_RANGE"]
    assert 0 < len(r.diag.select_events) <= 32


# TEST-INT-023 selection x task lifetimes (V3 8.15) ----------------------------------
def test_int023_task_branch_does_not_cancel_others_until_group_exit():
    r = ok("""
async fn fast() -> Int { await sleep(1.millis)
 return 1 }
async fn slow() -> Int { defer print("slow finished or cancelled")
 await sleep(50.millis)
 return 2 }
async fn main() {
    let first = parallel {
        let a = spawn fast()
        let b = spawn slow()
        let w = select { task a completed as r => "a" }
        let bv = await b
        "{w} then {bv}"
    }
    print(first)
    let raced = parallel race { spawn fast()
     spawn slow() }
    print(raced)
}""")
    assert r.lines == ["slow finished or cancelled", "a then 2", "slow finished or cancelled", "1"]


# TEST-INT-024 relative timeout x loops (V3 8.16) ------------------------------------
def test_int024_after_in_loop_warns_absolute_deadline_does_not():
    loop_after = """
async fn f(rx: ReceivePort[Int]) throws ChannelClosed {
    while true { select { receive x from rx => print(x)
      after 1.seconds => { break } } }
}"""
    assert "W.SELECT.DEADLINE_RESET" in check(loop_after, "verified").check_warnings
    loop_at = """
async fn f(rx: ReceivePort[Int]) throws ChannelClosed {
    let deadline = time.now() + 1.seconds
    while true { select { receive x from rx => print(x)
      at deadline => { break } } }
}"""
    assert "W.SELECT.DEADLINE_RESET" not in check(loop_at, "verified").check_codes


def test_int024_absolute_deadline_bounds_total_time():
    r = ok("""
async fn ticker(tx: SendPort[Int]) throws ChannelClosed { for i in 0..1000 { await sleep(4.millis)
 await tx.send(i) } }
async fn main() {
    let ch = Channel[Int].unbounded()
    let rx = ch.receiver()
    let start = time.now()
    let got = parallel race {
        spawn ticker(ch.sender())
        spawn collect(rx, start + 20.millis)
    }
    print(got)
}
async fn collect(rx: ReceivePort[Int], deadline: Instant) -> Int throws ChannelClosed {
    let n = 0
    while true { let more = select { receive x from rx => { n = n + 1
      true }
     at deadline => false }
     if !more { break } }
    return n
}""")
    assert r.lines == ["4"]


# TEST-INT-025 guards x mutable state (V3 8.17) ---------------------------------------
def test_int025_guard_is_snapshot_and_must_be_local_bool():
    r = check("""
mutable record S { open: Bool }
async fn f(s: S, rx: ReceivePort[Int]) -> Int throws ChannelClosed {
    return select { when s.open: receive x from rx => x }
}""")
    assert r.check_codes  # a field read is not a precomputed local guard
    r = ok("""
async fn main() {
    let ch = Channel[Int].unbounded()
    let rx = ch.receiver()
    let tx = ch.sender()
    try await tx.send(1) catch ChannelClosed => ()
    let wanted = false
    let v = select now { when wanted: receive x from rx => x
     none ready => -1 }
    print(v)
}""")
    assert r.lines == ["-1"]


# TEST-INT-026 modules x mutable state x tasks (V3 8.18) ------------------------------
def test_int026_module_state_frozen_and_service_task_owns_mutation():
    files = {"svc.lang": """
pub const DEFAULT_LIMIT = 3
pub async fn counter(rx: ReceivePort[Int], out: SendPort[Int]) throws ChannelClosed {
    let total = 0
    for await x in rx { total = total + x }
    await out.send(total)
}
"""}
    from tests.helpers import Run
    import io, tempfile
    from pathlib import Path
    r = run("""
import svc
async fn main() {
    let inbox = Channel[Int].unbounded()
    let results = Channel[Int].unbounded()
    let rr = results.receiver()
    let total = parallel {
        spawn svc.counter(inbox.receiver(), results.sender())
        let tx = inbox.sender()
        for i in 0..svc.DEFAULT_LIMIT { try await tx.send(i) catch ChannelClosed => () }
        inbox.close()
        try await rr.receive() catch ChannelClosed => -1
    }
    print(total)
}""", files=files)
    assert r.lines == ["3"], r.text()
    r = check("let counter = 0\nfn f() { }")
    assert "S.MODULE.MUTABLE_GLOBAL" in r.check_errors


# TEST-INT-027 auto-import x reproducibility (V3 8.19) --------------------------------
def test_int027_known_ambiguous_and_unknown_imports_distinguished():
    known = check('fn f() -> Str { return readText("x") }')
    d = next(d for d in known.check if d.stable_code == "S.NAME.UNRESOLVED")
    assert len(d.fixes) == 1 and "import std.fs" in d.fixes[0].description
    files = {"a.lang": "pub fn helper() -> Int { return 1 }", "b.lang": "pub fn helper() -> Int { return 2 }"}
    amb = check("fn f() -> Int { return helper() }", files=files)
    d = next(d for d in amb.check if d.stable_code == "S.NAME.UNRESOLVED")
    assert len(d.fixes) == 2 and "choose" in " ".join(d.help)
    unk = check("fn f() -> Int { return frobnicate() }")
    d = next(d for d in unk.check if d.stable_code == "S.NAME.UNRESOLVED")
    assert not d.fixes and any("dependency" in n.message for n in d.notes)


# TEST-INT-028 diagnostics x privacy (V3 8.20) -----------------------------------------
def test_int028_sensitive_fields_redacted_in_diagnostics():
    r = run("""
record Creds { user: Str, sensitive token: Str }
fn check_it(c: Creds) requires c.user != "root" { }
fn main() { let secret = "s3cr" + "3t-value"
 check_it(Creds(user: "ro" + "ot", token: secret)) }""")
    assert r.codes == ["A.CONTRACT.PRECONDITION_FAILED"]
    text = r.text()
    # captured runtime values are redacted; the user's own source text is shown as written
    assert "s3cr3t-value" not in text and '"root"' in text


def test_int028_long_values_bounded():
    r = run("""
fn main() { let s = "x".repeat(100000)
 let xs = [s]
 print(xs[3]) }""")
    assert len(r.text()) < 20000


# TEST-INT-029 protocol contracts x mutable implementations (V3 8.9) ------------------
def test_int029_mutable_implementation_conforms_but_is_not_sendable():
    r = run("""
protocol Counter { fn next(self) -> Int
    ensures result > 0 }
mutable record C { n: Int
 fn next(self) -> Int { self.n = self.n + 1
  return self.n } }
fn tick(c: Counter) -> Int { return c.next() }
async fn remote(c: Counter) -> Int { return c.next() }
async fn main() {
    let c = C(n: 0)
    print(tick(c), tick(c))
    let v = parallel { let h = spawn remote(c)
     await h }
    print(v, c.n)
}""")
    # mutable values are graph-copied into the child: the parent's state is unaffected
    assert r.lines == ["1 2", "3 2"], r.text()


# TEST-INT-030 resources x abandonment transaction example (V3 8.6) -------------------
TXN = ERR + """
mutable record Db { log: MutableList[Str] }
resource fn txn(db: Db) yields Db {
    db.log.push("begin")
    let exit = yield db
    match exit {
        ScopeExit.Normal => db.log.push("commit")
        _ => db.log.push("rollback")
    }
}
"""


def test_int030_transaction_commit_and_rollback():
    r = ok(TXN + """
fn main() {
    let db = Db(log: MutableList[Str]())
    use t = txn(db) { t.log.push("write 1") }
    let r = try use t = txn(db) { t.log.push("write 2")
     throw Bad(n: 1) } catch Bad => "handled"
    print(db.log, r)
}""")
    assert r.lines == ['MutableList["begin", "write 1", "commit", "begin", "write 2", "rollback"] handled']


def test_int030_abandonment_runs_only_abandon_safe_release(tmp_path):
    target = tmp_path / "txn.txt"
    r = run(f"""import std.fs
resource fn txn(path: Str) yields fs.File throws FileNotFound, PermissionDenied, IOFailure {{
    use f = try fs.openAtomicWrite(path) {{
        onAbandon f.close()
        let exit = yield f
        print("provider continuation")
    }}
}}
fn main() throws FileNotFound, PermissionDenied, IOFailure {{
    use f = try txn("{target}") {{
        try f.write("partial")
        assert false, "state declared invalid"
    }}
}}""")
    assert r.codes == ["A.ASSERT.FAILED"]
    assert "provider continuation" not in r.stdout   # arbitrary provider code does not run
    assert not target.exists()                       # the atomic write was rolled back, not committed
    assert list(tmp_path.iterdir()) == []            # and its temp file was discarded
