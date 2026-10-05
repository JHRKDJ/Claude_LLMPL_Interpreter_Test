"""Runtime diagnostics that are otherwise rarely reached: stuck cleanup and hard
termination (V3 7.10.11), cleanup failure under cancellation (5.6), awaited-task
outcomes (5.12.3), checked-alternative abandonments (5.7.8), resource and channel
misuse caught dynamically, and runtime/static advisories (7.9.7, 5.13.8)."""
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from lang.runtime.interp import RunOptions
from lang.tooling.driver import run_program
from tests.helpers import check, run, run_unchecked

ROOT = Path(__file__).resolve().parents[2]


def _run_opts(src, **opts):
    d = Path(tempfile.mkdtemp(prefix="langdiag-"))
    p = d / "main.lang"
    p.write_text(src)
    out = io.StringIO()
    o = RunOptions(mode="draft", clock="virtual", stdout=out, stderr=io.StringIO(), **opts)
    co, r = run_program(p, o)
    return out.getvalue(), r


# ---------------------------------------------------------------- stuck cleanup
STUCK = """
async fn main() {
    let r = try within 10.millis {
        defer { await sleep(30.seconds)
            print("cleanup finished") }
        await sleep(1.seconds)
        1
    } catch DeadlineExceeded => -1
    print(r)
}"""


def test_slow_cleanup_under_cancellation_reports_stuck_cleanup_and_still_finishes():
    out, r = _run_opts(STUCK, stuck_cleanup_after_ms=1000)
    assert out.splitlines() == ["cleanup finished", "-1"]
    assert r.exit_code == 0
    w = [d for d in r.warnings if d.stable_code == "W.CLEANUP.STUCK"]
    assert len(w) == 1 and "1000 ms" in w[0].message
    # no language-level timeout: cleanup is not cut short (V3 7.10.11)


def test_cleanup_within_threshold_is_not_reported():
    out, r = _run_opts(STUCK, stuck_cleanup_after_ms=60000)
    assert r.exit_code == 0 and not [d for d in r.warnings if d.stable_code == "W.CLEANUP.STUCK"]


def test_cleanup_that_can_never_finish_is_stuck_and_deadlocked():
    out, r = _run_opts("""
async fn main() {
    let ch = Channel[Int].rendezvous()
    let rx = ch.receiver()
    let tx = ch.sender()
    let r = try within 10.millis {
        defer { let v = try await rx.receive() catch ChannelClosed => 0 }
        await sleep(1.seconds)
    } catch DeadlineExceeded => ()
}""")
    assert r.outcome == "abandoned"
    assert [d.stable_code for d in r.diagnostics] == ["A.CONCURRENCY.DEADLOCK"]
    assert any("stuck cleanup" in n.message for n in r.diagnostics[0].notes)
    assert [d.stable_code for d in r.warnings] == ["W.CLEANUP.STUCK"]


# ---------------------------------------------------------------- interrupts
LOOP = """
async fn main() {
    defer { print("cleanup ran") }
    print("started")
    while true { await sleep(10.millis) }
}"""


