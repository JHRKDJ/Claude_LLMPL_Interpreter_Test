# BUG LEDGER

Meaningful interpreter/toolchain defects discovered during development. Each entry
has a permanent regression test that failed before the fix. LocalFlow application
defects are recorded separately in `examples/localflow/APP_BUG_LEDGER.md`.

Format:

```
BUG-NNNN
Origin: where it was found (unit/conformance/LocalFlow scenario/audit)
Subsystems: ...
Symptom: ...
Minimal reproduction: tests/regressions/...
Regression test failed before fix: yes/no
Fix: ...
Commit: ...
Status: open/fixed
```

---

BUG-0001
Origin: conformance test `test_composed_provider_scoped_delegation` (resources)
Subsystems: resources × call frames (× async/spawn/select frame state)
Symptom: a provider that yields from inside its own `use` scope abandoned with
  A.RESOURCE.MULTIPLE_YIELD; more generally, while a `use` body ran inside a
  provider's `yield`, the logical frame stack still had the suspended provider
  frame on top, so frame-scoped state (provider context, async-ness, spawn groups,
  select fairness cursors, invariant `self` rule) was taken from the wrong activation.
Minimal reproduction: tests/regressions/test_bug_0001_provider_frames.py
Regression test failed before fix: yes (both cases)
Fix: eval_Yield hides the suspended provider frames (restores call depth) while the
  scope body runs and restores them for normal release (lang/runtime/interp/res.py).
Commit: 3dcea3c
Status: fixed

BUG-0002
Origin: conformance test `test_external_cancellation_plus_group_failure_preserved`
Subsystems: task groups × external cancellation
Symptom: a fail-fast (or collect) group whose children were cancelled by an
  enclosing scope's cancellation returned normally (fail-fast returned the body
  value; collect returned a report) instead of propagating cancellation after
  quiescence.
Minimal reproduction: tests/regressions/test_bug_0002_group_external_cancel.py
Regression test failed before fix: yes (2 of 3 cases; the third pins the
  "unaffected group returns, cancellation stays pending" behaviour)
Fix: group_outcome re-raises cancellation after quiescence when cancellation is
  pending for the owner and any child ended cancelled (lang/runtime/interp/conc.py).
Commit: 3dcea3c
Status: fixed

BUG-0003
Origin: checker integration review (conformance test
  `test_on_abandon_restricted_to_builtin_primitives` asserted the wrong code)
Subsystems: resources × diagnostics
Symptom: the runtime's defence-in-depth check for `onAbandon` (only built-in
  abandonment-safe release primitives, V3 5.5.10-12) abandoned with the unrelated
  code A.RESOURCE.PROVIDER_OUTSIDE_USE, so tools and readers could not distinguish
  "provider used outside `use`" from "unsafe abandonment action".
Minimal reproduction: tests/regressions/test_bug_0003_on_abandon_code.py (runs the
  interpreter without the static checker, which now rejects this statically)
Regression test failed before fix: yes
Fix: exec_OnAbandonStmt reports A.RESOURCE.ON_ABANDON_RESTRICTED (new code in
  lang/diagnostics/codes.py); the conformance test asserts the static code
  S.RESOURCE.ON_ABANDON_RESTRICTED.
Commit: a67c865
Status: fixed

BUG-0004
Origin: writing checker conformance tests (one-line enum/match forms)
Subsystems: parser (match arms × record/enum members × select branches)
Symptom: after consuming a `,` separator the parser still required a newline, so
  `match x { 1 => 10, _ => 0 }`, `enum Color { Red, Green, Blue }` and
  `record P { x: Int, y: Int }` were rejected with S.SYNTAX.MISSING_SEPARATOR,
  contradicting the syntax contract.
Minimal reproduction: tests/regressions/test_bug_0004_comma_separators.py
Regression test failed before fix: yes (4 of 5 cases; the fifth pins that a missing
  separator without a comma is still reported)
Fix: a consumed `,` now ends the item exactly like a newline at all three sites in
  lang/syntax/parser.py; syntax.md grammar and SPEC-007 updated to state it.
Commit: be0d02c
Status: fixed

BUG-0005
Origin: formatter safety net (parse/format/parse equivalence over the test corpus)
Subsystems: parser × source spans (× diagnostics, formatter)
Symptom: `-` applied to a parenthesised numeric literal was folded into one literal
  whose span ended before the closing parenthesis (`-(-7` for `-(-7)`), so any
  diagnostic or tool reading the span saw truncated source text.
