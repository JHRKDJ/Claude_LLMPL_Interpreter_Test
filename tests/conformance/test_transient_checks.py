"""Transient checking of nested typed contents (V3 5.3.7, 5.3.12, 7.6.3; IMPL-004).

A boundary check of `List[Int]` is shallow (the outer list); typed code that *reads*
an element relies on the annotation, so the element is checked at the read and a
failure names both the use site and the relied-upon annotation."""
from tests.helpers import ok, run

JSON = "import std.json\n"


def _secondary_texts(d):
    return [l.span.text for l in d.secondary]


def test_for_loop_element_checked_against_param_annotation():
    r = run(JSON + """
fn total(xs: List[Int]) -> Int { let s = 0
 for x in xs { s = s + x }
 return s }
fn main() throws JsonError { print(total(try json.parse("[1, \\"two\\", 3]"))) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"], r.text()
    d = r.diag
    assert d.primary.span.text == "xs"
    assert "List[Int]" in _secondary_texts(d)
    assert d.found == "Str"


def test_index_read_checked():
    r = run(JSON + """
fn first(xs: List[Int]) -> Int { return xs[0] + 1 }
fn main() throws JsonError { print(first(try json.parse("[\\"a\\"]"))) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    assert r.diag.primary.span.text == "xs[0]"


def test_map_value_read_checked():
    r = run(JSON + """
fn port(cfg: Map[Str, Int]) -> Int { return cfg["port"] }
fn main() throws JsonError { print(port(try json.parse("\\{\\"port\\": \\"80\\"\\}"))) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    assert "Map[Str, Int]" in _secondary_texts(r.diag)


def test_payload_binding_checked():
    r = run(JSON + """
fn head(xs: List[Int]) -> Int { return match xs.get(0) { Some(v) => v, None => 0 } }
fn main() throws JsonError { print(head(try json.parse("[true]"))) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"], r.text()


def test_record_field_annotation_relied_upon():
    r = run(JSON + """
record Batch { items: List[Int] }
fn sum(b: Batch) -> Int { let s = 0
 for x in b.items { s = s + x }
 return s }
fn main() throws JsonError { print(sum(Batch(items: try json.parse("[1, 2.5]")))) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    assert any("items" in t for t in _secondary_texts(r.diag))


def test_well_typed_contents_pass_and_untyped_code_is_not_checked():
    r = ok(JSON + """
fn total(xs: List[Int]) -> Int { let s = 0
 for x in xs { s = s + x }
 return s }
fn loose(xs) { let out = []
 for x in xs { out = out.appended(x) }
 return out.length }
fn main() throws JsonError {
    print(total(try json.parse("[1, 2, 3]")))
    print(loose(try json.parse("[1, \\"a\\", true]")))
}""")
    assert r.lines == ["6", "3"]


def test_boundary_check_is_shallow():
    # passing the list does not traverse it: only the element actually read fails
    r = run(JSON + """
fn second(xs: List[Int]) -> Int { return xs[1] }
fn main() throws JsonError { print(second(try json.parse("[\\"bad\\", 2]"))) }""")
    assert r.exit_code == 0 and r.lines == ["2"]
