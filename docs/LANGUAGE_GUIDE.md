# Language guide

A practical reference for writing programs in this implementation of the V3
language. Semantics are defined by `design/LLM_NATIVE_DESIGN_V3.md`; specification
choices are in `DECISIONS.md`; per-subsystem contracts are in `docs/semantics/`.

Every fenced block marked `lang` below is a complete program executed by
`tests/unit/test_language_guide.py`; the comment `// prints:` lists its expected
output.

## 1. Programs, modules and tools

A file is a module. Execution starts at `fn main()` (or `async fn main()`, or
`fn main(args: List[Str])`). `print` writes its arguments separated by spaces.

```lang
fn main() {
    print("hello", 1 + 2)
}
// prints: hello 3
```

```
lang run main.lang [args...]     # check (draft by default), then run
lang check --mode=verified f.lang --json
lang format f.lang               # canonical layout (--check / --diff)
lang test tests/ --schedule=random --seed=42
lang repl
```

Exit status: 0 ok, 1 unhandled recoverable error, 2 static errors, 3 abandonment,
4 hard termination, 130 interrupted; `main() -> Int` returns its own status.

## 2. Values and bindings

`let` bindings can be rebound; `const` cannot. Values are frozen unless their type
says `Mutable…` or `mutable record`. There is no truthiness and no implicit
conversion: `1 + 2.0` and `"a" + 1` are errors; `Int / Int` gives a `Float`;
use `a.div(b)` for floor division.

```lang
fn main() {
    let count = 1
    count = count + 1
    const LIMIT = 10
    let xs = [1, 2, 3]            // frozen List[Int]
    let more = xs + [4]           // a new list
    let ys = MutableList[Int]()   // mutable, identity-bearing
    ys.push(5)
    let m = {"a": 1, "b": 2}      // frozen Map, insertion-ordered
    print(count, LIMIT, more, ys.length, m["b"], 7 / 2, 7.div(2), xs.get(9))
}
// prints: 2 10 [1, 2, 3, 4] 1 2 3.5 3 None
```

Strings interpolate `{expr}` (write `\{` and `\}` for literal braces) and support
`{x:>6}` / `{f:.2}` formatting.

```lang
fn main() {
    let name = "Ada"
    let score = 9.5
    print("{name} scored {score:.2} \{braces\}")
}
// prints: Ada scored 9.50 {braces}
```

## 3. Functions, records, enums and matching

Functions return values only with `return`. Records are constructed with named
fields; `with` makes an updated copy of a frozen record. Enum cases are always
qualified, except the core `Some`, `None`, `Ok`, `Err`.

```lang
record Point { x: Int, y: Int
    fn dist2(self) -> Int { return self.x * self.x + self.y * self.y }
}

enum Shape { Circle(r: Float), Rect(w: Float, h: Float), Empty }

fn area(s: Shape) -> Float {
    return match s {
        Shape.Circle(r) => 3.0 * r * r
        Shape.Rect(w, h) => w * h
        Shape.Empty => 0.0
    }
}

fn main() {
    let p = Point(x: 3, y: 4)
    let q = p with { y: 0 }
    print(p.dist2(), q, area(Shape.Rect(w: 2.0, h: 3.0)))
    let maybe: Int? = null
    print(match maybe { Some(v) => v, None => -1 })
}
// prints: 25 Point(x: 3, y: 0) 6.0
// prints: -1
```

Lambdas: `fn(x) => x + 1` or `fn(x: Int) -> Int { return x + 1 }`. A closure that
reassigns a captured binding must say `nonlocal`.

```lang
fn main() {
    let total = 0
    let add = fn(n: Int) {
        nonlocal total
        total = total + n
    }
    add(2)
    add(3)
    print(total, [1, 2, 3].map(fn(x) => x * 10))
}
// prints: 5 [10, 20, 30]
```

## 4. Recoverable errors and Result

Errors are declared types. A throwing function lists them; call sites mark the
failure point with `try` (required in verified mode), handle with `catch`, or
convert to a `Result` with `capture`. `propagate r` returns an `Err` early from a
`Result`-returning function.

```lang
error ParseError { line: Int }

fn parseLine(s: Str, line: Int) -> Int throws ParseError {
    if s == "" { throw ParseError(line: line) }
    return s.length
}

fn total(lines: List[Str]) -> Result[Int, ParseError] {
    let sum = 0
    for (i, s) in lines.enumerate() {
        sum = sum + propagate (capture parseLine(s, i + 1))
    }
    return Ok(sum)
}

fn main() {
    let n = try parseLine("abc", 1) catch ParseError as e => -e.line
    let fallback = try parseLine("", 2) else 0
    print(n, fallback, total(["a", "bb"]), total(["a", ""]))
}
// prints: 3 0 Ok(3) Err(ParseError(line: 2))
```

