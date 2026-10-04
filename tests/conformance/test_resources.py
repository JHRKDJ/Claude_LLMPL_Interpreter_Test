"""Resource providers, scopes, borrows, release and defer interactions (V3 5.5, 5.6, 7.9, 8.5-8.7)."""
from tests.helpers import ok, run

PROV = """
error AcquireFailed { }
error ReleaseFailed { }
error BodyFailed { }
mutable record Conn { id: Int
 open: Bool }

resource fn connect(id: Int, failAcquire: Bool = false, failRelease: Bool = false) yields Conn
    throws AcquireFailed, ReleaseFailed
{
    if failAcquire { throw AcquireFailed() }
    print("acquire {id}")
    let c = Conn(id: id, open: true)
    let exit = yield c
    c.open = false
    print("release {id} {exit}")
    if failRelease { throw ReleaseFailed() }
}
"""


def test_scope_is_expression_valued_and_releases_on_success():
    r = ok(PROV + """
fn main() throws AcquireFailed, ReleaseFailed {
    let v = use c = try connect(1) {
        print("body {c.id}")
        c.id * 10
    }
    print("value {v}")
}""")
    assert r.lines == ["acquire 1", "body 1", "release 1 ScopeExit.Normal", "value 10"]


def test_release_on_recoverable_exception_knows_exit_class():
    r = run(PROV + """
fn main() throws AcquireFailed, ReleaseFailed, BodyFailed {
    use c = try connect(2) {
        throw BodyFailed()
    }
}""")
    assert r.lines == ["acquire 2", "release 2 ScopeExit.Failed"]
    assert r.outcome == "threw" and "BodyFailed" in r.diag.message


def test_acquisition_failure_runs_no_release():
    r = run(PROV + """
fn main() throws AcquireFailed, ReleaseFailed {
    use c = try connect(3, failAcquire: true) { print("body") }
}""")
    assert r.lines == []
    assert "AcquireFailed" in r.diag.message


def test_release_failure_after_success_is_outward():
    r = run(PROV + """
fn main() throws AcquireFailed, ReleaseFailed {
    let v = use c = try connect(4, failRelease: true) { 1 }
    print("unreachable {v}")
}""")
    assert r.lines == ["acquire 4", "release 4 ScopeExit.Normal"]
    assert "ReleaseFailed" in r.diag.message


def test_release_failure_after_body_failure_aggregates():
    r = run(PROV + """
fn main() throws AggregateException {
    use c = try connect(5, failRelease: true) { throw BodyFailed() }
}""")
    assert "AggregateException" in r.diag.message
    assert [c.extra.get("source") for c in r.diag.children] == ["body", "release"]


def test_abandonment_skips_provider_continuation_and_defer():
    r = run(PROV + """
fn main() throws AcquireFailed, ReleaseFailed {
    use c = try connect(6) {
        defer print("defer must not run")
        assert c.id < 0
    }
}""")
    assert r.lines == ["acquire 6"]
    assert r.codes == ["A.ASSERT.FAILED"]


def test_provider_must_yield_exactly_once():
    r = run("""
resource fn bad() yields Int { print("no yield") }
fn main() { use x = bad() { print(x) } }""")
    assert r.codes == ["A.RESOURCE.NO_YIELD"]
    r = run("""
resource fn twice() yields Int { yield 1
 yield 2 }
fn main() { use x = twice() { print(x) } }""")
    assert r.codes == ["A.RESOURCE.MULTIPLE_YIELD"]


def test_provider_only_in_use():
    r = run(PROV + """
fn main() { let c = connect(1) }""")
    assert r.codes == ["A.RESOURCE.PROVIDER_OUTSIDE_USE"]


def test_borrow_cannot_escape_by_return_store_or_let():
    r = run(PROV + """
fn leak(c: Conn) -> Conn { return c }
fn main() throws AcquireFailed, ReleaseFailed { use c = try connect(1) { leak(c) } }""")
    assert r.codes == ["A.RESOURCE.ESCAPE"]
    r = run(PROV + """
fn main() throws AcquireFailed, ReleaseFailed { use c = try connect(1) { let xs = MutableList.of(c) } }""")
    assert r.codes == ["A.RESOURCE.ESCAPE"]
    r = run(PROV + """
fn main() throws AcquireFailed, ReleaseFailed { use c = try connect(1) { let alias = c } }""")
    assert r.codes == ["A.RESOURCE.ESCAPE"]


def test_borrow_passes_to_helpers():
    r = ok(PROV + """
fn describe(c: borrow Conn) -> Str { return "conn {c.id} open={c.open}" }
fn main() throws AcquireFailed, ReleaseFailed { use c = try connect(7) { print(describe(c)) } }""")
    assert r.lines == ["acquire 7", "conn 7 open=true", "release 7 ScopeExit.Normal"]


def test_use_after_release_through_escaped_closure():
    r = run(PROV + """
fn main() throws AcquireFailed, ReleaseFailed {
    let f = use c = try connect(8) { fn() => c.id }
    print(f())
}""")
    assert r.codes == ["A.RESOURCE.USE_AFTER_RELEASE"]
    assert r.diag.resource is not None


def test_composed_provider_scoped_delegation():
    r = ok(PROV + """
resource fn pooled() yields Conn throws AcquireFailed, ReleaseFailed {
    use inner = try connect(9) {
        print("configure {inner.id}")
        yield inner
        print("pool cleanup")
    }
}
fn main() throws AcquireFailed, ReleaseFailed { use c = try pooled() { print("using {c.id}") } }""")
    assert r.lines == ["acquire 9", "configure 9", "using 9", "pool cleanup", "release 9 ScopeExit.Normal"]


def test_fs_atomic_write_commits_or_rolls_back(tmp_path):
    out = tmp_path / "out.txt"
    r = ok(f"""import std.fs
error Stop {{ }}
fn main() throws FileNotFound, PermissionDenied, IOFailure {{
    use f = try fs.openAtomicWrite("{out}") {{ try f.write("committed") }}
    let r = capture use g = try fs.openAtomicWrite("{out}") {{
        try g.write("partial")
        throw Stop()
    }}
    print(try fs.readText("{out}"))
}}""")
    assert r.lines == ["committed"]


def test_fs_read_missing_file_is_recoverable(tmp_path):
    r = ok(f"""import std.fs
fn main() {{
    let t = try fs.readText("{tmp_path}/nope") catch FileNotFound as e => "missing {{e.path}}"
    print(t)
}}""")
    assert r.lines == [f"missing {tmp_path}/nope"]


def test_on_abandon_restricted_to_builtin_primitives():
    r = run("""
mutable record R { n: Int
 fn undo(self) { } }
resource fn p() yields R {
    let r = R(n: 1)
    onAbandon r.undo()
    yield r
}
fn main() { use x = p() { } }""")
    assert r.codes == ["A.RESOURCE.PROVIDER_OUTSIDE_USE"]


def test_on_abandon_runs_registered_release(tmp_path):
    path = tmp_path / "a.txt"
    r = run(f"""import std.fs
resource fn logged(path: Str) yields fs.File throws FileNotFound, PermissionDenied, IOFailure {{
    use f = try fs.openWrite(path) {{
        onAbandon f.close()
        yield f
        print("normal release")
    }}
}}
fn main() throws FileNotFound, PermissionDenied, IOFailure {{
    use f = try logged("{path}") {{
        try f.write("x")
        assert false, "invariant broken"
    }}
}}""")
    assert r.codes == ["A.ASSERT.FAILED"]
    assert "normal release" not in r.stdout
