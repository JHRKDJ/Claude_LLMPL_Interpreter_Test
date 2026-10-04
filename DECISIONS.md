# DECISIONS

This file records only (a) specification-stage decisions that V3 requires someone
to make, (b) genuine V3 ambiguities that had to be resolved, and (c) implementation
architecture decisions with semantic consequences.

**Authority:** `design/LLM_NATIVE_DESIGN_V3.md` (V3) is authoritative. Every entry
names its V3 basis. If an entry conflicts with V3, V3 wins and the entry must be
corrected.

Entry kinds: `SPEC` = specification-stage decision (V3 asks for a choice);
`AMB` = genuine ambiguity / conflict resolved narrowly; `IMPL` = implementation
decision with semantic consequences.

---

## A. Surface syntax (V3 Part IV, 5.17, 7.1, 9.3)

### SPEC-001 Blocks, statements, comments
- Braces delimit every block (V3 6.1 Decided). Newlines terminate statements; `;`
  is accepted as a separator but is non-canonical (formatter splits lines).
- Continuation (V3 7.1.2): inside `(...)`/`[...]`/map literals; after a binary
  operator at end of line; after `,` `=` `=>` `->`; a line beginning with `.`
  continues a chained call; `else`/`catch` may begin the line after `}`; function
  headers may break before `throws`/`requires`/`ensures`/`{`.
