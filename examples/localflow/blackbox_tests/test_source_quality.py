"""LocalFlow's source passes the toolchain's own gates: static check without errors in
verified mode (the manifest's mode, also requested explicitly here), and canonical
formatting."""
import subprocess
import sys

from harness import APP, ROOT

SRC = sorted((APP / "src").glob("*.lang"))


def lang(*args):
    return subprocess.run([sys.executable, "-m", "lang", *args], capture_output=True, text=True, cwd=str(ROOT),
                          env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"}, timeout=300)


def test_check_passes():
    r = lang("check", *[str(p) for p in SRC])
    assert r.returncode == 0, r.stderr[-3000:]


def test_verified_mode_accepts_the_program():
    r = lang("check", "--mode=verified", str(APP / "src" / "main.lang"))
    assert r.returncode == 0, r.stderr[-3000:]
    assert "0 error(s)" in r.stderr.splitlines()[-1]


def test_canonically_formatted():
    r = lang("format", "--check", *[str(p) for p in SRC])
    assert r.returncode == 0, r.stderr
