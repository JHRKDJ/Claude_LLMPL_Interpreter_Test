"""Exhaustiveness combinatorics (V3 3.3, 5.15.5; TEST-FUZZ-005). Random match arm lists
over `(Shape, Bool?)` — 12 values — are compared with brute-force ground truth:
the checker reports S.MATCH.NON_EXHAUSTIVE exactly when some value is uncovered by
unguarded arms (guards never count); every arm it calls unreachable really is
unreachable; at run time every value selects the first matching arm (differential
against a Python simulation), and an uncovered value abandons with the runtime
backstop."""
import itertools
import random

import pytest

from tests.helpers import check, run

SHAPES = [("Shape.A", "A"), ("Shape.B", "B"), ("Shape.C(flag: true)", ("C", True)), ("Shape.C(flag: false)", ("C", False))]
OPTS = [("Some(true)", True), ("Some(false)", False), ("null", None)]
VALUES = [(s, o) for s in SHAPES for o in OPTS]

SHAPE_PATS = {"Shape.A": {"A"}, "Shape.B": {"B"}, "Shape.C(true)": {("C", True)}, "Shape.C(false)": {("C", False)},
              "Shape.C(_)": {("C", True), ("C", False)}, "_": {"A", "B", ("C", True), ("C", False)}}
OPT_PATS = {"Some(true)": {True}, "Some(false)": {False}, "Some(_)": {True, False}, "None": {None},
            "_": {True, False, None}}

PRELUDE = """
enum Shape { A, B, C(flag: Bool) }
"""


def gen(rng):
    arms = []
    for _ in range(rng.randrange(1, 7)):
        sp = rng.choice(list(SHAPE_PATS))
        op = rng.choice(list(OPT_PATS))
        guarded = rng.random() < 0.2
        arms.append((sp, op, guarded))
    return arms


def covers(arm, v):
    sp, op, _ = arm
    return v[0][1] in SHAPE_PATS[sp] and v[1][1] in OPT_PATS[op]


def source(arms):
    lines = [f"        ({sp}, {op}){' if g' if gd else ''} => {i}" for i, (sp, op, gd) in enumerate(arms)]
    return PRELUDE + "fn f(s: Shape, o: Bool?, g: Bool) -> Int {\n    return match (s, o) {\n" + \
        "\n".join(lines) + "\n    }\n}\n"


@pytest.mark.parametrize("seed", range(80))
def test_exhaustiveness_matches_ground_truth(seed):
    rng = random.Random(seed)
    arms = gen(rng)
    src = source(arms)
    unguarded = [a for a in arms if not a[2]]
    uncovered = [v for v in VALUES if not any(covers(a, v) for a in unguarded)]
    r = check(src, "verified")
    codes = r.check_codes
    assert ("S.MATCH.NON_EXHAUSTIVE" in codes) == bool(uncovered), (src, uncovered, r.text())
    # soundness of unreachable-arm reports: each reported arm is covered by earlier unguarded arms
    for d in r.check:
        if d.stable_code == "S.MATCH.UNREACHABLE_ARM":
            line = d.primary.span.start_line_col[0]
            i = line - 5  # arm i is on source line 5 + i
            assert 0 <= i < len(arms)
            prev = [a for a in arms[:i] if not a[2]]
            assert all(any(covers(a, v) for a in prev) for v in VALUES if covers(arms[i], v)), (src, i)
    # runtime differential: first matching arm (guards evaluated with g)
    calls = []
    expected = []
    for (sv, sp), (ov, op) in VALUES:
        for g in (True, False):
            want = next((i for i, a in enumerate(arms) if covers(a, ((sv, sp), (ov, op))) and (not a[2] or g)), None)
            if want is None:
                continue
            calls.append(f"    print(f({sv}, {ov}, {str(g).lower()}))")
            expected.append(str(want))
    out = run(src + "fn main() {\n" + "\n".join(calls) + "\n}\n")
    assert out.lines == expected, (src, out.text())
    if uncovered:
        (sv, _), (ov, _) = uncovered[0]
        out = run(src + f"fn main() {{ print(f({sv}, {ov}, false)) }}\n")
        assert out.codes == ["A.MATCH.NO_ARM"], (src, out.text())
