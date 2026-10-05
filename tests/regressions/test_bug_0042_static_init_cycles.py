"""BUG-0042 (second audit, T11): `lang check --mode=verified` accepted programs whose
module constants initialise cyclically (directly, through a function, or across
modules); the cycle surfaced only at link time with a *static* code (S.MODULE.INIT_CYCLE)
but abandonment exit status 3. V3 6.11: initialisation cycles are rejected with a full
cycle diagnostic. Now: definite cycles are static errors; link-time detection (the
backstop) uses A.* codes consistent with its exit status."""
from tests.helpers import check, run


def test_direct_cycle_is_a_static_error_in_both_modes():
    src = "const A = B + 1\nconst B = A + 1\nfn main() { print(A) }"
    for mode in ("draft", "verified"):
        r = check(src, mode)
        assert "S.MODULE.INIT_CYCLE" in r.check_errors, (mode, r.text())
    d = [x for x in check(src, "verified").check if x.stable_code == "S.MODULE.INIT_CYCLE"][0]
    assert "A" in d.message and "B" in d.message


def test_cycle_through_a_function_reported_in_verified():
    src = "fn getB() -> Int { return B }\nconst A = getB() + 1\nconst B = A + 1\nfn main() { print(A) }"
    r = check(src, "verified")
    assert "S.MODULE.INIT_CYCLE" in r.check_errors, r.text()
    assert "getB" in [x for x in r.check if x.stable_code == "S.MODULE.INIT_CYCLE"][0].message


def test_cycle_across_modules():
    r = check("import m.{X}\npub const Y = X + 1\nfn main() { print(Y) }", "verified",
              files={"m.lang": "import main.{Y}\npub const X = Y + 1\n"})
    assert "S.MODULE.INIT_CYCLE" in r.check_errors, r.text()


def test_runtime_backstop_uses_abandonment_code():
    from tests.helpers import run_unchecked
    r = run_unchecked("const A = B + 1\nconst B = A + 1\nfn main() { print(A) }")
    assert r.codes == ["A.MODULE.INIT_CYCLE"] and r.exit_code == 3, r.codes


def test_acyclic_constants_unaffected():
    r = run("fn twice(n: Int) -> Int { return n * 2 }\nconst A = twice(B)\nconst B = 4\nfn main() { print(A) }")
    assert r.lines == ["8"], r.text()