Abandonment (a broken assumption such as `xs[99]`, a failed contract or
`assert`) is not catchable; it stops the program with a diagnostic.

## 5. Contracts and invariants

```lang
predicate positive(x: Int) { x > 0 }

mutable record Account {
    balance: Int
    invariant balance >= 0

    fn withdraw(self, amount: Int) -> Int
        requires positive(amount)
        ensures result == old(self.balance) - amount
    {
        self.balance = self.balance - amount
        return self.balance
    }
}

fn main() {
    let a = Account(balance: 10)
    print(a.withdraw(3))
}
// prints: 7
```

## 6. Resources and cleanup

A resource provider yields exactly once and is used only through `use`. The scope
is expression-valued; release runs on every non-abandoning exit and can see how the
scope ended. `defer` runs at block exit, last-in first-out.

```lang
resource fn session(name: Str) yields Str {
    print("open", name)
    let exit = yield name
    print("close", name, match exit { ScopeExit.Normal => "ok", _ => "rolled back" })
}

fn helper(s: borrow Str) -> Int { return s.length }

fn main() {
    defer print("main done")
    let n = use s = session("db") { helper(s) }
    print("length", n)
}
// prints: open db
// prints: close db ok
// prints: length 2
// prints: main done
```

## 7. Structured concurrency

Only `async fn` can suspend, and calls to them are written `await`. Tasks are
created with `spawn` inside a `parallel` block and never outlive it. Mutable
arguments are copied into the child; frozen ones are shared.

```lang
async fn work(n: Int) -> Int {
    await sleep(n.millis)
    return n * 10
}

async fn main() {
    let total = parallel {
        let a = spawn work(2)
        let b = spawn work(1)
        (await a) + (await b)
    }
    let first = parallel race { spawn work(5)
        spawn work(1) }
    let r = try within 1.millis { await work(50) } catch DeadlineExceeded => -1
    print(total, first, r)
}
// prints: 30 10 -1
```

Group modes: `parallel` (fail-fast, failures arrive as `AggregateException`),
`parallel collect` (returns a `TaskGroupReport`), `parallel race`,
`parallel firstSuccess`. Long CPU loops call `cancel.check()`.

## 8. Channels and select

```lang
async fn producer(tx: SendPort[Int]) throws ChannelClosed {
    for i in 1..=3 { await tx.send(i) }
}

async fn main() {
    let ch = Channel[Int].buffered(2)
    let rx = ch.receiver()
    let sum = parallel {
        spawn producer(ch.sender())
        let total = 0
        let deadline = time.now() + 1.seconds
        let open = true
        while open {
            select {
                receive x from rx => { total = total + x
                    if x == 3 { open = false } }
                at deadline => { open = false }
            }
        }
        total
    }
    print(sum)
}
// prints: 6
```

`select now { ... none ready => ... }` never waits; `when flag: branch` guards a
branch with a precomputed `Bool`; `closed rx => ...` handles closure explicitly.

## 9. Draft and verified

Draft mode runs programs with missing annotations and markers, reporting them as
warnings; written annotations, contracts, resources and task isolation are always
enforced. Verified mode (`--mode=verified`, or `mode = "verified"` in `lang.toml`)
turns those obligations into errors; release builds (`--release`) require it.

## 10. Standard library

`import std.<name>` binds the module name. Native modules: `std.fs` (resource
providers such as `fs.openRead`), `std.json`, `std.math`, `std.regex`,
`std.datetime`. Written in the language itself (lang/stdlib/): `std.chan`
(`drain`, `fanIn`, `ask`/`serve` request-response, `workerPool`) and `std.order`
(the structural protocols `Comparable`, `Hashable`, `Iterable` and helpers).
Standard errors (`JsonError`, `PatternError`, `FormatError`, `FileNotFound`, ...)
belong to catch categories such as `Data` and `IO`.

```lang
import std.regex
import std.datetime
import std.order

record Version { major: Int, minor: Int
    fn compareTo(self, other: Dyn) -> Int {
        let o = other as Version
        return if self.major != o.major { self.major - o.major } else { self.minor - o.minor }
    }
}

fn main() throws PatternError, FormatError {
    print((try regex.findAll("\\d+", "v1.22.3")).map(fn(m) => m.text))
    let d = try datetime.parseIso("2024-02-28T23:30:00Z")
    print(datetime.formatIso(datetime.addMillis(d, 3600000)))
    print(order.max([Version(major: 1, minor: 4), Version(major: 2, minor: 0)]))
}
// prints: ["1", "22", "3"]
// prints: 2024-02-29T00:30:00Z
// prints: Some(Version(major: 2, minor: 0))
```