Minimal reproduction: tests/regressions/test_bug_0005_negative_literal_span.py
Regression test failed before fix: yes (span case; the other two pin folding of
  adjacent `-7` and unchanged values)
Fix: parse_unary folds only when the number literal immediately follows the minus
  sign (lang/syntax/parser.py); the formatter treats folded negative literals as
  prefix expressions for parenthesisation.
Commit: 4285cb7
Status: fixed

BUG-0006
Origin: formatter fuzzing (seeded generated program, seed 4)
Subsystems: parser (statement start × leading-operator diagnostics)
Symptom: the rule "a line starting with `-` after a line that ends an expression is a
  separate statement" fired for every statement beginning with unary minus, so
  valid block values such as `if c { 1 } else { -v }` were rejected with
  S.SYNTAX.LEADING_OPERATOR.
Minimal reproduction: tests/regressions/test_bug_0006_leading_minus.py
Regression test failed before fix: yes (4 of 5; the fifth pins the genuine case and
  its fix)
Fix: the rule now requires a line break immediately before the `-` and a previous
  line ending in an expression-ending token (name, literal, `)` or `]`); the fix
  edit is anchored at that token (lang/syntax/parser.py).
Commit: 4285cb7
Status: fixed

BUG-0007
Origin: parser fuzzing (mutated corpus program, seed 115: `select {"outer")`)
Subsystems: parser error recovery × item loops (select branches, match arms, members)
Symptom: statement-level recovery stopped at a stray `)`/`]` without consuming it; an
  enclosing item loop then re-parsed the same token forever, appending diagnostics
  until the process ran out of memory (observed as the process being killed).
Minimal reproduction: tests/regressions/test_bug_0007_recovery_progress.py (runs in
  a memory-capped subprocess with a timeout)
Regression test failed before fix: yes
Fix: sync_stmt consumes a stray closing `)`/`]` when it has not advanced, so every
  recovery step makes progress (lang/syntax/parser.py).
Commit: f347523
Status: fixed

BUG-0008
Origin: interaction test TEST-INT-022 (select closure loops, V3 8.13)
Subsystems: static checker advisories × select × loops
Symptom: W.SELECT.CLOSED_LOOP was reported for loops whose closed branch ends the
  loop through the select's value (`let done = select { … closed rx => true }`,
  `if done { break }`) or by changing loop state (`closed rx => { open = false }`),
  i.e. a false positive on the correct shapes V3 8.13 asks programs to use.
Minimal reproduction: tests/regressions/test_bug_0008_closed_loop_advisory.py
Regression test failed before fix: yes (2 of 3; the third pins the genuine spin case)
Fix: the advisory fires only when the select's value is discarded (statement
  position in a loop/function body) and the closed branch neither exits nor assigns
  (lang/check/selectcheck.py, walk.py).
Commit: dcaa94f
Status: fixed

BUG-0009
Origin: writing LocalFlow (graph.lang)
Subsystems: static checker (type arguments in value position × destructuring)
Symptom: (a) `MutableList[(Str, Int)]()` gave elements type Dyn, so matches on
  `xs.last()` with tuple patterns were falsely reported non-exhaustive; (b)
  `let (a, b) = xs.pop()` (an Option) was not reported although it can only abandon.
Minimal reproduction: tests/regressions/test_bug_0009_tuple_type_args.py
Regression test failed before fix: yes (2 of 3; the third pins the runtime backstop)
Fix: type_from_value_expr converts tuple literals to tuple types; destructuring a
  statically non-tuple value (or a tuple of the wrong arity) is
  S.TYPE.STATIC_MISMATCH with an unwrap hint for Options (lang/check/expr.py, walk.py).
Commit: d886ef1
Status: fixed

BUG-0010
Origin: writing LocalFlow (load.lang)
Subsystems: static checker (block typing × control flow)
Symptom: a block ending in return/break/continue/throw had type Unit instead of
  Never, so a match with a diverging arm (`None => { continue }`) produced Dyn and
  later code lost static precision (false "open type" exhaustiveness warnings).
Minimal reproduction: tests/regressions/test_bug_0010_diverging_blocks.py
Regression test failed before fix: yes
Fix: block() types a block whose last statement transfers control as Never
  (lang/check/walk.py).
Commit: d886ef1
Status: fixed

