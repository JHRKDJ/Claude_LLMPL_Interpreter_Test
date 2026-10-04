"""Functions, bindings, closures, records, variants, patterns (V3 5.1, 5.4, 6.3, 6.5, 7.3, 7.4)."""
from tests.helpers import ok, run


def test_let_is_reassignable_const_is_not():
    r = ok("""fn main() { let x = 1
 x = 2
 print(x) }""")
    assert r.lines == ["2"]
    r = run("""fn main() { const x = 1
 x = 2 }""")
    assert "S.NAME.CONST_REASSIGN" in r.check_errors


def test_uninitialised_binding_static_and_runtime():
    r = run("""fn main() {
    let x: Int
    if 1 > 2 { x = 3 }
    print(x)
}""")
    assert "S.NAME.UNINITIALISED" in r.check_warnings  # draft: warning, runtime check fills the gap
    assert r.codes == ["A.BINDING.UNINITIALISED"]
    r = ok("""fn main() {
    let x: Int
    if 1 > 2 { x = 3 } else { x = 4 }
    print(x)
}""")
    assert r.lines == ["4"]


def test_uninitialised_is_distinct_from_none():
    r = ok("""fn main() { let x: Int? = null
 print(x, x is None) }""")
    assert r.lines == ["None true"]


def test_duplicate_let_in_same_scope_rejected():
    r = run("""fn main() { let x = 1
 let x = 2 }""")
    assert "S.NAME.DUPLICATE" in r.check_errors


def test_shadowing_in_nested_scope_allowed():
    r = ok("""fn main() { let x = 1
 if true { let x = 2
 print(x) }
 print(x) }""")
    assert r.lines == ["2", "1"]


def test_named_and_default_arguments():
    r = ok("""
fn f(a: Int, b: Int = 10, c: Int = 100) -> Int { return a + b + c }
fn main() { print(f(1), f(1, 2), f(1, c: 3), f(a: 5, b: 0, c: 0)) }""")
    assert r.lines == ["111 103 14 5"]


def test_arity_error_reports_declaration():
    r = run("""fn f(a: Int) -> Int { return a }
fn main() { f(1, 2) }""")
    assert r.codes == ["A.TYPE.ARITY"]
    assert any(l.message == "declared here" for l in r.diag.secondary)


def test_function_bodies_need_explicit_return():
    r = ok("""fn f() { 42 }
fn main() { print(f()) }""")
    assert r.lines == ["()"]


def test_expression_valued_blocks():
    r = ok("""fn main() {
    let a = if 1 < 2 { "yes" } else { "no" }
    let b = match 3 { 1 => "one"
 3 => "three"
 _ => "other" }
    print(a, b)
}""")
    assert r.lines == ["yes three"]


def test_closures_capture_and_nonlocal():
    r = ok("""fn main() {
    let count = 0
    let inc = fn() {
        nonlocal count
        count = count + 1
        return count
    }
    inc()
    inc()
    print(count)
}""")
    assert r.lines == ["2"]


def test_captured_reassignment_requires_nonlocal():
    r = run("""fn main() {
    let count = 0
    let inc = fn() { count = count + 1 }
}""")
    assert "S.NAME.CAPTURED_REASSIGN" in r.check_errors


def test_left_to_right_evaluation():
    r = ok("""
fn t(tag: Str, v: Int) -> Int { print(tag)
 return v }
fn add(a: Int, b: Int) -> Int { return a + b }
fn main() { print(add(t("a", 1), t("b", 2)) + t("c", 3)) }""")
    assert r.lines == ["a", "b", "c", "6"]


def test_records_frozen_structural_equality():
    r = ok("""
record P { x: Int
 y: Int }
fn main() { print(P(x: 1, y: 2) == P(x: 1, y: 2), P(x: 1, y: 2) == P(x: 1, y: 3)) }""")
    assert r.lines == ["true false"]


def test_frozen_record_field_assignment_rejected():
    r = run("""
record P { x: Int }
fn main() { let p = P(x: 1)
 p.x = 2 }""")
    assert r.codes == ["A.TYPE.FROZEN_MUTATION"]
    assert "with" in r.text()


