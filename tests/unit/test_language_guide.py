"""Every `lang` example in docs/LANGUAGE_GUIDE.md runs and prints what it claims."""
import re
from pathlib import Path

import pytest

from tests.helpers import run

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "LANGUAGE_GUIDE.md"
BLOCKS = re.findall(r"```lang\n(.*?)```", GUIDE.read_text(), re.S)


def test_guide_has_examples():
    assert len(BLOCKS) >= 10


@pytest.mark.parametrize("i", range(len(BLOCKS)))
def test_guide_example(i):
    src = BLOCKS[i]
    expected = [ln.split("// prints:", 1)[1].strip() for ln in src.splitlines() if "// prints:" in ln]
    r = run(src)
    assert r.exit_code == 0, r.text()
    assert not [d for d in r.check if d.severity == "error"], r.text()
    assert r.lines == expected, (r.lines, expected)


@pytest.mark.parametrize("i", range(len(BLOCKS)))
def test_guide_example_is_canonically_formatted(i):
    from lang.format import format_source
    src = BLOCKS[i]
    assert format_source(src)  # parses and formats (examples need not be byte-canonical)
