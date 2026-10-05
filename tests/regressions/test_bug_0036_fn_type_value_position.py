"""BUG-0036 (second audit, T16): a function type could not be written as a type argument
in value position — `MutableList[fn() -> Int]()`, `Channel[fn(Int) -> Int].unbounded()`
— because `fn(` always started a lambda (S.SYNTAX.UNEXPECTED_TOKEN)."""
from lang.format import format_source
from tests.helpers import check, run


SRC = """fn main() {
    let fs = MutableList[fn() -> Int]()
    fs.push(fn() => 1)
    let m = MutableMap[Str, fn(Int) -> Int throws Never]()
    m.set("double", fn(x: Int) -> Int { return x * 2 })
    let ch = Channel[fn(Int) -> Int].buffered(1)
    print(fs[0](), m["double"](4), [fn(x) => x + 1][0](1))
}
"""


def test_function_types_as_value_position_type_arguments():
    r = run(SRC)
    assert r.lines == ["1 8 2"], r.text()
    assert check(SRC, "verified").check_errors == []


def test_formatter_round_trips_them():
    out = format_source(SRC)
    assert "MutableList[fn() -> Int]()" in out and "Channel[fn(Int) -> Int].buffered(1)" in out
    assert format_source(out) == out


def test_element_annotation_enforced():
    r = run("fn main() { let fs = MutableList[fn() -> Int]()\n fs.push(3) }")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"] or "S.TYPE.STATIC_MISMATCH" in r.check_codes, r.text()