def test_frozen_record_requires_frozen_fields():
    r = run("""
record Holder { items: Dyn }
fn main() { let h = Holder(items: MutableList.of(1)) }""")
    assert r.codes == ["A.TYPE.FROZEN_MUTATION"]


def test_mutable_records_identity_bearing():
    r = ok("""
mutable record Counter { n: Int }
fn bump(c: Counter) { c.n += 1 }
fn main() {
    let a = Counter(n: 0)
    let b = a
    bump(b)
    print(a.n, a == b, a == Counter(n: 1))
}""")
    assert r.lines == ["1 true false"]


def test_with_update_creates_new_value():
    r = ok("""
record User { name: Str
 age: Int }
fn main() { let u = User(name: "a", age: 1)
 let v = u with { age: 2 }
 print(u.age, v.age, v.name) }""")
    assert r.lines == ["1 2 a"]


def test_record_annotation_is_nominal():
    r = run("""
record A { x: Int }
record B { x: Int }
fn f(a: A) -> Int { return a.x }
fn main() { f(B(x: 1)) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    d = r.diag
    assert d.expected == "A" and d.found == "B"
    assert any("relies on this annotation" in l.message for l in d.secondary)


def test_dynamic_mismatch_reports_value_origin():
    r = run("""
record Account { balance: Int }
fn balance(account: Account) -> Int { return account.balance }
fn load() -> Dyn { return 5 }
fn main() {
    let value = load()
    let amount = balance(value)
}""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    labels = [l.message for l in r.diag.secondary]
    assert any("originated" in m for m in labels), labels


def test_return_annotation_checked():
    r = run("""fn f() -> Int { return "x" }
fn main() { f() }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


def test_methods_and_associated_functions():
    r = ok("""
record Config { level: Int
    fn defaults() -> Config { return Config(level: 1) }
    fn bumped(self) -> Config { return self with { level: self.level + 1 } }
}
fn main() { print(Config.defaults().bumped().level) }""")
    assert r.lines == ["2"]


def test_enums_exhaustive_runtime_backstop():
    r = run("""
enum Color { Red
 Green
 Blue }
fn name(c: Color) -> Str {
    return match c { Color.Red => "r"
 Color.Green => "g" }
}
fn main() { print(name(Color.Blue)) }""")
    assert r.codes == ["A.MATCH.NO_ARM"]


def test_variant_payloads_named_and_positional():
    r = ok("""
enum Shape { Circle(radius: Float)
 Rect(w: Float, h: Float) }
fn area(s: Shape) -> Float {
    return match s {
        Shape.Circle(radius: r) => r * r
        Shape.Rect(w, h) => w * h
    }
}
fn main() { print(area(Shape.Circle(2.0)), area(Shape.Rect(w: 2.0, h: 5.0))) }""")
    assert r.lines == ["4.0 10.0"]


def test_bare_uppercase_pattern_is_rejected():
    r = run("""
enum E { A
 B }
fn main() { match E.A { A => print(1)
 _ => print(2) } }""")
    assert "S.MATCH.INVALID_PATTERN" in r.check_errors


def test_match_guards_and_or_patterns_and_literals():
    r = ok("""fn main() {
    for x in [0, 1, 5, 12] {
        let s = match x {
            0 | 1 => "small"
            n if n > 10 => "big {n}"
            _ => "mid"
        }
        print(s)
    }
}""")
    assert r.lines == ["small", "small", "mid", "big 12"]


def test_literal_patterns_type_exact():
    r = ok("""fn main() { let v: Dyn = 1.0
 print(match v { 1 => "int"
 1.0 => "float"
 _ => "other" }) }""")
    assert r.lines == ["float"]


def test_type_patterns_on_dyn():
    r = ok("""fn describe(v: Dyn) -> Str {
    return match v {
        n: Int => "int {n}"
        s: Str => "str {s}"
        _ => "other"
    }
}
fn main() { print(describe(3), describe("x"), describe(1.5)) }""")
    assert r.lines == ["int 3 str x other"]


def test_option_and_null():
    r = ok("""fn find(xs: List[Int], t: Int) -> Int? {
    for x in xs { if x == t { return Some(x) } }
    return null
}
fn main() { print(find([1, 2], 2), find([1, 2], 3), find([1], 1).unwrapOr(0)) }""")
    assert r.lines == ["Some(2) None 1"]


def test_option_annotation_checks_payload():
    r = run("""fn f(x: Int?) -> Int { return 1 }
fn main() { f(Some("s")) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


def test_record_patterns():
    r = ok("""
record P { x: Int
 y: Int }
fn main() { match P(x: 1, y: 2) { P(x: 1, y: y) => print("y={y}")
 _ => print("no") } }""")
    assert r.lines == ["y=2"]


def test_as_narrowing():
    r = ok("""fn main() { let v: Dyn = [1, 2]
 let xs = v as List[Int]
 print(xs.length) }""")
    assert r.lines == ["2"]
    r = run("""fn main() { let v: Dyn = "x"
 let n = v as Int }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


def test_generic_function_and_record():
    r = ok("""
record Box[T] { value: T }
fn first[T](xs: List[T]) -> T? { return xs.first() }
fn main() { print(Box[Int](value: 3).value, first([7, 8])) }""")
    assert r.lines == ["3 Some(7)"]


def test_module_constants_frozen():
    r = ok("""const LIMIT = 10
const NAMES = ["a", "b"]
fn main() { print(LIMIT, NAMES) }""")
    assert r.lines == ['10 ["a", "b"]']
    r = run("""const STATE = MutableList.of(1)
fn main() { print(1) }""")
    assert r.codes == ["S.MODULE.MUTABLE_GLOBAL"]


def test_module_level_let_rejected():
    r = run("""let counter = 0
fn main() { }""")
    assert "S.MODULE.MUTABLE_GLOBAL" in r.check_errors


def test_unresolved_name_suggests_import():
    r = run("""fn main() { print(helper(1)) }""",
            files={"util.lang": "pub fn helper(x: Int) -> Int { return x }"})
    assert "S.NAME.UNRESOLVED" in r.check_errors
    d = [d for d in r.check if d.stable_code == "S.NAME.UNRESOLVED"][0]
    assert d.fixes and "import util.{helper}" in d.fixes[0].edits[0].replacement


def test_imports_and_exports():
    r = ok("""import util.{helper}
import util
fn main() { print(helper(2), util.helper(3)) }""",
           files={"util.lang": "pub fn helper(x: Int) -> Int { return x * 10 }\nfn secret() { }"})
    assert r.lines == ["20 30"]
    r = run("""import util.{secret}
fn main() { }""", files={"util.lang": "fn secret() { }"})
    assert "S.NAME.PRIVATE" in r.check_errors


def test_unknown_package_import_is_not_installed():
    r = run("""import leftpad.core
fn main() { }""")
    assert "S.MODULE.UNKNOWN_DEPENDENCY" in r.check_errors


def test_const_init_cycle_detected():
    r = run("""const A = B + 1
const B = A + 1
fn main() { print(A) }""")
    assert r.codes == ["S.MODULE.INIT_CYCLE"]
    assert "A" in r.diag.message and "B" in r.diag.message


def test_directory_module():
    r = ok("""import pkg.{f}
fn main() { print(f()) }""", files={"pkg/mod.lang": "pub fn f() -> Int { return 7 }"})
    assert r.lines == ["7"]


def test_main_return_code_and_args():
    r = run("""fn main(args: List[Str]) -> Int { print(args)
 return 4 }""", argv=["x", "y"])
    assert r.exit_code == 4 and r.lines == ['["x", "y"]']


def test_stack_overflow_is_abandonment():
    r = run("""fn f(n: Int) -> Int { return f(n + 1) }
fn main() { f(0) }""")
    assert r.codes == ["A.RUNTIME.STACK_OVERFLOW"]