- A line that *starts* with a binary operator is **not** a continuation; the parser
  reports `S.SYNTAX.LEADING_OPERATOR` with a fix (V3: "prefer clear diagnostics over
  aggressive implicit continuation").
- Comments: `// line` and `/* block */` (non-nesting).

### SPEC-002 Bindings and constants (V3 5.1.5, 6.3, 9.3#1)
- `let x = e` declares a **reassignable** binding (JavaScript `let` prior; V3
  examples use `let`). `let x: T` without initializer declares an *uninitialised*
  binding (V3 5.4.3-4); reading it before definite assignment is a static error and
  a runtime abandonment `A.BINDING.UNINITIALISED`.
- `const x = e` declares a non-reassignable binding (JS prior). At module level only
  `const` is permitted and the value must be transitively frozen (V3 5.2.1-2).
- `x = e` rebinds; `obj.f = e` / `xs[i] = e` mutate (V3 5.1.5 keeps these distinct).
  Compound `+= -= *= /= %=`.

### SPEC-003 Closure capture / reassignment marker (V3 6.3, 7.4.3, 9.2, 9.3#20)
- Closures capture bindings lexically (by reference to the binding).
- A closure may reassign a captured binding only after declaring `nonlocal x`
  inside the closure body (Python prior, compared with Rust capture modifiers and
  explicit capture lists; chosen for familiarity and greppability). Without it,
  assignment is `S.NAME.CAPTURED_REASSIGN` (both modes).
- A capture is **mutable** if the captured binding is reassigned anywhere after
  declaration (including via `nonlocal`) or the captured value is mutable. Closures
  with mutable captures are not sendable (V3 5.11).

### SPEC-004 Functions, methods, lambdas (V3 6.1, 7.1.3-7.1.6, 6.5)
- `fn name[T](p: T, q) -> R throws E1, E2 requires c ensures c { ... }`; `async fn`.
- Function bodies return Unit unless `return e` is executed (Kotlin model: blocks of
  `if`/`match`/`use`/`select`/`parallel`/`within` yield their last expression, but
  function bodies require explicit `return`). V3 7.2.1: expression orientation only
  where it does not obscure control flow; V3 examples always use `return`.
- Methods are declared inside the `record`/`enum` body with explicit `self` first
  parameter (V3 6.5). A member `fn` without `self` is an associated function
  (`Config.defaults()`).
- Lambdas share the `fn` family (V3 7.1.6): `fn(x) => x + 1` (expression) and
  `fn(x: Int) -> Int throws E { ... }` (block; needs `return`). `async fn(...)`.
- Parameters may have defaults (`y: Int = 0`, frozen constant expressions only).
  Calls accept positional then named arguments `f(1, y: 2)`.

### SPEC-005 Types and Dyn spelling (V3 5.3.1, 6.4, 9.3#4)
- `Dyn` names the dynamic type. Built-ins: `Int Float Bool Str Unit Dyn`,
  `List[T] Map[K,V] Set[T]` (frozen), `MutableList[T] MutableMap[K,V] MutableSet[T]`,
  `Option[T]` / `T?`, `Result[T,E]`, tuples `(A, B)`, function types
  `fn(A, B) -> C throws E1 | E2`, `async fn(...)`, `Task[T,E]`, `Channel[T]`,
  `SendPort[T]`, `ReceivePort[T]`, `Instant`, `Duration`, `borrow T` (parameters).
- Throws lists use `,` in declaration headers and `|` inside function *types*
  (a comma there would end the parameter). The formatter canonicalises both.

### SPEC-006 Records, update, construction (V3 5.1, 7.3.1, 9.3#2)
- `record Name[T] satisfies P { field: T = default  sensitive field: Str  invariant expr  fn method(self) ... }`
  and `mutable record Name { ... }` (V3 working form).
- Construction is call-like with named fields: `User(name: "Ann", age: 3)` (avoids
  Rust's struct-literal/block ambiguity). Positional construction is permitted only
  for single-field records.
- Frozen update: `user with { age: 4 }` (V3 7.3.1 illustrative form). `with` is
  only legal on frozen records (mutable records use field assignment).

### SPEC-007 Variants (V3 6.2, 3.3)
- `enum Shape { Circle(radius: Float)  Rect(w: Float, h: Float)  Empty }`.
- User cases are always qualified: `Shape.Circle(radius: 1.0)`, pattern
  `Shape.Circle(r)`. Only the core cases `Some`, `None`, `Ok`, `Err` are unqualified.

### SPEC-008 Collections (V3 7.3.2, 9.3#3)
- Literals `[1, 2]` (frozen `List`), `{"k": v}` (frozen `Map`), `Set.of(1, 2)`.
  Mutable: `MutableList[Int]()`, `MutableList.of(...)`, `xs.mutableCopy()`,
  `m.freeze()` (V3 5.1.7).
- Map and Set iterate in **insertion order** (stable and specified; V3 7.3.2).
  Equality of maps/sets ignores order. Maps are not directly iterable; use
  `.keys()`, `.values()`, `.entries()` (explicit; avoids Python/Swift prior clash).
- Mutating a mutable collection while iterating it abandons
  (`A.COLLECTION.MODIFIED_DURING_ITERATION`).
- `xs[i]` abandons on out-of-range (precondition); `xs.get(i)` returns `T?`
  (V3 7.7.2 checked twin).

### SPEC-009 Strings (V3 7.1.5, 7.3.3)
- `"..."` and `"""..."""` always interpolate `{expr}` / `{expr:fmt}`; literal braces
  are written `\{` `\}`. Format spec: `[<|>]width` and `.N` precision.
- Interpolation uses the built-in safe display only; it never calls user code.
- `Str` is a sequence of Unicode code points; `length` counts code points; no
  implicit normalisation (`s.normalized()` is explicit).

### SPEC-010 Operators and numerics (V3 7.3.3, 4.2, 9.3#25)
- `&&` `||` `!` require Bool operands and produce Bool (V3 4.2: Python's operand-
  returning `and`/`or` would be a false prior). Conditions must be Bool (no
  truthiness; V3 2.7).
- `+ - * %` on Int→Int, Float→Float; mixing Int and Float abandons
  (`A.TYPE.OPERAND_MISMATCH`; V3 5.3.4 no coercion). `Int / Int` yields Float (true
  division — a mistaken integer assumption then fails loudly, whereas silent
  truncation would not); floor division is `a.div(b)`; `%` is floored modulo.
  Integer division/modulo by zero abandons; `checkedDiv` returns `Int?`.
- `+` concatenates Str+Str and List+List only.
- `==` is structural for frozen values and identity for identity-bearing (mutable)
  values (V3 5.1.1-2). Different runtime types compare unequal, except Int vs Float
  which abandons (silent `1 == 1.0` coercion is exactly what V3 forbids).
- **NaN policy (provisional, V3 7.3.3/9.2):** Float arithmetic follows IEEE-754
  (NaN/Inf propagate) because data workloads are in scope; NaN is made visible at
  boundaries where it would corrupt structure: NaN as a Map key/Set element abandons
  (`A.NUMERIC.NAN_KEY`), `toInt()`/`round()` of NaN/Inf abandons, and
  `isNaN()/isFinite()` exist. Revisit with evidence.

### SPEC-011 Error declarations, categories, catches (V3 5.9, 7.7.7, 9.3#8)
- `category IO` declares a catch category. `error FileNotFound category IO { path: Str }`
  declares a concrete nominal error (frozen record-like). `error enum ParseError { ... }`
  declares a closed error enum.
- `throw expr` raises a recoverable error value.
- `try e` propagates (prefix; covers the whole operand expression, Swift-style).
- `try e catch FileNotFound as err => h  catch category IO as err => h2` handles
  named types/categories (expression-valued). There is no catch-all.
- `try e else fallback` (unqualified fallback) is legal only when the statically known
  throws set of `e` is exactly one concrete error type (V3 5.7.5); otherwise
  `S.EFFECT.BROAD_FALLBACK` in **both** modes (it is a legality rule, not an
  annotation obligation).

### SPEC-012 Exception/Result conversion (V3 5.7.4, 7.7.4, 9.3#6, 9.3#24)
- `capture e` evaluates `e` and yields `Ok(v)` or `Err(error)` for recoverable
  exceptions only (never cancellation/abandonment). Marks awaited child errors
  observed (V3 5.12.4).
- `r.orThrow()` throws the `Err` payload (so `try r.orThrow()`).
- `propagate r` inside a function returning `Result` returns the `Err` early
  (appending a propagation-chain entry) or yields the `Ok` value.
- Context attachment: `Err(e).context("path", path)` (V3 7.7.8 illustrative).

### SPEC-013 Effect variables and unions (V3 5.8, 7.7.5, 9.3#7)
- Type parameters used in a `throws` position are error-set variables:
  `fn map[T, U, E](xs: List[T], f: fn(T) -> U throws E) -> List[U] throws E`.
  Unions `E1 | E2` normalise by sorted unique names for diagnostics.

### SPEC-014 Contracts, predicates, invariants (V3 5.10, 7.8, 9.3#9-10)
- `requires`/`ensures` clauses follow the signature; `result` names the return value
  inside `ensures`; `old(expr)` snapshots at entry.
- `predicate name(params) { boolExpr }` — restricted, non-recursive.
- `invariant expr` inside a record body.
- **Invariant field control (9.3#10):** fields mentioned by any invariant of a
  record may be assigned only inside that record's own methods. Invariants are
  checked after construction, after `with`, and at exit (normal / exception /
  cancellation, after cleanup) of every *outermost* method call on that object
  (Eiffel qualified-call rule: calls on `self` from within an active method of the
  same object do not re-check).

### SPEC-015 Resources (V3 5.5, 7.9, 9.3#5)
- Provider: `resource fn openFile(path: Str) yields File throws IOError { ... }`
  (`async resource fn` allowed). Body must execute exactly one `yield value`.
  `let exit = yield v` receives a `ScopeExit` (`Normal`, `Failed`, `Cancelled`) so
  normal release can choose commit/rollback (V3 5.5.9 "may know which exit class").
- `onAbandon handle.close()` registers an abandonment-safe release; only built-in
  primitives flagged abandonment-safe are accepted (V3 5.5.10-12).
- Scope: `use file = try openFile(path) { body }` (expression-valued).
- Borrow parameters: `fn parse(file: borrow File)`.

### SPEC-016 `defer` (V3 5.6, 7.9.6)
- `defer expr` / `defer { block }` is **block-scoped** (Swift prior) and runs LIFO at
  block exit on normal return, recoverable exception, and cancellation (masked);
  never during abandonment. Deferred blocks may `await` in async functions.

### SPEC-017 Task groups and spawn (V3 5.12, 7.10, 9.3#15)
- `parallel { ... }` = fail-fast; `parallel collect { ... }` = collect-all returning
  `TaskGroupReport`; `parallel race { ... }`; `parallel firstSuccess { ... }`.
- `spawn f(args)` (explicit arguments, preferred) or `spawn { block }` (captures);
  must appear lexically inside a `parallel` body; returns `Task[T, E]`.
- `await h` waits for a child; `within deadline { ... }` cancels its body at the
  deadline and throws `DeadlineExceeded` (V3 7.12.9 "lexical within").
- Cancellation check: `cancel.check()` (V3 9.3#16 working form `cancel.check()`).

### SPEC-018 Channels (V3 5.13, 7.11, 9.3#11-12)
- `Channel[T].rendezvous()` / `.buffered(n)` / `.unbounded()` → controller.
  Controller: `.sender()`, `.receiver()`, `.close()`. Ports: `await tx.send(v)`
  (throws `ChannelClosed`), `await rx.receive()` (throws `ChannelClosed` once closed
  and drained), `tx.trySend(v)` → `TrySend`, `rx.tryReceive()` → `TryReceive[T]`,
  `port.release()`; loop sugar `for await x in rx { }` ends on closure.
- `Broadcast[T].buffered(n)` with `.publisher()` and `.subscribe()`; frozen-only.

### SPEC-019 Select (V3 5.14, 7.12, 9.3#13-14)
```
select [priority | now] {
    when ready: receive msg from rx => ...
    closed rx => ...
    send value to tx => ...
    task h completed as r => ...      // r : Result[T, E]
    at deadline => ...
    after 5.seconds => ...
    none ready => ...                  // only in `select now`
}
```
- A receive branch on a closed-and-drained port without a matching `closed` branch
  makes the select throw `ChannelClosed` (explicit: visible as `try select`).
- Dynamic homogeneous helpers: `await selectReceive(ports)` and
  `await selectTask(handles)`.

### SPEC-020 Modules, exports, manifest (V3 6.11, 7.4.1, 9.3#17-19,21)
- One file = one module (`.lang`). `import a.b.c` binds `c`; `import a.b.{x, y}`
  binds names; `import a.b as z`. Paths are absolute from the project root.
- Directory modules: `a/b/mod.lang` is module `a.b` (Rust precedent).
- Export keyword `pub` (V3 working prior); default module-private.
- Manifest `lang.toml` (`[project] name, mode`, `[dependencies] name = { path }`),
  lockfile `lang.lock`. Import cycles between modules are allowed for declarations;
  cycles among module-constant initialisers are rejected with the full cycle
  (`S.MODULE.INIT_CYCLE`, V3 6.11 "Runtime value-initialisation cycles: Rejected").

### SPEC-021 Tests and stress flags (V3 7.14.5, 9.3#22)
- `test "name" { ... }` top-level blocks; `assert cond` / `assert cond, "msg"`
  (abandons on failure). `lang test --schedule=random --seed=N`.

### SPEC-022 Diagnostic code display (V3 7.13.2, 9.3#23)
- Display `A.TYPE.DYNAMIC_MISMATCH`; JSON carries `outcome`, `domain`, `reason`,
  `stable_code` separately. Outcomes: `A` abandonment, `R` recoverable, `S`
  static, `W` warning/advisory, `C` cancellation, `H` hard termination.

---

## B. Semantic resolutions (ambiguities and gaps)

### AMB-001 Global structural protocol conformance vs. inherited contracts
V3 5.10.8/5.10.11 + 7.5.1: conformance is structural, and protocol contracts apply
"whenever the conforming method is invoked". **Resolution:** the conformance relation
is computed over every protocol in the loaded program; for a concrete type T,
calling method m runs the contracts of every protocol P that T structurally satisfies
and that declares m. **Narrowing:** a method that adds its own `requires` does not
structurally satisfy a protocol declaring that method (V3 5.10.9 forbids added
preconditions; making such a type non-conforming avoids action-at-a-distance
precondition errors). Declaring `satisfies P` on such a type is a static error.
*Concern recorded for the final report:* a protocol added in another module can add
postconditions to existing types' methods.

### AMB-002 Fail-fast groups and observing a child failure at `await`
V3 5.12.3-5, 7.10.4, 8.10. **Resolution:** when a child terminates with an
unobserved recoverable failure: if the group body is at that moment blocked in
`await` on exactly that handle, the failure is delivered to the body (it may be
caught → observed). Otherwise the failure triggers group cancellation of the body and
all other children. `await` is always a cancellation point (V3 7.10.2), so a body
cannot catch a failure that already triggered group cancellation. Outward: every
unobserved failure, in task-path order, inside `AggregateException` (V3 6.8 "even
one child"). An exception thrown by the body itself is also aggregated (path
`<body>`); an awaited-but-uncaught child exception is aggregated once, under the
child's path (V3 8.10 "no failure displayed twice").

### AMB-003 Awaiting a child that was cancelled or abandoned
V3 says awaiting exposes recoverable exceptions; abandonment is never converted to a
catchable exception (7.10.3). **Resolution:** awaiting an abandoned child makes the
awaiting task abandon (`A.TASK.AWAITED_ABANDONED`) — the awaited value was assumed.
Awaiting a cancelled child delivers cancellation if the awaiter is itself under
cancellation, otherwise abandons (`A.TASK.AWAITED_CANCELLED`). In collect mode the
report, not `await`, is the supervision channel.

### AMB-004 Cancellation points
V3 7.10.2 lists `await`, explicit checks and blocking library operations; 7.11.6 says
a blocking send/receive is cancellable *only when it waits*. **Resolution:**
`await` (of a handle or async call), `cancel.check()`, `sleep`, `within` waits,
select waits, and channel operations that must wait are cancellation points; a
channel operation that commits immediately is not.

### AMB-005 Draft-mode absence of `throws`
V3 5.15.2-4: draft relaxes the obligation to *write* annotations but written ones stay
active. **Resolution:** in draft mode, a function with no `throws` clause has an
*unannotated* effect (exceptions propagate unchecked). A written `throws` clause is
enforced at runtime: an escaping undeclared recoverable error abandons
(`A.EFFECT.UNDECLARED_EXCEPTION`). In verified mode, absence means "throws nothing"
and is proven statically. Typed call sites additionally check escaping exceptions
against the callee's static function type (transient effect check, V3 7.6.2).

### AMB-006 Port liveness ("no receivers remain")
V3 5.13.10-11 needs endpoint-loss detection without GC finalisation (rejected by
RUN0 §I and V3 9.5 "Final-reference cleanup"). **Resolution:** each task holds a
set of port capabilities: ports it created (`ch.sender()`/`ch.receiver()`) or
received through task arguments, captures, or messages. A task's holdings are
released at task termination or by `port.release()`. "No receivers remain" = no
task holds any receive port of the channel; similarly for senders.

### AMB-007 Equality of identity-bearing values
V3 5.1.1-2 gives frozen values structural equality and mutable records identity.
**Resolution:** `==` on mutable records and mutable collections is identity; a static
advisory (`W.TYPE.IDENTITY_EQUALITY`) points to `.freeze()` for content comparison.
Map keys and Set elements must be frozen (`A.TYPE.UNHASHABLE`).

### AMB-008 `spawn` inside closures / helper functions
V3 3.2 "every task creation point is visible locally"; 5.12 lexical nesting.
**Resolution:** `spawn` is legal only lexically inside a `parallel` body of the same
function (not inside a nested lambda), so the owning group is always visible.

### AMB-009 Contract language: reading mutable fields
V3 5.10.3 lists "frozen field reads"; invariants of mutable records (5.10.6-7) must
read mutable fields. **Resolution:** contracts may *read* fields of any record; they
may not mutate, call general functions, or allocate unboundedly. `old()` legality is
judged on the captured *result* (V3 7.8.3).

### AMB-010 Unresolved names in draft mode
V3 2.4 and 5.15.2. **Resolution:** an unresolved name is a blocking static error in
both modes (`S.NAME.UNRESOLVED`, with import candidates and an optional visible
patch) — executing it can never succeed and V3 makes the diagnostic the point.

---

## C. Implementation architecture with semantic consequences

### IMPL-001 Deterministic cooperative scheduler on baton-passing threads
Language tasks run on Python threads, but exactly one runs at a time; a central
scheduler hands a baton to the next ready task (FIFO by default, seeded random under
`--schedule=random`). This keeps scheduling deterministic and independent of
Python's asyncio/GIL policy (V3 2.7), while letting the tree-walking evaluator stay
recursive. Python threads are never used for parallel execution.

### IMPL-002 Virtual clock option
`--clock=virtual` makes time advance only when every task is blocked (discrete-event
simulation) so deadline/timeout behaviour is reproducible in tests. The default clock
is real monotonic time.

### IMPL-003 Resource providers execute the scope body *inside* `yield`
Because a provider yields exactly once and the scope is lexical, `yield v` invokes the
scope body as a callback and captures its outcome; the provider then continues with
the `ScopeExit` class. Body exceptions/cancellation are never delivered into provider
code (so release cannot suppress them, V3 5.5.9). Abandonment unwinds through the
provider without running post-yield code (V3 5.5.10).

### IMPL-004 Static checker inserts transient checks
The checker computes static types and records, per AST node, the runtime check a
typed use relies on (V3 7.6.3); the runtime executes those checks in both modes, and
always enforces written boundary annotations independently of the checker.