BUG-0011
Origin: writing the standard library in the language (lang/stdlib/chan.lang)
Subsystems: name resolution × runtime type application
Symptom: inside a generic function, a type parameter written as a type argument in
  value position (`MutableList[T]()`, `Channel[A].rendezvous()`) was reported
  `S.NAME.UNRESOLVED`, and at run time it could not be evaluated, although the same
  parameter already worked in annotations (`let x: T`).
Minimal reproduction: tests/regressions/test_bug_0011_type_param_value_position.py
Regression test failed before fix: yes (both tests)
Fix: the resolver marks such an index as a type parameter instead of resolving it as
  a value; the runtime applies the erased parameter as `Dyn` (IMPL-006)
  (lang/check/resolve.py, lang/runtime/interp/exprs.py).
Commit: 4f8e1fc
Status: fixed

BUG-0012
Origin: first V3 coverage audit (diagnostic-code coverage sweep)
Subsystems: runtime diagnostics (member access)
Symptom: calling a missing method on a dynamically typed value (`p.go()` with
  `p: Dyn`) abandoned with `A.TYPE.UNKNOWN_FIELD`; the code-selection expression in
  `unknown_member` could never produce `A.TYPE.UNKNOWN_METHOD`, so the runtime code
  disagreed with the checker's `S.TYPE.UNKNOWN_METHOD` for the same source.
Minimal reproduction: tests/regressions/test_bug_0012_unknown_method_code.py
Regression test failed before fix: yes (2 of 3; the third pins field reads)
Fix: member lookup knows whether it serves a call; a missing callee member is
  `A.TYPE.UNKNOWN_METHOD`, a missing read is `A.TYPE.UNKNOWN_FIELD`
  (lang/runtime/interp/exprs.py, calls.py).
Commit: 4f8e1fc
Status: fixed

BUG-0013
Origin: first V3 coverage reread (V3 7.7.5 `compose` example)
Subsystems: static checker (error-effect polymorphism × higher-order returns)
Symptom: error-set variables bound at a call were not substituted into a returned
  function type, so `compose(parse, half)` had type `fn(Str) -> Int` with no effect:
  `try f(s)` was a false W.EFFECT.USELESS_TRY and a function declaring `throws Bad`
  that called the composition (which may throw `Worse`) was accepted in verified mode.
Minimal reproduction: tests/regressions/test_bug_0013_effect_union_in_returned_fn.py
Regression test failed before fix: yes (3 of 4; the fourth pins runtime behaviour)
Fix: the call's full substitution (types and effects) is applied to its return type;
  `substitute` replaces a type variable only by a type, and effect variables inside
  function-type effects by their bound sets (lang/check/callcheck.py, lang/typesys.py).
Commit: 139d451
Status: fixed

