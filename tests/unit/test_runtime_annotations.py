"""The runtime honours annotations recorded by the static checker."""
import io
import tempfile
from pathlib import Path

from lang.runtime.interp import Interpreter, RunOptions
from lang.syntax import ast as A
from lang.tooling.driver import load_and_check

SRC = """
error Bad { }
error Other { }
fn f(x: Int) -> Int throws Bad { if x > 0 { throw Bad() }
 return 0 }
fn main() {
    print(try f(1) else 7)
}"""


def _prepare(src):
    d = Path(tempfile.mkdtemp(prefix="langann-"))
    p = d / "main.lang"
    p.write_text(src)
    co = load_and_check(p, "verified")
    assert not co.blocking
    return co


def _try_nodes(co):
    out = []
    for ms in co.program.modules.values():
        if ms.ast is not None:
            out += [n for n in A.walk(ms.ast) if isinstance(n, A.Try)]
    return out


def _run(co):
    out = io.StringIO()
    r = Interpreter(co.program, RunOptions(clock="virtual", stdout=out, stderr=io.StringIO())).run_main()
    return r, out.getvalue()


def test_checker_records_fallback_type():
    co = _prepare(SRC)
    (t,) = _try_nodes(co)
    assert t.ann["fallback_qual"] == "main.Bad"
    r, out = _run(co)
    assert r.exit_code == 0 and out == "7\n"


def test_fallback_only_handles_the_proved_type():
    # if the proved type differs from what is thrown (defence in depth), the error propagates
    co = _prepare(SRC)
    (t,) = _try_nodes(co)
    t.ann["fallback_qual"] = "main.Other"
    r, out = _run(co)
    assert r.exit_code == 1 and r.outcome == "threw" and out == ""
