"""BUG-0031 (second audit, C09/F9): the provider yield-count check was wrong both ways.
False negatives: `if flag { return }` before the yield (return treated like throw), a
match arm without a yield, a yield inside one branch of an `if` initialiser. False
positives: a yield in every match arm ("found 2"), `while true { yield v; break }`.
V3 5.5.3: exactly one yield on every normally completing path."""
import pytest

from tests.helpers import check

BAD = {
    "return_before_yield": "resource fn p(flag: Bool) yields Int { if flag { return }\n yield 1 }",
    "match_arm_without_yield": "enum K { A, B }\nresource fn p(k: K) yields Int { match k { K.A => { yield 1 }\n K.B => { print(1) } } }",
    "yield_in_if_initialiser": "resource fn p(flag: Bool) yields Int { let v = if flag { yield 1 } else { 0 } }",
    "two_yields": "resource fn p() yields Int { yield 1\n yield 2 }",
    "loop_may_yield_many": "resource fn p(n: Int) yields Int { for i in 0..n { yield i } }",
    "no_yield": "resource fn p() yields Int { print(1) }",
}
GOOD = {
    "yield_in_every_arm": "enum K { A, B }\nresource fn p(k: K) yields Int { match k { K.A => { yield 1 }\n K.B => { yield 2 } } }",
    "while_true_yield_break": "resource fn p() yields Int { while true { yield 1\n break } }",
    "throw_before_yield": "error E { }\nresource fn p(ok: Bool) yields Int throws E { if !ok { throw E() }\n yield 1 }",
    "return_after_yield": "resource fn p(x: Bool) yields Int { let e = yield 1\n if x { return }\n print(2) }",
    "plain": "resource fn p() yields Int { let e = yield 1 }",
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_wrong_yield_counts_reported(name):
    assert "S.RESOURCE.YIELD_COUNT" in check(BAD[name], "verified").check_errors, name


@pytest.mark.parametrize("name", sorted(GOOD))
def test_correct_providers_accepted(name):
    r = check(GOOD[name], "verified")
    assert "S.RESOURCE.YIELD_COUNT" not in r.check_codes, (name, r.text())
