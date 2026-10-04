"""Contracts, predicates, old(), invariants, protocols (V3 5.10, 7.5, 7.8, 8.1, 8.8, 8.9)."""
from tests.helpers import ok, run


def test_requires_blames_caller():
    r = run("""fn withdraw(amount: Int) -> Int requires amount > 0 { return amount }
fn main() { withdraw(-5) }""")
    assert r.codes == ["A.CONTRACT.PRECONDITION_FAILED"]
    d = r.diag
    assert d.primary.span.text == "withdraw(-5)"
    assert d.values.get("amount") == "-5"
    assert any("precondition declared here" in l.message for l in d.secondary)


def test_ensures_with_result_and_old():
    r = ok("""
mutable record Account { balance: Int
    fn deposit(self, amount: Int) -> Int
        requires amount > 0
        ensures self.balance == old(self.balance) + amount
        ensures result == self.balance
    {
        self.balance += amount
        return self.balance
    }
}
fn main() { let a = Account(balance: 10)
 print(a.deposit(5)) }""")
    assert r.lines == ["15"]


def test_postcondition_failure_blames_implementation():
    r = run("""fn double(x: Int) -> Int ensures result == x * 2 { return x + 2 }
fn main() { print(double(1)) }""")
    assert r.codes == ["A.CONTRACT.POSTCONDITION_FAILED"]
    assert r.diag.primary.span.text == "result == x * 2"


def test_old_must_be_frozen():
    r = run("""
mutable record Box { items: MutableList[Int]
    fn add(self, x: Int) ensures self.items.length == old(self.items).length + 1 { self.items.push(x) } }
fn main() { let b = Box(items: MutableList[Int]())
 b.add(1) }""")
    assert r.codes == ["A.CONTRACT.EVALUATION_FAILED"]


def test_predicates_in_contracts():
    r = ok("""
predicate positive(x: Int) { x > 0 }
fn sq(x: Int) -> Int requires positive(x) ensures positive(result) { return x * x }
fn main() { print(sq(3)) }""")
    assert r.lines == ["9"]


def test_frozen_record_invariant_on_construction_and_with():
    r = run("""
record Range { lo: Int
 hi: Int
 invariant lo <= hi }
fn main() { let r = Range(lo: 1, hi: 5)
 let bad = r with { lo: 9 } }""")
    assert r.codes == ["A.CONTRACT.INVARIANT_VIOLATED"]


def test_mutable_invariant_checked_at_method_exit():
    r = run("""
mutable record Account { balance: Int
    invariant balance >= 0
    fn withdraw(self, amount: Int) { self.balance -= amount }
}
fn main() { let a = Account(balance: 5)
 a.withdraw(3)
 print(a.balance)
 a.withdraw(10) }""")
    assert r.lines == ["2"]
    assert r.codes == ["A.CONTRACT.INVARIANT_VIOLATED"]
    assert "on exit from `withdraw`" in r.diag.message


def test_invariant_may_break_temporarily_inside_method():
    r = ok("""
mutable record Pair { a: Int
 b: Int
    invariant a == b
    fn bump(self) { self.a += 1
 self.sync() }
    fn sync(self) { self.b = self.a }
}
fn main() { let p = Pair(a: 1, b: 1)
 p.bump()
 print(p.a, p.b) }""")
    assert r.lines == ["2 2"]


def test_invariant_fields_controlled():
    r = run("""
mutable record Account { balance: Int
 note: Str
 invariant balance >= 0 }
fn main() { let a = Account(balance: 1, note: "")
 a.note = "ok"
 a.balance = -1 }""")
    assert r.codes == ["A.CONTRACT.INVARIANT_FIELD_WRITE"]


def test_invariant_checked_after_exception_exit():
    r = run("""
error Nope { }
mutable record Account { balance: Int
    invariant balance >= 0
    fn risky(self) throws Nope { self.balance = -1
 throw Nope() }
}
fn main() { let a = Account(balance: 1)
 try a.risky() catch Nope => print("caught") }""")
    assert r.codes == ["A.CONTRACT.INVARIANT_VIOLATED"]
    assert any("pending exception" in n.message for n in r.diag.notes)
    assert r.stdout == ""


def test_cleanup_runs_before_postcondition():
    r = ok("""
mutable record Log { n: Int }
fn work(log: Log) -> Int ensures log.n == 2 {
    defer log.n += 1
    log.n += 1
    return log.n
}
fn main() { let l = Log(n: 0)
 print(work(l), l.n) }""")
    assert r.lines == ["1 2"]


def test_protocol_shape_check_at_boundary():
    r = run("""
protocol Named { fn name(self) -> Str }
record Dog { fn name(self) -> Str { return "dog" } }
record Rock { }
fn greet(n: Named) -> Str { return n.name() }
fn main() { print(greet(Dog()))
 print(greet(Rock())) }""")
    assert r.lines == ["dog"]
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    assert "missing method `name`" in r.diag.message


def test_protocol_arity_mismatch_rejected():
    r = run("""
protocol Scaler { fn scale(self, k: Int) -> Int }
record Bad { fn scale(self) -> Int { return 1 } }
fn apply(s: Scaler) -> Int { return s.scale(2) }
fn main() { apply(Bad()) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


def test_protocol_effect_compatibility():
    r = run("""
error Boom { }
protocol Loader { fn load(self) -> Str }
record Risky { fn load(self) -> Str throws Boom { throw Boom() } }
fn apply(l: Loader) -> Str { return l.load() }
fn main() { apply(Risky()) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    assert "Boom" in r.diag.message


def test_protocol_contracts_inherited_on_every_call():
    r = run("""
protocol Sized { fn size(self) -> Int ensures result >= 0 }
record Weird { fn size(self) -> Int { return -1 } }
fn main() {
    let w = Weird()
    print(w.size())
}""")
    assert r.codes == ["A.CONTRACT.POSTCONDITION_FAILED"]
    assert "inherited from protocol Sized" in r.diag.message


def test_protocol_preconditions_inherited():
    r = run("""
protocol Store { fn put(self, n: Int) requires n > 0 }
record Mem { fn put(self, n: Int) { print("put {n}") } }
fn main() { let m = Mem()
 m.put(1)
 m.put(0) }""")
    assert r.lines == ["put 1"]
    assert r.codes == ["A.CONTRACT.PRECONDITION_FAILED"]


def test_added_precondition_means_nonconforming():
    r = run("""
protocol Store { fn put(self, n: Int) }
record Picky { fn put(self, n: Int) requires n > 100 { } }
fn apply(s: Store) { s.put(1) }
fn main() { apply(Picky()) }""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    assert "precondition" in r.diag.message


def test_implementation_postconditions_supplement():
    r = run("""
protocol Counter { fn next(self) -> Int ensures result > 0 }
record Odd { fn next(self) -> Int ensures result % 2 == 1 { return 2 } }
fn main() { print(Odd().next()) }""")
    assert r.codes == ["A.CONTRACT.POSTCONDITION_FAILED"]
    assert "result % 2 == 1" in r.diag.message
