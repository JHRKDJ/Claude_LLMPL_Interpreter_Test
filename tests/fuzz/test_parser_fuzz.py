"""Parser and checker robustness on malformed input (RUN0 property testing):
seeded random mutations of real programs never raise a Python exception, every
diagnostic carries a registered stable code, and every primary span lies within the
file. Deep nesting is handled without crashing."""
import random

import pytest

from lang.diagnostics.codes import CODES
from lang.syntax.parser import parse_text
from tests.fuzz.corpus import program_corpus

CORPUS = program_corpus()
PIECES = ["{", "}", "(", ")", "[", "]", ",", "=>", "=", "+", "-", "\n", '"', "/*", "//", "try ", "catch ",
          "fn ", "let ", "match ", "if ", "else ", "await ", "spawn ", "select {", ":", ".", "|", "0", "x"]


def mutate(src: str, rng: random.Random) -> str:
    s = src
    for _ in range(rng.randrange(1, 4)):
        i = rng.randrange(0, len(s) + 1)
        k = rng.randrange(3)
        if k == 0 and s:
            j = min(len(s), i + rng.randrange(1, 6))
            s = s[:i] + s[j:]
        elif k == 1:
            s = s[:i] + rng.choice(PIECES) + s[i:]
        else:
            j = min(len(s), i + rng.randrange(1, 8))
            s = s[:i] + s[j:] + s[i:j]
    return s


def check_diags(text, diags):
    for d in diags:
        assert d.stable_code in CODES, d.stable_code
        if d.primary is not None and d.primary.span is not None and d.primary.span.file.text == text:
            assert 0 <= d.primary.span.start <= d.primary.span.end <= len(text), (d, text)


@pytest.mark.parametrize("seed", range(300))
def test_mutated_programs_never_crash_the_parser(seed):
    rng = random.Random(seed)
    src = mutate(CORPUS[seed % len(CORPUS)], rng)
    r = parse_text(src)
    check_diags(src, r.diagnostics)


@pytest.mark.parametrize("seed", range(60))
def test_mutated_programs_never_crash_the_checker(seed, tmp_path):
    from lang.tooling.driver import load_and_check
    rng = random.Random(10_000 + seed)
    src = mutate(CORPUS[(seed * 7) % len(CORPUS)], rng)
    p = tmp_path / "main.lang"
    p.write_text(src)
    co = load_and_check(p, rng.choice(["draft", "verified"]))
    check_diags(src, co.diagnostics)


@pytest.mark.parametrize("depth", [50, 200])
def test_deep_nesting(depth):
    src = "fn f() -> Int { return " + "(" * depth + "1" + ")" * depth + " }"
    r = parse_text(src)
    check_diags(src, r.diagnostics)
    src2 = "fn f() { " + "if true { " * depth + "}" * depth + " }"
    check_diags(src2, parse_text(src2).diagnostics)


def test_unclosed_nesting_reports_opener():
    src = "fn f() {\n if a {\n  while b {\n"
    r = parse_text(src)
    assert [d.stable_code for d in r.diagnostics][0] == "S.SYNTAX.UNCLOSED_DELIMITER"
