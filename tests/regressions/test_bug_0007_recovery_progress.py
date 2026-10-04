"""BUG-0007: statement-level error recovery could stop on a stray closing delimiter
without consuming it; inside `select { ... }` (and other item loops) the parser then
re-parsed the same token forever, accumulating diagnostics until memory ran out
(found by parser fuzzing: `select {"outer")`). Recovery must always make progress."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CASES = [
    'fn main() {\n    defer print(select {"outer")\n    print("after")\n}',
    "fn f() { let r = match x { 1 => 2) }\n}",
    "record P { x: Int) }",
    "fn f() { let s = select { receive x from rx => 1 ] } }",
]


def test_recovery_terminates_on_stray_closers():
    code = ("import sys; sys.path.insert(0, %r)\n"
            "import resource; resource.setrlimit(resource.RLIMIT_AS, (700*1024**2, 700*1024**2))\n"
            "from lang.syntax.parser import parse_text\n"
            "for src in %r:\n"
            "    r = parse_text(src)\n"
            "    assert 0 < len(r.diagnostics) < 20, (src, len(r.diagnostics))\n"
            "print('ok')\n") % (str(ROOT), CASES)
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0 and p.stdout.strip() == "ok", p.stderr[-2000:]
