"""Draft vs verified mode interactions (V3 5.15, 7.6.4): the modes differ in
acceptance and proof, never in the meaning of a written annotation."""
import io
import subprocess
import sys
from pathlib import Path

from tests.helpers import run

ERRS = "error Bad { n: Int }\n"


def test_draft_runs_with_obligation_warnings_verified_refuses():
    src = ERRS + """
fn f(x: Int) -> Int throws Bad { if x < 0 { throw Bad(n: x) }
 return x }
fn main() { print(f(1)) }"""
    d = run(src, "draft")
    assert d.exit_code == 0 and d.lines == ["1"]
    assert "S.EFFECT.MISSING_TRY" in d.check_warnings
    v = run(src, "verified")
    assert v.exit_code is None
    assert "S.EFFECT.MISSING_TRY" in v.check_errors


def test_unmarked_failure_still_propagates_in_draft():
    # V3 5.15.3: if an unmarked throwing call fails in draft, the exception propagates
    r = run(ERRS + """
fn f() -> Int throws Bad { throw Bad(n: 7) }
fn main() { print(f())
 print("unreachable") }""", "draft")
    assert r.exit_code == 1 and r.outcome == "threw" and r.lines == []


def test_written_annotations_enforced_at_runtime_in_draft():
    # V3 5.3.2-3: draft relaxes obligations, not the meaning of written annotations
    src = """
fn mk() { return "text" }
fn f(x: Int) -> Int { return x + 1 }
fn main() { print(f(mk())) }"""
    r = run(src, "draft")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"] and r.exit_code == 3


def test_same_annotation_failure_in_verified_when_value_is_truly_dynamic():
    # verified still performs runtime checks where truly dynamic values enter typed code
    src = """
import std.json
pub fn f(x: Int) -> Int { return x + 1 }
pub fn main() throws JsonError {
    let v = try json.parse("\\"text\\"")
    print(f(v))
}"""
    r = run(src, "verified")
    assert r.check_errors == [], r.text()
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


def test_verified_rejects_method_calls_on_dyn():
    # V3 7.7.6: a Dyn callable has no known error set; verified code must narrow it
    r = run("""
import std.json
pub fn main() throws JsonError {
    let v = try json.parse("[1]")
    print(v.length)
    print(v.get(0))
}""", "verified")
    assert "S.TYPE.DYNAMIC_CALL" in r.check_errors


def test_exhaustiveness_runtime_in_draft_static_in_verified():
    # V3 3.3: "the interpreter catches missing cases at runtime in draft mode and the
    # static checker catches them in verified mode"
    src = """
enum Color { Red, Green, Blue }
fn name(c: Color) -> Str { return match c { Color.Red => "r", Color.Green => "g" } }
fn main() { print(name(Color.Red))
 print(name(Color.Blue)) }"""
    d = run(src, "draft")
    assert d.lines == ["r"] and d.codes == ["A.MATCH.NO_ARM"]
    v = run(src, "verified")
    assert v.exit_code is None and "S.MATCH.NON_EXHAUSTIVE" in v.check_errors


def test_task_isolation_active_in_draft():
    # V3 5.15.4 / 2487: task isolation is not optional in draft mode
    r = run("""
async fn w(c: Dyn) { }
async fn main() { let ch = Channel[Int].unbounded()
 parallel { spawn w(ch) } }""", "draft")
    assert r.codes == ["A.TASK.NOT_SENDABLE"]


def test_contracts_active_in_draft():
    r = run("""
fn f(x: Int) -> Int requires x > 0 { return x }
fn main() { print(f(0)) }""", "draft")
    assert r.codes == ["A.CONTRACT.PRECONDITION_FAILED"]


def test_dynamic_callable_runs_in_draft_rejected_in_verified():
    src = """
fn apply(g, x: Int) -> Int { return g(x) }
fn inc(x: Int) -> Int { return x + 1 }
fn main() { print(apply(inc, 1)) }"""
    assert run(src, "draft").lines == ["2"]
    assert "S.TYPE.DYNAMIC_CALL" in run(src, "verified").check_errors


def test_project_manifest_selects_mode():
    files = {"lang.toml": '[project]\nname = "app"\nmode = "verified"\n'}
    from tests.helpers import check
    r = check(ERRS + "fn f() -> Int throws Bad { throw Bad(n: 1) }\nfn g() -> Int { return f() }",
              mode=None, files=files)
    assert "S.EFFECT.MISSING_TRY" in r.check_errors


def _cli(args, cwd):
    root = Path(__file__).resolve().parents[2]
    return subprocess.run([sys.executable, "-m", "lang", *args], cwd=cwd, capture_output=True, text=True,
                          env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"}, timeout=60)


def test_release_requires_verified(tmp_path):
    p = tmp_path / "main.lang"
    p.write_text('fn main() { print("hi") }\n')
    r = _cli(["run", "--release", "--mode", "draft", str(p)], tmp_path)
    assert r.returncode == 2 and "S.MODE.RELEASE_REQUIRES_VERIFIED" in r.stderr
    r = _cli(["run", "--release", str(p)], tmp_path)
    assert r.returncode == 0 and r.stdout == "hi\n"


def test_release_build_rejects_draft_only_program(tmp_path):
    p = tmp_path / "main.lang"
    p.write_text(ERRS + "fn f() -> Int throws Bad { throw Bad(n: 1) }\nfn main() { print(f()) }\n")
    r = _cli(["run", "--release", str(p)], tmp_path)
    assert r.returncode == 2 and "S.EFFECT.MISSING_TRY" in r.stderr
    r = _cli(["run", str(p)], tmp_path)
    assert r.returncode == 1  # draft: runs, the unmarked failure propagates to top level