BUG-0014
Origin: parser fuzzer (seed 127) after the stdlib tests joined the corpus
Subsystems: parser (let destructuring)
Symptom: `let ()` crashed the parser with an IndexError (empty name list).
Minimal reproduction: tests/regressions/test_bug_0014_empty_destructuring.py
Regression test failed before fix: yes (all 3)
Fix: an empty destructuring pattern is `S.SYNTAX.UNEXPECTED_TOKEN` ("needs at least
  one name") (lang/syntax/parser.py).
Commit: f909cfc
Status: fixed

BUG-0015
Origin: first V3 coverage reread (re-checking LocalFlow in verified mode)
Subsystems: static checker (module import binding)
Symptom: a function or constant imported by name, `import model.{isFinal}`, kept the
  placeholder entry created before signatures were filled, so the checker typed it
  `Dyn`: every call was a false `S.TYPE.DYNAMIC_CALL` error in verified mode (10 in
  LocalFlow, previously misattributed to branch-type joins in TODO.md) and argument
  types and effects of named imports were not checked at all.
Minimal reproduction: tests/regressions/test_bug_0015_brace_import_typing.py
Regression test failed before fix: yes (3 of 4; qualified access was already typed)
Fix: names bound by named imports are recorded and rebound to the filled entries
  after signature construction (lang/check/typecheck.py). LocalFlow now passes
  verified mode with zero errors and its manifest selects verified.
Commit: c596dfb
Status: fixed

BUG-0016
Origin: second independent audit (concurrency auditor, F1)
Subsystems: task groups × control flow (return/break/continue)
Symptom: `return`, `break` or `continue` inside a `parallel` body left the group
  without waiting for quiescence: children ran after the function returned, never
  ran when the program ended, and their failures were lost (V3 5.12.2, 6.8).
Minimal reproduction: tests/regressions/test_bug_0016_parallel_control_transfer.py
Regression test failed before fix: yes (all 3)
Fix: a control transfer ends the body normally; the group quiesces and settles its
  outcome (a child failure still becomes the outward AggregateException), then the
  transfer resumes (lang/runtime/interp/conc.py).
Commit: 4825290
Status: fixed

BUG-0017
Origin: second independent audit (concurrency auditor, F2)
Subsystems: resource scopes × control flow
Symptom: `return` inside a `use` body crashed the interpreter
  (H.RUNTIME.INTERNAL_ERROR: the return unwound through the provider's own frame);
  `break`/`continue` inside a `use` body skipped normal release (resource leak).
Minimal reproduction: tests/regressions/test_bug_0017_use_control_transfer.py
Regression test failed before fix: yes (all 4)
Fix: the scope body captures control transfers as a "transfer" outcome; release
  runs with ScopeExit.Normal; a release failure replaces the transfer as on normal
  exit; otherwise the transfer resumes (lang/runtime/interp/res.py).
Commit: 4825290
Status: fixed

BUG-0018
Origin: second independent audit (concurrency auditor, F3)
Subsystems: name resolution × isolation (closure captures)
Symptom: a closure capturing a binding that the enclosing scope reassigned *after*
  creating the closure was considered sendable and was shared live with a child task;
  a spawn block whose capture was reassigned after the spawn was silently snapshotted.
Minimal reproduction: tests/regressions/test_bug_0018_capture_reassigned_later.py
Regression test failed before fix: yes (2 of 3)
Fix: capture "reassigned" flags are finalised after the whole program is resolved
  (lang/check/resolve.py).
Commit: 4825290
Status: fixed

BUG-0019
Origin: second independent audit (types auditor, T01)
Subsystems: numerics × diagnostics capture (Python leakage)
Symptom: Ints over 4300 digits could not be printed or parsed (CPython's conversion
  limit leaked as H.RUNTIME.INTERNAL_ERROR, exit 4, even while rendering the locals of
  an unrelated abandonment); `Int / Int` overflowing Float and oversized format
  widths/precisions leaked OverflowError/ValueError the same way.
Minimal reproduction: tests/regressions/test_bug_0019_big_int_python_leaks.py
Regression test failed before fix: yes (all 4)
Fix: the runtime lifts the digit limit; Int/Int overflow abandons with
  A.NUMERIC.INVALID_CONVERSION; format width/precision above 1000 abandons with
  A.RUNTIME.INVALID_ARGUMENT (lang/runtime/__init__.py, interp/exprs.py).
Commit: 5d3cef8
Status: fixed

BUG-0020
Origin: second independent audit (types auditor, T02)
Subsystems: structural equality
Symptom: `lang_eq` short-circuited on Python identity, so `a == a` was true but
  `a == b` false for structurally identical frozen values containing NaN — frozen
  values exposed reference identity (V3 5.1.1).
Minimal reproduction: tests/regressions/test_bug_0020_nan_identity_equality.py
Regression test failed before fix: yes
Fix: no identity shortcut for frozen containers (lang/runtime/equality.py).
Commit: 5d3cef8
Status: fixed

BUG-0021
Origin: second independent audit (concurrency auditor, F4)
Subsystems: isolation (frozen graph scan)
Symptom: task handles nested in frozen collections (or captured by a frozen closure)
  crossed task and channel boundaries; the frozen scan only looked for ports.
Minimal reproduction: tests/regressions/test_bug_0021_handle_in_frozen_graph.py
Regression test failed before fix: yes (2 of 3 initial; closure case added with fix)
Fix: the frozen scan rejects reject-policy capabilities and also scans frozen closure
  captures; scanning is enabled once any port or handle exists (lang/runtime/isolation.py,
  interp/conc.py).
Commit: 5d3cef8
Status: fixed

BUG-0022
Origin: second independent audit (concurrency auditor, F5)
Subsystems: resources × cancellation masking
Symptom: normal release was masked only when the scope body had been cancelled; a
  cancellation arriving during the release of a normally completed body cut the
  release short at its first await (resource leak).
Minimal reproduction: tests/regressions/test_bug_0022_release_masking.py
Regression test failed before fix: yes
Fix: release always runs masked; pending cancellation is redelivered after it
  (lang/runtime/interp/res.py).
Commit: 5d3cef8
Status: fixed

BUG-0023
Origin: second independent audit (concurrency auditor, F6)
Subsystems: task groups × external cancellation × observation
Symptom: with external cancellation coinciding with a child failure, firstSuccess and
  collect groups raised plain cancellation and the failure vanished (V3 5.12.11); a
  collect body that threw dropped earlier unobserved child failures (5.12.5).
Minimal reproduction: tests/regressions/test_bug_0023_group_failures_with_cancel.py
Regression test failed before fix: yes (all 3)
Fix: firstSuccess aggregates failures whenever any exist (cancellation pending);
  collect returns its report when children failed (cancellation pending); a throwing
  collect body aggregates unobserved child failures before the body's exception
  (lang/runtime/interp/conc.py).
Commit: 5d3cef8
Status: fixed

BUG-0024
Origin: second independent audit (types auditor, T04)
Subsystems: gradual typing × mutable collections
Symptom: a `MutableList[Str]` passed a `MutableList[Int]` parameter (element-type
  metadata ignored at the boundary), and typed code pushed a dynamically produced Str
  into an annotated `MutableList[Int]` unchecked (V3 7.6.3: writes check before insertion).
Minimal reproduction: tests/regressions/test_bug_0024_typed_mutable_collection_writes.py
Regression test failed before fix: yes (2 of 3)
Fix: boundary checks compare runtime element-type metadata; the checker marks calls on
  annotation-typed mutable collections so Dyn arguments are checked before the call
  (lang/runtime/rtypes.py, lang/check/callcheck.py, lang/runtime/interp/calls.py).
Commit: 3fd2815
Status: fixed

BUG-0025
Origin: second independent audit (types auditor, T05)
Subsystems: gradual typing × generic records
Symptom: `Box[Int](v: "s")` built a Box holding a Str, and reading `b.v` with
  `b: Box[Int]` used a Str as Int; generic record annotations were never enforced.
Minimal reproduction: tests/regressions/test_bug_0025_generic_record_annotations.py
Regression test failed before fix: yes (2 of 3)
Fix: explicit type arguments are checked at construction; T-typed field reads through
  an annotated instantiation get a transient check (lang/check/expr.py,
  lang/runtime/interp/calls.py, exprs.py).
Commit: 3fd2815
Status: fixed

BUG-0026
Origin: second independent audit (types auditor, T06/T07)
Subsystems: gradual typing × function types × effects
Symptom: calling a value whose type came from a written function-type annotation
  checked nothing at run time: wrong arguments passed in draft, wrong results were used
  as the annotated type, and a callable narrowed with `as fn(..) throws E1` let E2 escape.
Minimal reproduction: tests/regressions/test_bug_0026_function_typed_calls.py
Regression test failed before fix: yes (3 of 4, verified by stashing the fix)
Fix: typed calls carry argument/result/effect checks naming the relied-upon annotation;
  `as` counts as an annotation origin (lang/check/callcheck.py, expr.py,
  lang/runtime/interp/calls.py).
Commit: 3fd2815
Status: fixed

BUG-0027
Origin: second independent audit (types auditor, T08)
Subsystems: effect polymorphism at run time
Symptom: a written `throws E` (error-set variable) was permissive at run time, so a
  generic higher-order function could let an unrelated error escape.
Minimal reproduction: tests/regressions/test_bug_0027_effect_variable_runtime.py
Regression test failed before fix: yes
Fix: E is bound per call from the effects of the callable arguments whose annotation
  mentions it; unknown callback effects stay permissive (lang/runtime/interp/calls.py;
  IMPL-005 corrected).
Commit: 3fd2815
Status: fixed

BUG-0028
Origin: second independent audit (types auditor, T03)
Subsystems: contracts (invariant field control) × mutable sub-objects
Symptom: only direct assignment to invariant fields was controlled; an invariant field
  holding a mutable value could be mutated from outside (`b.items.push(1)`,
  `a.inner.v = -50`) or aliased, breaking the invariant silently until a later method
  entry blamed the record. Verified mode accepted it.
Minimal reproduction: tests/regressions/test_bug_0028_invariant_mutable_subobject.py
Regression test failed before fix: yes (3 of 4)
Fix: access to a mutable-valued invariant field is restricted to the record's own
  methods and contracts, statically (S.CONTRACT.INVARIANT_FIELD_ACCESS) and at run time
  (A.CONTRACT.INVARIANT_FIELD_ACCESS); SPEC-014 amended (lang/check/expr.py,
  lang/runtime/interp/exprs.py).
Commit: 3fd2815
Status: fixed

BUG-0029
Origin: second independent audit (concurrency auditor, F7)
Subsystems: resources × closures
Symptom: a closure capturing a resource borrow could escape its scope (as the `use`
  value, into an outer binding, a collection) with no diagnostic in either mode; misuse
  surfaced only when it was later called. tests/conformance/test_resources.py had pinned
  that behaviour (`test_use_after_release_through_escaped_closure`); it was corrected,
  not weakened: the escape is now rejected at the boundary and use-after-release stays
  tested through a draft-mode outer assignment.
Minimal reproduction: tests/regressions/test_bug_0029_borrow_capturing_closures.py
Regression test failed before fix: yes (2 of 3)
Fix: a lambda capturing a borrow is typed `borrow fn(...)`, so all borrow escape rules
  apply; calls through it are typed; `borrow fn` parameters accept callables; the
  runtime rejects a borrow-capturing closure as a scope value (lang/check/expr.py,
  callcheck.py, lang/runtime/frozen.py, interp/res.py, interp/calls.py, rtypes.py).
Commit: 56c8b45
Status: fixed

BUG-0030
Origin: second independent audit (concurrency auditor, F8)
Subsystems: static checker (borrow escapes)
Symptom: verified mode accepted `Some(c)`, `(c, 1)` and a helper storing a borrow
  parameter into a mutable record field; only the runtime caught them.
Minimal reproduction: tests/regressions/test_bug_0030_static_borrow_escapes.py
Regression test failed before fix: yes (both)
Fix: borrows passed to any record/variant constructor (including generic `Some`),
  tuple literals and field assignments are S.RESOURCE.ESCAPE (lang/check/callcheck.py,
  expr.py, walk.py).
Commit: 56c8b45
Status: fixed

BUG-0031
Origin: second independent audit (concurrency auditor, F9)
Subsystems: static checker (provider yield count)
Symptom: the yield-count check missed `if flag { return }` before the yield (return
  treated like throw), a match arm without a yield and a yield inside one branch of an
  `if` initialiser; it rejected a yield in every match arm ("found 2") and
  `while true { yield v; break }`.
Minimal reproduction: tests/regressions/test_bug_0031_yield_count_paths.py
Regression test failed before fix: yes (5 of 11)
Fix: a path analysis over capped yield counts (fall-through/return/break/continue,
  throws dropped, loop fixpoint) replaces the syntactic count (lang/check/yieldflow.py).
Commit: 4078e43
Status: fixed

BUG-0032
Origin: second independent audit (concurrency auditor, F10)
Subsystems: static checker (cleanup effects)
Symptom: one throwing `defer` in a block whose other statements cannot throw made the
  checker require `AggregateException`; verified mode rejected a correct program.
Minimal reproduction: tests/regressions/test_bug_0032_defer_effect_aggregate.py
Regression test failed before fix: yes
Fix: aggregate only when the body can fail or more than one cleanup can fail
  (V3 5.6 table) (lang/check/walk.py).
Commit: 4078e43
Status: fixed

BUG-0033
Origin: second independent audit (concurrency auditor, F11)
Subsystems: cancellation masking × deadlines
Symptom: while cleanup ran masked, a `within` deadline opened by the cleanup itself
  never fired, so cleanup could not bound its own duration (V3 5.6.3, 7.10.11).
Minimal reproduction: tests/regressions/test_bug_0033_cleanup_own_deadline.py
Regression test failed before fix: yes (1 of 2; the other pins outer masking)
Fix: masks are a stack of floors over the task's cancel scopes; only scopes opened
  inside the masked region are deliverable; `within` reports its own deadline while an
  outer masked cancellation stays pending (lang/runtime/tasks.py, interp/core.py, conc.py).
Commit: 4e61bca
Status: fixed

BUG-0034
Origin: second independent audit (concurrency auditor, F12)
Subsystems: channels (endpoint holder tracking)
Symptom: a receive port carried inside a buffered message had no holder, so its channel
  reported NoReceivers although the port would still be delivered and worked.
Minimal reproduction: tests/regressions/test_bug_0034_port_in_transit.py
Regression test failed before fix: yes (1 of 2; the other pins the undeliverable case)
Fix: the carrying channel holds in-transit ports until a receiver takes the message;
  the hold is dropped if the carrier's receivers are all lost (lang/runtime/interp/chan.py).
Commit: 4e61bca
Status: fixed
