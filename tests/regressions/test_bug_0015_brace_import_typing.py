"""BUG-0015 (found by the coverage reread while re-checking LocalFlow in verified
mode): a function imported by name, `import model.{isFinal}`, was typed `Dyn` by the
checker, so every call was a false `S.TYPE.DYNAMIC_CALL` error in verified mode
(10 of them in LocalFlow), and its parameter/return types and effects were not
checked at all. Qualified use (`import model` + `model.isFinal(...)`) was typed."""
from tests.helpers import check

MODEL = {"model.lang": """
pub error Bad { }
pub fn isFinal(s: Int) -> Bool { return s > 0 }
pub fn risky(s: Int) -> Int throws Bad { if s < 0 { throw Bad() }
    return s }
pub record Box { v: Int }
"""}


def test_named_import_call_is_typed():
    r = check("import model.{isFinal}\npub fn f() -> Bool { return isFinal(1) }\n", "verified", files=MODEL)
    assert r.check == [], r.text()


def test_named_import_checks_arguments_and_effects():
    r = check("""import model.{isFinal, risky, Bad}
pub fn f() -> Bool { return isFinal("x") }
pub fn g() -> Int { return try risky(1) }
""", "verified", files=MODEL)
    codes = r.check_errors
    assert "S.TYPE.STATIC_MISMATCH" in codes and "S.EFFECT.UNDECLARED_THROWS" in codes
    assert "S.TYPE.DYNAMIC_CALL" not in codes


def test_named_import_inside_lambda_and_cycle():
    files = dict(MODEL)
    files["jobs.lang"] = "import main\npub fn g() -> Int { return 1 }\n"
    r = check("""import model.{isFinal}
import jobs.{g}
pub fn f(xs: List[Int]) -> Bool { return xs.all(fn(j) => isFinal(j + g())) }
""", "verified", files=files)
    assert r.check == [], r.text()


def test_qualified_import_still_typed():
    r = check("import model\npub fn f() -> Bool { return model.isFinal(1) }\n", "verified", files=MODEL)
    assert r.check == [], r.text()
