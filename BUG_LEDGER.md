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
Commit: (pending)
Status: fixed

BUG-0014
Origin: parser fuzzer (seed 127) after the stdlib tests joined the corpus
Subsystems: parser (let destructuring)
Symptom: `let ()` crashed the parser with an IndexError (empty name list).
Minimal reproduction: tests/regressions/test_bug_0014_empty_destructuring.py
Regression test failed before fix: yes (all 3)
Fix: an empty destructuring pattern is `S.SYNTAX.UNEXPECTED_TOKEN` ("needs at least
  one name") (lang/syntax/parser.py).
Commit: (pending)
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
Commit: (pending)
Status: fixed
