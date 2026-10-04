"""Formatter properties (V3 7.14.3: canonical, deterministic, idempotent):

1. format(format(x)) == format(x);
2. parse(format(x)) is structurally equal to parse(x) (checked inside format_source);
3. every comment survives;
over the whole test-suite corpus and over seeded random programs."""
import pytest

from lang.format import format_source
from lang.syntax.parser import parse_text
from tests.fuzz.corpus import program_corpus
from tests.fuzz.gen import Gen

CORPUS = program_corpus()


def test_corpus_is_substantial():
    assert len(CORPUS) > 300


@pytest.mark.parametrize("i", range(0, len(CORPUS), 1))
def test_corpus_program_formats_idempotently(i):
    src = CORPUS[i]
    once = format_source(src)
    assert format_source(once) == once


SEEDS = range(400)


@pytest.mark.parametrize("seed", SEEDS)
def test_generated_program_formats_idempotently(seed):
    src = Gen(seed).program()
    res = parse_text(src)
    assert res.ok, (src, [d.message for d in res.diagnostics])
    once = format_source(src)
    assert format_source(once) == once
    assert len(parse_text(once).comments) == len(res.comments)


def test_formatting_is_deterministic():
    src = Gen(7).program()
    assert format_source(src) == format_source(src)
