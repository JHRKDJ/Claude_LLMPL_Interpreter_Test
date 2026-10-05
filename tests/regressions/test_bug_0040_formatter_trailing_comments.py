"""BUG-0040 (second audit, T09): the formatter refused ordinary code with a trailing
comment after an opening brace, a match header, an `else {`, a map entry, or between
contract clauses ("internal formatter error: output changes the program
(module.comments[0].own_line: False != True)"): its self-verification compared the
comment's placement flag, so canonically moving a trailing comment to its own line was
treated as a semantic change (V3 6.1/7.14.3: the formatter is canonical and authoritative)."""
import pytest

from lang.format import format_source
from lang.syntax.parser import parse_text

CASES = {
    "after_brace": "fn main() {\n    if true { // c\n        print(1)\n    }\n}\n",
    "record_brace": "record R { // r\n    x: Int\n}\n",
    "else_brace": "fn main() {\n    if true {\n        print(1)\n    } else { // d\n        print(2)\n    }\n}\n",
    "match_header": "fn main() {\n    let z = match 1 { // c\n        1 => 2 // arm\n        _ => 3\n    }\n    print(z)\n}\n",
    "map_entry": 'fn main() {\n    let m = {\n        "a": 1, // first\n        "b": 2,\n    }\n    print(m)\n}\n',
    "contract_clauses": "fn f(x: Int) -> Int\n    // explain precondition\n    requires x > 0\n"
                        "    ensures result > 0 // positive\n{\n    return x\n}\n",
    "call_args": "fn foo(a, b) { return a }\nfn main() {\n    print(foo(1, // c\n        2))\n}\n",
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_trailing_comments_are_formatted_and_kept(name):
    src = CASES[name]
    out = format_source(src)
    texts = [c.text for c in parse_text(src).comments]
    assert [c.text for c in parse_text(out).comments] == texts
    assert format_source(out) == out  # idempotent


def test_long_parameter_lists_wrap_and_reparse():
    src = ("pub async fn workerPool[J, R](n: Int, jobs: ReceivePort[J], results: SendPort[R], "
           "work: fn(J) -> R) throws ChannelClosed, AggregateException {\n    return\n}\n")
    out = format_source(src)
    assert max(len(line) for line in out.splitlines()) <= 100
    assert "    work: fn(J) -> R,\n) throws ChannelClosed, AggregateException {" in out
    assert format_source(out) == out


def test_shipped_stdlib_is_canonical():
    from pathlib import Path
    from lang.modules.loader import STDLIB_DIR
    for p in STDLIB_DIR.glob("*.lang"):
        text = p.read_text()
        assert format_source(text) == text, p.name
