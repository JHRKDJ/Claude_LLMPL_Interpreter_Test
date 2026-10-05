"""BUG-0049 (second audit, T18): (a) `lang check --fix` inserted the import and then
still printed the stale S.NAME.UNRESOLVED diagnostic and exited 2; (b) REPL diagnostics
named a nonexistent file `<cwd>/__repl__.lang`; (c) a literal invalid format spec
(`"{5:x}"`) passed verified checking and abandoned only at run time."""
import subprocess
import sys
from pathlib import Path

from tests.helpers import check

ROOT = Path(__file__).resolve().parents[2]


def cli(args, cwd, stdin=None):
    return subprocess.run([sys.executable, "-m", "lang", *args], cwd=cwd, capture_output=True, text=True,
                          input=stdin, env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"}, timeout=120)


def test_check_fix_reports_the_fixed_program(tmp_path):
    (tmp_path / "util.lang").write_text("pub fn helper() -> Int { return 1 }\n")
    p = tmp_path / "main.lang"
    p.write_text("fn main() { print(helper()) }\n")
    r = cli(["check", "--fix", str(p)], tmp_path)
    assert "import util.{helper}" in p.read_text()
    assert r.returncode == 0 and "S.NAME.UNRESOLVED" not in r.stderr, r.stderr


def test_repl_diagnostics_do_not_name_a_fake_file(tmp_path):
    r = cli(["repl"], tmp_path, stdin="fn f() -> Int { return nope }\n")
    assert "__repl__.lang" not in r.stderr + r.stdout and "<repl>" in r.stderr + r.stdout, r.stderr


def test_invalid_literal_format_spec_is_static():
    r = check('fn f() -> Str { return "{5:x}" }', "verified")
    assert "S.SYNTAX.INVALID_FORMAT_SPEC" in r.check_errors, r.text()
    assert check('fn f() -> Str { return "{5:>07} {1.5:.2}" }', "verified").check_errors == []
