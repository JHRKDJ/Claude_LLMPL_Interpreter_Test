"""REPL session semantics (V3 7.14.4, SPEC-024)."""
import io

from lang.tooling.repl import ReplSession, needs_more


def session(tmp_path, mode="draft"):
    out, err = io.StringIO(), io.StringIO()
    return ReplSession(mode=mode, clock="virtual", root=tmp_path, stdout=out, stderr=err), out, err


def test_bindings_persist_and_values_print(tmp_path):
    s, out, err = session(tmp_path)
    for e in ["let xs = MutableList[Int]()", "xs.push(1)", "xs.push(2)", "xs.length", "xs"]:
        s.execute(e)
    assert out.getvalue().splitlines() == ["2", "MutableList[1, 2]"], err.getvalue()


def test_declarations_accumulate(tmp_path):
    s, out, err = session(tmp_path)
    s.execute("record P { x: Int }")
    s.execute("fn mk(n: Int) -> P { return P(x: n) }")
    s.execute("mk(3).x")
    assert out.getvalue().splitlines() == ["defined P", "defined mk", "3"]


def test_redefinition_is_explicit_and_discards_bindings(tmp_path):
    s, out, err = session(tmp_path)
    s.execute("record P { x: Int }")
    s.execute("let p = P(x: 1)")
    s.execute("record P { x: Int, y: Int }")
    text = out.getvalue()
    assert "redefined `P`; discarded session bindings: p" in text
    s.execute("p")
    assert "S.NAME.UNRESOLVED" in err.getvalue()


def test_rejected_declaration_leaves_workspace_unchanged(tmp_path):
    s, out, err = session(tmp_path, mode="verified")
    s.execute("fn ok() -> Int { return 1 }")
    s.execute('fn bad() -> Int { return "s" }')
    assert "S.TYPE.STATIC_MISMATCH" in err.getvalue()
    assert "bad" not in s.decls
    s.execute("ok()")
    assert out.getvalue().splitlines()[-1] == "1"


def test_runtime_failure_keeps_session(tmp_path):
    s, out, err = session(tmp_path)
    s.execute("let a = 5")
    s.execute("[1][3]")
    assert "A.INDEX.OUT_OF_RANGE" in err.getvalue()
    s.execute("a + 1")
    assert out.getvalue().splitlines() == ["6"]


def test_async_top_level(tmp_path):
    s, out, err = session(tmp_path)
    s.execute("async fn later() -> Int {\n await sleep(5.millis)\n return 9\n}")
    s.execute("await later()")
    s.execute("parallel { let h = spawn later()\n await h }")
    assert out.getvalue().splitlines() == ["defined later", "9", "9"], err.getvalue()


def test_load_and_explicit_reload(tmp_path):
    mod = tmp_path / "util.lang"
    mod.write_text("pub fn greet() -> Str { return \"v1\" }\n")
    s, out, err = session(tmp_path)
    s.execute(":load util.lang")
    s.execute("let keep = 1")
    s.execute("util.greet()")
    mod.write_text("pub fn greet() -> Str { return \"v2\" }\n")
    s.execute("util.greet()")  # not reloaded yet: module identity unchanged
    s.execute(":reload util")
    s.execute("util.greet()")
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("loaded module util")
    assert lines[1:3] == ['"v1"', '"v1"']
    assert "discarded session bindings: keep" in out.getvalue()
    assert lines[-1] == '"v2"'


def test_continuation_detection():
    assert needs_more("fn f() {")
    assert needs_more("let x = 1 +")
    assert not needs_more('let s = "{"')
    assert not needs_more("fn f() { }")
