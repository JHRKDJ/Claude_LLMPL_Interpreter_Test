"""Standard library (V3 6.14, 7.15): channel patterns, ordinary protocols, regex,
datetime, JSON and math. `std.chan` and `std.order` are written in the language
itself (lang/stdlib/*.lang); regex/datetime/json/math are native modules."""
from pathlib import Path

import pytest

from lang.modules.loader import NATIVE_STD, STDLIB_DIR
from lang.runtime.builtins.registry import MODULES, load_all
from tests.helpers import check, ok, run


def test_every_std_module_has_exports():
    load_all()
    for m in NATIVE_STD:
        assert MODULES.get(m), f"{m} is listed as native but registers nothing"


@pytest.mark.parametrize("path", sorted(STDLIB_DIR.glob("*.lang")), ids=lambda p: p.stem)
def test_language_stdlib_modules_are_clean_in_verified_mode(path: Path):
    r = check(path.read_text(), "verified")
    assert r.check == [], r.text()


def test_chan_fan_in_drain_request_response_worker_pool():
    r = ok("""
import std.chan
async fn main() throws ChannelClosed, AggregateException {
    let a = Channel[Int].buffered(4)
    let b = Channel[Int].buffered(4)
    let merged = Channel[Int].unbounded()
    let ta = a.sender()
    let tb = b.sender()
    parallel {
        spawn chan.fanIn([a.receiver(), b.receiver()], merged.sender())
        for i in 0..3 { try await ta.send(i)
            try await tb.send(10 + i) }
        a.close()
        b.close()
    }
    merged.close()
    let all = await chan.drain(merged.receiver())
    print(all.sorted(), all.filter(fn(x) => x < 10))
    let reqs = Channel[chan.Request[Int, Str]].rendezvous()
    let server = reqs.sender()
    parallel {
        spawn chan.serve(reqs.receiver(), fn(q: Int) => "answer {q * 2}")
        print(try await chan.ask(server, 1, 21))
        reqs.close()
    }
    let jobs = Channel[Int].buffered(8)
    let res = Channel[Int].unbounded()
    let jt = jobs.sender()
    parallel {
        spawn chan.workerPool(3, jobs.receiver(), res.sender(), fn(j: Int) => j * j)
        for i in 1..=5 { try await jt.send(i) }
        jobs.close()
    }
    res.close()
    print((await chan.drain(res.receiver())).sorted())
}""", mode="verified")
    # per-input order is preserved by fan-in; every message delivered exactly once
    assert r.lines == ["[0, 1, 2, 10, 11, 12] [0, 1, 2]", "answer 42", "[1, 4, 9, 16, 25]"]


def test_chan_helpers_are_schedule_independent():
    src = """
import std.chan
async fn main() throws ChannelClosed, AggregateException {
    let jobs = Channel[Int].buffered(2)
    let res = Channel[Int].unbounded()
    let jt = jobs.sender()
    parallel {
        spawn chan.workerPool(4, jobs.receiver(), res.sender(), fn(j: Int) => j + 100)
        for i in 0..20 { try await jt.send(i) }
        jobs.close()
    }
    res.close()
    let got = await chan.drain(res.receiver())
    print(got.length, got.sorted() == (0..20).toList().map(fn(i) => i + 100))
}"""
    for seed in (1, 2, 3, 4):
        assert run(src, schedule="random", seed=seed).lines == ["20 true"]


def test_order_protocols_structural():
    r = ok("""
import std.order
record Version {
    major: Int
    minor: Int
    fn compareTo(self, other: Dyn) -> Int {
        let o = other as Version
        if self.major != o.major { return self.major - o.major }
        return self.minor - o.minor
    }
}
record Word { text: Str
    fn hashKey(self) -> Dyn { return self.text.length } }
record Bag satisfies order.Iterable[Int] { xs: List[Int]
    fn items(self) -> List[Int] { return self.xs } }
fn main() {
    let vs = [Version(major: 1, minor: 2), Version(major: 0, minor: 9), Version(major: 1, minor: 0)]
    print(order.sort(vs))
    print(order.max(vs), order.min(vs), order.max([]))
    print(order.groupByKey([Word(text: "a"), Word(text: "bb"), Word(text: "c")]))
    print(order.flatten([Bag(xs: [1, 2]), Bag(xs: [3])]))
}""", mode="verified")
    assert r.lines == [
        "[Version(major: 0, minor: 9), Version(major: 1, minor: 0), Version(major: 1, minor: 2)]",
        "Some(Version(major: 1, minor: 2)) Some(Version(major: 0, minor: 9)) None",
        '{1: [Word(text: "a"), Word(text: "c")], 2: [Word(text: "bb")]}',
        "[1, 2, 3]"]


