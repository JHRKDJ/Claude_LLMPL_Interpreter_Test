"""CLI command family (V3 7.14.2): run/check/format/test/repl, exit codes, JSON."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def cli(args, cwd, stdin=None):
    return subprocess.run([sys.executable, "-m", "lang", *args], cwd=cwd, capture_output=True, text=True,
                          input=stdin, env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"}, timeout=120)


def write(tmp_path, name, text):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_run_exit_codes(tmp_path):
    ok = write(tmp_path, "ok.lang", 'fn main() { print("hi") }\n')
    r = cli(["run", str(ok)], tmp_path)
    assert (r.returncode, r.stdout) == (0, "hi\n")
    thr = write(tmp_path, "thr.lang", "error Bad { }\nfn main() throws Bad { throw Bad() }\n")
    assert cli(["run", str(thr)], tmp_path).returncode == 1
    st = write(tmp_path, "st.lang", "fn main() { print(nope) }\n")
    r = cli(["run", str(st)], tmp_path)
    assert r.returncode == 2 and "S.NAME.UNRESOLVED" in r.stderr
    ab = write(tmp_path, "ab.lang", "fn main() { let xs = [1]\n print(xs[5]) }\n")
    r = cli(["run", str(ab)], tmp_path)
    assert r.returncode == 3 and "A.INDEX.OUT_OF_RANGE" in r.stderr
    code = write(tmp_path, "code.lang", "fn main() -> Int { return 7 }\n")
    assert cli(["run", str(code)], tmp_path).returncode == 7


def test_run_passes_arguments(tmp_path):
    p = write(tmp_path, "args.lang", "fn main(args: List[Str]) { print(args.length, args[0]) }\n")
    r = cli(["run", str(p), "alpha", "beta"], tmp_path)
    assert r.stdout == "2 alpha\n"


def test_check_json_is_machine_readable(tmp_path):
    p = write(tmp_path, "c.lang", "fn f() -> Int { return lenght }\n")
    r = cli(["check", "--json", str(p)], tmp_path)
    assert r.returncode == 2
    data = json.loads(r.stdout)
    d = data["diagnostics"][0]
    assert d["code"]["stable_code"] == "S.NAME.UNRESOLVED"
    assert (d["code"]["outcome"], d["code"]["domain"], d["code"]["reason"]) == ("static", "name", "unresolved")
    assert d["severity"] == "error" and d["blocking"] is True
    assert d["primary"]["span"]["start"] == {"line": 1, "column": 24, "offset": 23}


def test_check_fix_inserts_known_import(tmp_path):
    p = write(tmp_path, "fx.lang", 'fn f() -> Str throws IOFailure, FileNotFound, PermissionDenied '
                                    '{ return try fs.readText("x") }\n')
    r = cli(["check", "--fix", str(p)], tmp_path)
    assert "import std.fs" in p.read_text()
    r = cli(["check", str(p)], tmp_path)
    assert "S.NAME.UNRESOLVED" not in r.stderr


def test_check_fix_diff_does_not_write(tmp_path):
    src = 'fn f() -> Str throws IOFailure, FileNotFound, PermissionDenied { return try fs.readText("x") }\n'
    p = write(tmp_path, "fd.lang", src)
    r = cli(["check", "--fix", "--diff", str(p)], tmp_path)
    assert p.read_text() == src and "+import std.fs" in r.stdout


def test_format_check_diff_and_write(tmp_path):
    p = write(tmp_path, "f.lang", "fn main() { let x=1+2\nprint(x) }\n")
    r = cli(["format", "--check", str(p)], tmp_path)
    assert r.returncode == 1
    r = cli(["format", "--diff", str(p)], tmp_path)
    assert "+    let x = 1 + 2" in r.stdout and p.read_text() == "fn main() { let x=1+2\nprint(x) }\n"
    assert cli(["format", str(p)], tmp_path).returncode == 0
    assert p.read_text() == "fn main() {\n    let x = 1 + 2\n    print(x)\n}\n"
    assert cli(["format", "--check", str(p)], tmp_path).returncode == 0


def test_format_refuses_syntax_errors(tmp_path):
    p = write(tmp_path, "bad.lang", "fn main() { let = 1 }\n")
    r = cli(["format", str(p)], tmp_path)
    assert r.returncode == 2 and "syntax errors" in r.stderr
    assert p.read_text() == "fn main() { let = 1 }\n"


def test_test_command_and_seeded_stress(tmp_path):
    p = write(tmp_path, "t.lang", """
fn add(a: Int, b: Int) -> Int { return a + b }
test "adds" { assert add(1, 2) == 3 }
async fn racer(tx: SendPort[Int], v: Int) throws ChannelClosed { await tx.send(v) }
test "order" {
    let ch = Channel[Int].unbounded()
    let rx = ch.receiver()
    let tx = ch.sender()
    parallel { spawn racer(tx, 1)
     spawn racer(tx, 2) }
    let first = try await rx.receive()
    assert first == 1, "ordering assumption"
}
""")
    r = cli(["test", str(p)], tmp_path)
    assert r.returncode == 0 and "2 passed, 0 failed" in r.stdout
    r = cli(["test", str(p), "--schedule=random", "--seed=1", "--repeat", "12", "--filter", "order"], tmp_path)
    assert r.returncode == 1
    assert "W.TEST.SEED" in r.stderr and "--schedule=random --seed=" in r.stderr
    seed = int(r.stdout.split("FAIL")[1].split("[seed ")[1].split("]")[0])
    r2 = cli(["test", str(p), "--schedule=random", f"--seed={seed}", "--filter", "order"], tmp_path)
    assert r2.returncode == 1  # the recorded seed reproduces the failure


def test_test_json(tmp_path):
    p = write(tmp_path, "tj.lang", 'test "a" { assert 1 == 1 }\ntest "b" { assert 1 == 2 }\n')
    r = cli(["test", "--json", str(p)], tmp_path)
    data = json.loads(r.stdout)
    assert [(x["name"], x["passed"]) for x in data["results"]] == [("a", True), ("b", False)]
    assert data["results"][1]["diagnostics"][0]["code"]["stable_code"] == "A.ASSERT.FAILED"


def test_release_requires_verified(tmp_path):
    p = write(tmp_path, "rel.lang", 'fn main() { print("x") }\n')
    r = cli(["run", "--release", "--mode", "draft", str(p)], tmp_path)
    assert r.returncode == 2 and "S.MODE.RELEASE_REQUIRES_VERIFIED" in r.stderr


def test_repl_via_stdin(tmp_path):
    r = cli(["repl", "--clock", "virtual"], tmp_path, stdin="let x = 2\nfn sq(n: Int) -> Int {\n return n * n\n}\nsq(x)\n:quit\n")
    assert r.stdout.splitlines() == ["defined sq", "4"]
