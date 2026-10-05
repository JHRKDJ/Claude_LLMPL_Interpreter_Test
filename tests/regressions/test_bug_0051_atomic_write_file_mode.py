"""BUG-0051 (found by the LocalFlow final-review harness, which now compares file
modes): `fs.openAtomicWrite` created its temporary file with `mkstemp`, so the committed
file had mode 0600 while `fs.writeText`/`openWrite` produce the ordinary umask default
(0644 under umask 022). An atomic write must be observably the same file as a plain
write, and replacing an existing file keeps that file's permissions."""
import os
import stat
import tempfile
from pathlib import Path

from tests.helpers import run


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


SRC = """
import std.fs

fn main(args: List[Str]) throws IOFailure, FileNotFound, PermissionDenied {{
    let dir = args[0]
    try fs.writeText(fs.join(dir, "plain.txt"), "x")
    try use out = try fs.openAtomicWrite(fs.join(dir, "{name}")) {{
        try out.write("y")
    }}
}}
"""


def test_atomic_write_has_the_same_mode_as_a_plain_write():
    d = Path(tempfile.mkdtemp(prefix="bug0051-"))
    r = run(SRC.format(name="atomic.txt"), argv=[str(d)])
    assert not r.check_errors and not r.diags, r.text()
    assert (d / "atomic.txt").read_text() == "y"
    assert _mode(d / "atomic.txt") == _mode(d / "plain.txt")


def test_atomic_replace_keeps_the_existing_mode():
    d = Path(tempfile.mkdtemp(prefix="bug0051-"))
    (d / "existing.txt").write_text("old")
    os.chmod(d / "existing.txt", 0o640)
    r = run(SRC.format(name="existing.txt"), argv=[str(d)])
    assert not r.check_errors and not r.diags, r.text()
    assert (d / "existing.txt").read_text() == "y"
    assert _mode(d / "existing.txt") == 0o640