def test_order_sort_is_stable():
    r = ok("""
import std.order
record K { k: Int, tag: Str
    fn compareTo(self, other: Dyn) -> Int { return self.k - (other as K).k } }
fn main() { print(order.sort([K(k: 2, tag: "a"), K(k: 1, tag: "b"), K(k: 2, tag: "c"), K(k: 1, tag: "d")]).map(fn(x) => x.tag)) }""")
    assert r.lines == ['["b", "d", "a", "c"]']


def test_non_comparable_rejected_statically_and_at_runtime():
    src = """
import std.order
record W { s: Str }
fn main() { print(order.sort([W(s: "x"), W(s: "y")])) }"""
    assert "S.TYPE.STATIC_MISMATCH" in check(src, "verified").check_errors
    r = run(src)
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


def test_regex_operations():
    r = ok(r"""
import std.regex
fn main() throws PatternError {
    print(try regex.matches("[a-z]+\\d", "abc1"), try regex.matches("[a-z]+", "abc1"))
    print(try regex.find("(\\w+)@(\\w+)?", "mail bob@ now"))
    print(try regex.find("z", "abc"))
    print((try regex.findAll("\\d+", "a1 b22 c333")).map(fn(m) => m.text))
    print(try regex.replace("(\\w+)=(\\w+)", "a=1, b=2", "$2:$1 $$"))
    print(try regex.split(",\\s*", "x, y,z"))
    print(try regex.find("é+", "caféé"))
    print(regex.escape("a.b"))
}""", mode="verified")
    assert r.lines == [
        "true false",
        'Some(RegexMatch(text: "bob@", start: 5, end: 9, groups: [Some("bob"), None]))',
        "None",
        '["1", "22", "333"]',
        "1:a $, 2:b $",
        '["x", "y", "z"]',
        'Some(RegexMatch(text: "éé", start: 3, end: 5, groups: []))',  # code-point indices
        "a\\.b"]


def test_invalid_pattern_is_recoverable_data_error():
    r = ok("""
import std.regex
fn main() {
    let v = try regex.matches("(", "x") catch PatternError as e => { print("bad: {e.message} at {e.position}")
        false }
    let w = try regex.matches("[", "x") catch Data => true
    print(v, w)
}""")
    assert r.lines == ["bad: missing ), unterminated subpattern at 0", "false true"]


def test_regex_effect_must_be_declared_in_verified():
    r = check("""
import std.regex
fn f(s: Str) -> Bool { return try regex.matches("a", s) }""", "verified")
    assert "S.EFFECT.UNDECLARED_THROWS" in r.check_errors


def test_datetime():
    r = ok("""
import std.datetime
fn main() throws FormatError {
    let d = try datetime.parseIso("2024-02-28T23:30:00Z")
    let e = datetime.addMillis(d, 3600000)
    print(datetime.formatIso(e), datetime.weekday(e), datetime.toEpochMillis(d))
    print(datetime.formatIso(datetime.fromEpochMillis(1500)))
    print(try datetime.parseIso("2024-05-01T12:00:00+02:00"))
    print(try datetime.date(2024, 1, 2) == (try datetime.of(2024, 1, 2, 0, 0, 0, 0)))
    let bad = try datetime.parseIso("yesterday") catch FormatError as f => { print("bad: {f.input}")
        d }
    let leap = try datetime.date(2023, 2, 29) catch FormatError as f => { print("invalid: {f.input}")
        d }
}""", mode="verified")
    assert r.lines == ["2024-02-29T00:30:00Z Thursday 1709163000000", "1970-01-01T00:00:01.500Z",
                       "DateTime(year: 2024, month: 5, day: 1, hour: 10, minute: 0, second: 0, millis: 0)",
                       "true", "bad: yesterday", "invalid: 2023-2-29-0-0-0-0"]


def test_json_and_math():
    r = ok("""
import std.json
import std.math
fn main() throws JsonError {
    let v = try json.parse("\\{\\"a\\": [1, 2.5, null, true]\\}")
    print(v, json.stringify(v))
    print(math.sqrt(16.0), math.gcd(12, 18), math.pow(2.0, 10.0))
    let bad = try json.parse("\\{") catch JsonError as e => "line {e.line}"
    print(bad)
}""")
    assert r.lines[0] == '{"a": [1, 2.5, None, true]} {"a":[1,2.5,null,true]}'
    assert r.lines[1:] == ["4.0 6 1024.0", "line 1"]