def _spawn(src):
    d = Path(tempfile.mkdtemp(prefix="langsig-"))
    p = d / "main.lang"
    p.write_text(src)
    proc = subprocess.Popen([sys.executable, "-m", "lang", "run", str(p)], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "started"
    return proc


def test_first_interrupt_cancels_cooperatively_with_cleanup():
    proc = _spawn(LOOP)
    proc.send_signal(signal.SIGINT)
    out, err = proc.communicate(timeout=30)
    assert "cleanup ran" in out
    assert "C.PROGRAM.INTERRUPTED" in err
    assert proc.returncode not in (0, 4)


def test_second_interrupt_escalates_to_hard_termination():
    proc = _spawn("""
async fn main() {
    defer { while true { await sleep(10.millis) } }
    print("started")
    while true { await sleep(10.millis) }
}""")
    proc.send_signal(signal.SIGINT)
    time.sleep(0.5)  # first interrupt: cancellation is delivered, cleanup now loops forever
    assert proc.poll() is None
    proc.send_signal(signal.SIGINT)
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 4
    assert "hard termination" in err


# ---------------------------------------------------------------- cleanup under cancellation
def test_cleanup_failure_while_cancelling_is_reported_and_cancellation_preserved():
    r = run("""
error Flush { }
async fn work() throws Flush {
    defer { throw Flush() }
    await sleep(1.seconds)
}
async fn main() {
    let v = try within 5.millis { try await work()
        1 } catch DeadlineExceeded => 2 catch Flush => 3
    print(v)
}""")
    assert "W.CLEANUP.FAILED_DURING_CANCELLATION" in [d.stable_code for d in r.warnings]
    assert r.lines == ["2"]  # the deadline cancellation still wins (V3 5.6 table)


# ---------------------------------------------------------------- awaited outcomes
def test_awaiting_an_abandoned_child_abandons_with_cause():
    r = run_unchecked("""
async fn bad() -> Int { let xs = [1]
 return xs[5] }
async fn main() {
    parallel collect {
        let h = spawn bad()
        await sleep(1.millis)
        print(await h)
    }
}""")
    # in collect mode the group itself reports abandonment as data, but a direct
    # `await` needs the value, so the awaiting task abandons with the child's cause
    assert r.codes == ["A.TASK.AWAITED_ABANDONED"]
    assert [c.stable_code for c in r.diags[0].causes] == ["A.INDEX.OUT_OF_RANGE"]


def test_empty_race_group_abandons():
    r = run_unchecked("""
async fn main() { let v = parallel race { 1 }
 print(v) }""")
    assert r.codes == ["A.TASK.EMPTY_GROUP"]


def test_task_handle_used_outside_its_group_abandons_dynamically():
    r = run_unchecked("""
async fn w() -> Int { return 1 }
async fn main() {
    let hs = MutableList[Dyn]()
    parallel { hs.push(spawn w()) }
    print(await (hs[0]))
}""")
    assert r.codes == ["A.TASK.HANDLE_OUTSIDE_SCOPE"]


# ---------------------------------------------------------------- checked alternatives
def test_unwrap_none_and_err_abandon_with_specific_codes():
    assert run("fn main() { let x: Int? = null\n print(x.unwrap()) }").codes == ["A.OPTION.UNWRAP_NONE"]
    assert run("""
error E { }
fn main() { let r: Result[Int, E] = Err(E())
 print(r.unwrap()) }""").codes == ["A.RESULT.UNWRAP_ERR"]


def test_invalid_numeric_conversion_abandons():
    assert run("import std.math\nfn main() { print(math.nan.round()) }").codes == ["A.NUMERIC.INVALID_CONVERSION"]
    assert run("fn main() { print(10.pow(400).toFloat()) }").codes == ["A.NUMERIC.INVALID_CONVERSION"]


def test_propagate_in_non_result_function_abandons_dynamically():
    r = run_unchecked("""
error E { }
fn g() -> Result[Int, E] { return Err(E()) }
fn f() -> Int { let v = propagate g()
 return v }
fn main() { print(f()) }""")
    assert r.codes == ["A.EFFECT.UNDECLARED_PROPAGATE"]


def test_released_port_use_abandons():
    r = run("""
async fn main() {
    let ch = Channel[Int].buffered(1)
    let tx = ch.sender()
    tx.release()
    try await tx.send(1) catch ChannelClosed => ()
}""")
    assert r.codes == ["A.CHANNEL.PORT_RELEASED"]


def test_dynamic_member_errors_abandon():
    assert run("record P { x: Int }\nfn main() { let p: Dyn = P(x: 1)\n print(p.y) }").codes == \
        ["A.TYPE.UNKNOWN_FIELD"]
    assert run("record P { x: Int }\nfn main() { let p: Dyn = P(x: 1)\n print(p.go()) }").codes == \
        ["A.TYPE.UNKNOWN_METHOD"]
    assert run("fn main() { let f: Dyn = 3\n print(f(1)) }").codes == ["A.TYPE.NOT_CALLABLE"]


# ---------------------------------------------------------------- modules
def test_entry_module_without_main():
    r = run("fn helper() -> Int { return 1 }")
    assert "S.MODULE.NO_MAIN" in r.codes + r.check_codes


def test_malformed_manifest_is_reported():
    r = run("fn main() { print(1) }", files={"lang.toml": "[project\nname = 'x'\n"})
    assert "S.MODULE.MANIFEST" in r.check_codes + r.codes


# ---------------------------------------------------------------- advisories
def test_scope_too_wide_advisory():
    r = check("""
import std.fs
async fn f(p: Str) -> Str throws FileNotFound, PermissionDenied, IOFailure {
    return use file = fs.openRead(p) {
        let text = try file.readAll()
        await sleep(5.seconds)
        text
    }
}""", "draft")
    assert "W.RESOURCE.SCOPE_TOO_WIDE" in r.check_warnings, r.text()


def test_scope_used_until_the_end_has_no_advisory():
    r = check("""
import std.fs
async fn f(p: Str) -> Str throws FileNotFound, PermissionDenied, IOFailure {
    return use file = fs.openRead(p) {
        await sleep(5.seconds)
        try file.readAll()
    }
}""", "draft")
    assert "W.RESOURCE.SCOPE_TOO_WIDE" not in r.check_warnings


def test_unbounded_channel_growth_advisory():
    r = run("""
async fn main() {
    let ch = Channel[Int].unbounded()
    let tx = ch.sender()
    for i in 0..10001 { try await tx.send(i) catch ChannelClosed => () }
    print(ch.isClosed())
}""")
    assert r.lines == ["false"]
    assert [d.stable_code for d in r.warnings] == ["W.CHANNEL.UNBOUNDED_GROWTH"]


# ---------------------------------------------------------------- report trees
def test_unhandled_aggregate_has_one_child_per_task_failure():
    r = run("""
error Boom { }
async fn bad() throws Boom { await sleep(1.millis)
 throw Boom() }
async fn slow() { await sleep(1.seconds) }
async fn main() throws AggregateException {
    parallel { spawn bad()
        spawn slow() }
}""")
    d = r.diag
    assert d.stable_code == "R.ERROR.UNHANDLED" and d.extra["error_type"] == "AggregateException"
    assert [(c.stable_code, c.task.path) for c in d.children] == [("R.TASK.AGGREGATE", "main/parallel@7:5/1:bad")]


def test_task_group_failure_lists_cancelled_siblings():
    r = run("""
async fn crash() { await sleep(1.millis)
 let xs = [1]
 print(xs[3]) }
async fn slow() { await sleep(1.seconds) }
async fn main() { parallel { spawn crash()
    spawn slow() } }""")
    d = r.diag
    assert d.stable_code == "A.TASK.GROUP_FAILURE"
    assert [c.stable_code for c in d.children] == ["A.INDEX.OUT_OF_RANGE", "C.TASK.CANCELLED"]
    assert d.children[1].severity == "info"


# ---------------------------------------------------------------- release failure during abandonment
def test_release_failure_during_abandonment_is_appended_not_replacing(tmp_path, monkeypatch):
    """V3 5.5.13: a failing abandonment-safe release never replaces the abandonment."""
    from lang.runtime.builtins.registry import METHODS, load_all
    load_all()
    close = METHODS["File"]["close"]

    def failing_close(interp, recv, args, span):
        raise OSError("device unavailable")
    monkeypatch.setattr(close, "impl", failing_close)
    target = tmp_path / "t.txt"
    target.write_text("x")
    r = run(f"""import std.fs
resource fn guarded(path: Str) yields fs.File throws FileNotFound, PermissionDenied, IOFailure {{
    use f = try fs.openRead(path) {{
        onAbandon f.close()
        yield f
    }}
}}
fn main() throws FileNotFound, PermissionDenied, IOFailure {{
    use f = try guarded("{target}") {{
        let xs = [1]
        print(xs[2])
    }}
}}""")
    assert r.codes == ["A.INDEX.OUT_OF_RANGE"]
    assert any("abandonment-safe release" in n.message and "device unavailable" in n.message
               for n in r.diag.notes)


# ---------------------------------------------------------------- render budgets (V3 7.13.5)
MANY = """
async fn crash(n: Int) { await sleep(1.millis)
    let xs = [1]
    print(xs[n]) }
async fn main() { parallel collect {
    for i in 0..30 { spawn crash(i + 5) }
} }"""


def test_default_view_caps_child_reports_but_json_and_deep_do_not():
    import json
    from lang.diagnostics.render_json import render_json
    from lang.diagnostics.render_text import render_all
    r = run(MANY.replace("parallel collect", "parallel"))
    d = r.diag
    assert len(d.children) == 30
    text = render_all([d])
    assert text.count("A.INDEX.OUT_OF_RANGE") == 20 and "... 10 more child report(s)" in text
    assert render_all([d], "deep").count("A.INDEX.OUT_OF_RANGE") == 30
    assert len(json.loads(render_json([d]))["diagnostics"][0]["children"]) == 30


def test_exhausted_render_budget_emits_a_truncated_report():
    from lang.diagnostics.render_text import RenderBudget, render_all
    r = run(MANY.replace("parallel collect", "parallel"))
    text = render_all([r.diag, r.diag], budget=RenderBudget(0.0))
    assert "rendering budget was exhausted" in text and "2 diagnostic(s) not shown" in text


def test_random_schedule_failure_records_seed_and_recent_decisions():
    """V3 7.14.5: a failure under seeded random scheduling records the seed and the
    recent scheduling decisions; FIFO runs record none."""
    import json
    from lang.diagnostics.render_json import render_json
    from lang.diagnostics.render_text import render_all
    src = """
async fn w(n: Int) -> Int { await sleep(1.millis)
 return n }
async fn main() {
    let t = parallel { let a = spawn w(1)
        let b = spawn w(2)
        let c = spawn w(3)
        (await a) + (await b) + (await c) }
    let xs = [1]
    print(xs[t])
}"""
    r = run(src, schedule="random", seed=42)
    d = r.diag
    assert d.stable_code == "A.INDEX.OUT_OF_RANGE" and d.task.seed == 42
    dec = d.extra["schedule_decisions"]
    assert dec and all({"switch", "ran", "ready", "pick"} <= set(x) for x in dec) and len(dec) <= 32
    assert "recent seeded scheduling decisions" in render_all([d], "deep")
    assert json.loads(render_json([d]))["diagnostics"][0]["extra"]["schedule_decisions"] == dec
    assert "schedule_decisions" not in run(src).diag.extra
