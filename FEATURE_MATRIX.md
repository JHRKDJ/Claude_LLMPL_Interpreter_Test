# FEATURE MATRIX (derived from a complete read of V3)

Evidence paths: `c/` tests/conformance, `n/` tests/negative, `i/` tests/interactions,
`r/NNNN` tests/regressions/test_bug_NNNN_*, `t/` tests/tooling, `u/` tests/unit; Impl
paths are under `lang/` unless stated. Filled by the first V3 coverage sweep; states
were set only where a passing test (or an absence test) exists.

Columns: **V3** = V3 decision status; **§** = V3 section; **Impl** = implementation
location; **Tests** = conformance / negative / interaction test locations;
**State** ∈ NOT_STARTED, IN_PROGRESS, IMPLEMENTED, VERIFYING, COMPLETE,
BLOCKED_BY_REAL_DESIGN_CONFLICT, DEFERRED, OUT_OF_SCOPE; deferred/rejected rows are tracked so their
absence can be verified. Work items are in `WORK_ITEMS.json`.

Abbreviations: D = Decided, DD = Decided direction, P = Provisional, SS =
Specification-stage, OD = Open detail, DEF = Deferred, REJ = Rejected.

## 1. Syntax and source (V3 4.x, 6.1, 7.1)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| SYN-01 | Brace-delimited blocks; indentation not significant | D | 6.1, 7.1.1 | syntax/parser.py | u/test_parser; n/test_static_errors[unclosed_brace] | COMPLETE |  |
| SYN-02 | Newline statements + continuation rules; clear diagnostics over aggressive continuation | DD | 7.1.2 | syntax/lexer.py, parser.py (nl_ctx) | u/test_parser::continuation_*; n/[leading_operator,missing_separator]; r/0006 | COMPLETE | SPEC-001 |
| SYN-03 | `fn`, explicit `self`, postfix optional return annotation | DD | 6.1, 7.1.4 | parser.py fn decl; check/decls.py | c/test_functions_records::methods_*,function_bodies_* | COMPLETE | SPEC-004 |
| SYN-04 | `async fn`; only async functions suspend | D | 6.1, 7.10.2 | parser; runtime/interp/calls.py (A.ASYNC.*); check callcheck | c/test_tasks::sync_function_cannot_suspend*, await_outside_async*; c/test_checker[sync_calls_async,missing_await] | COMPLETE | SPEC-023 |
| SYN-05 | Unicode strings, brace interpolation, escaping, format modifiers, safe display | DD | 7.1.5 | lexer.py strings; interp/exprs.py (_SPEC modifiers); capture.py | c/test_values::strings_interpolation_and_escapes, string_normalisation_is_explicit; u/test_lexer; n/[*interpolation*] | COMPLETE | SPEC-009 |
| SYN-06 | Lambdas: expression + block forms, effect annotations | DD | 7.1.6 | parser lambda; interp/exprs.py eval_Lambda | c/test_functions_records::closures_*; i/test_int017_* | COMPLETE | SPEC-004 |
| SYN-07 | Keyword priors (fn, spawn, await, match, try, pub, use, let, mutable record, requires/ensures) | SS | 7.1.3 | syntax/tokens.py | u/test_lexer::keywords_*; n/[python_def,ternary,increment] | COMPLETE | DECISIONS §A |
| SYN-08 | Expression-oriented blocks (if/match/use/select) | DD | 7.2.1 | interp/stmts.py, exprs.py, res.py, selectx.py | c/test_functions_records::expression_valued_blocks; c/test_resources::scope_is_expression_valued* | COMPLETE | SPEC-004 |
| SYN-09 | Left-to-right evaluation; args before call | DD | 7.2.2 | interp/calls.py eval_args | c/test_functions_records::left_to_right_evaluation | COMPLETE |  |

## 2. Values and data model (V3 5.1, 6.2, 7.3)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| VAL-01 | Int arbitrary precision; Float binary64; Bool non-coercing; Str immutable Unicode; Unit | DD | 6.2, 7.3.3 | runtime/values.py, builtins/numbers.py, strings.py | c/test_values::int_arbitrary_precision, no_mixed_numeric_arithmetic, no_truthiness_* | COMPLETE |  |
| VAL-02 | NaN policy | SS/P | 7.3.3, 9.3#25 | builtins/numbers.py, equality.py | c/test_values::float_ieee_and_display, nan_map_key_abandons, int_float_equality_abandons | COMPLETE | SPEC-010 provisional; SPEC-010 (provisional: IEEE propagation + abandonment on NaN keys/conversions) |
| VAL-03 | Frozen records transitively frozen, structural equality, no identity | D | 5.1.1-3, 7.3.1 | values.py FrozenRecord; frozen.py; equality.py | c/test_functions_records::records_frozen_structural_equality, frozen_record_requires_frozen_fields | COMPLETE |  |
| VAL-04 | Mutable records identity-bearing | D | 5.1.2, 7.3.1 | values.py MutableRecord | c/test_functions_records::mutable_records_identity_bearing | COMPLETE | AMB-007 |
| VAL-05 | Type-level mutability (no per-instance switch) | D | 5.1.4 | parser `mutable record`; check/decls.py | c/test_checker[frozen_field_type, frozen_mutation] | COMPLETE |  |
| VAL-06 | Frozen updates produce new values (`with`) | D | 5.1.6, 7.3.1 | interp/exprs.py eval_WithUpdate | c/test_functions_records::with_update_creates_new_value; n/[invalid_with] | COMPLETE | SPEC-006 |
| VAL-07 | Frozen collections (persistent) + mutable collections; sequence/map/set | D sem | 7.3.2 | builtins/colls.py | c/test_values::frozen_list_persistent_updates, frozen_collections_reject_mutation, mutable_list_identity_and_aliasing | COMPLETE | SPEC-008 |
| VAL-08 | freeze() / mutableCopy() snapshot isolation | D | 5.1.7 | builtins/colls.py freeze/mutableCopy | c/test_values::freeze_snapshot_isolation | COMPLETE |  |
| VAL-09 | Map/set iteration order specified | DD | 7.3.2 | builtins/colls.py (insertion order) | c/test_values::map_insertion_order_and_order_insensitive_equality | COMPLETE | insertion order |
| VAL-10 | Structural equality and hashing incl. nested collections/variants | DD | 7.3.1 | runtime/equality.py | c/test_values::map_insertion_order_*, int_and_float_keys_are_distinct, mutable_keys_rejected | COMPLETE |  |
| VAL-11 | Closed nominal variants | D | 6.2, 3.3 | values.py EnumType; check/exhaustive.py | c/test_functions_records::enums_exhaustive_runtime_backstop, variant_payloads_*; c/test_checker[non_exhaustive_enum] | COMPLETE | SPEC-007 |
| VAL-12 | Option: `T?` = Option[T], `null` = None, no raw null | D | 5.4, 7.3.4 | core_types.py OPTION | c/test_functions_records::option_and_null, option_annotation_checks_payload | COMPLETE |  |
| VAL-13 | Result[T,E] core type | D | 7.3.4 | core_types.py RESULT; builtins/optres.py | c/test_errors::capture_and_result; i/test_int002_* | COMPLETE |  |
| VAL-14 | Str indexing/normalisation defined | DD | 7.3.3 | builtins/strings.py | c/test_values::string_code_points, string_normalisation_is_explicit | COMPLETE | code points, no implicit normalisation; code points, explicit normalized(form) |
| VAL-15 | No class inheritance | D | 2.2 | parser.py foreign-syntax diagnostics | n/test_rejected_and_deferred::no_class_inheritance | COMPLETE | verify absence; absence verified |

## 3. Bindings, state, scope, closures (V3 5.1.5, 5.2, 6.3, 7.4)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| BND-01 | Reassignable bindings; rebinding distinct from mutation | D sem | 5.1.5 | interp/stmts.py; check/resolve.py | c/test_functions_records::let_is_reassignable_const_is_not | COMPLETE | SPEC-002 |
| BND-02 | Optional constant binding | SS | 6.3 | parser `const`; resolve.py | c/test_functions_records::let_is_reassignable_const_is_not; n/[const_reassign] | COMPLETE | `const` |
| BND-03 | Frozen module constants; mutable module globals prohibited | D | 5.2, 7.4.2 | check/resolve.py, interp/link.py | c/test_functions_records::module_constants_frozen, module_level_let_rejected; n/[mutable_global] | COMPLETE |  |
| BND-04 | Uninitialised binding state; no use before initialisation | D/DD | 5.4.3, 6.3 | resolve.py definite assignment; values.Uninit | c/test_functions_records::uninitialised_*; c/test_checker[uninitialised] | COMPLETE |  |
| BND-05 | Closures capture lexical bindings; reassignment marker | DD/P | 7.4.3 | resolve.py captures/nonlocal; capture analysis | c/test_functions_records::closures_capture_and_nonlocal, captured_reassignment_requires_nonlocal | COMPLETE | SPEC-003 |
| BND-06 | State-horizon advisories | P | 7.3.5 | check/advisories.py, callcheck.py | c/test_checker[large_mutable_record, pass_through, invariant_across_await] | COMPLETE | heuristic; heuristic; 3 of the 6 example advisories of 7.3.5 (large state bags, pass-through, mutation before cancellation point) |

## 4. Types and annotations (V3 5.3, 6.4, 7.6)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| TYP-01 | Dynamic default, strong, non-coercing | D | 5.3.1, 5.3.4 | runtime/rtypes.py, equality.py | c/test_values::no_mixed_numeric_arithmetic, string_concat_requires_strings | COMPLETE |  |
| TYP-02 | Written annotations runtime-enforced in both modes | D | 5.3.2-3 | interp/calls.py boundary checks; rtypes.py | i/test_modes::written_annotations_enforced_at_runtime_in_draft | COMPLETE |  |
| TYP-03 | Concrete record annotation nominal | D | 5.3.5 | rtypes.py nominal check | c/test_functions_records::record_annotation_is_nominal | COMPLETE |  |
| TYP-04 | Protocol annotation: immediate shallow shape/effect check | D | 5.3.6, 7.5.2 | rtypes.py protocol shape | c/test_contracts::protocol_shape_check_at_boundary, protocol_arity_mismatch_rejected, protocol_effect_compatibility | COMPLETE |  |
| TYP-05 | Transient checks of nested/generic contents at typed uses/writes | D | 5.3.7, 7.6.3 | check inserts rt_check; interp transient_check | c/test_transient_checks (7 tests) | COMPLETE | IMPL-004 |
| TYP-06 | Return values checked before leaving | D | 5.3.8 | interp/calls.py return check | c/test_functions_records::return_annotation_checked | COMPLETE |  |
| TYP-07 | Dynamic mismatch = abandonment with boundary/annotation/origin diagnostics | D | 5.3.9, 5.3.12, 7.6.5 | interp/core.py make_diag; rtypes.py | c/test_functions_records::dynamic_mismatch_reports_value_origin | COMPLETE |  |
| TYP-08 | Dynamic callables narrowed before verified invocation | D | 5.3.10, 7.7.6 | check/callcheck.py S.TYPE.DYNAMIC_CALL | c/test_checker[dynamic_call]; i/test_modes::dynamic_callable_runs_in_draft_rejected_in_verified | COMPLETE |  |
| TYP-09 | Dynamic values not sendable by default; inspection | D | 5.3.11, 7.6.6 | runtime/isolation.py | i/test_int013_resource_deep_in_argument_graph_rejected_* | COMPLETE |  |
| TYP-10 | Generics: collections, variants, Results, tasks, channels, effects | DD | 6.4 | typesys.py, check/types.py | c/test_functions_records::generic_function_and_record; r/0009, r/0011, r/0013 | COMPLETE | IMPL-006 (type parameters erased at run time) |
| TYP-11 | `Dyn` spelling | SS | 5.3.1 | typesys.PRIMS | c/test_functions_records::type_patterns_on_dyn | COMPLETE | SPEC-005 |
| TYP-12 | Verified: static validation of resolvable annotations | D | 7.6.4 | check/typecheck.py | c/test_checker[static_mismatch_arg, static_mismatch_return, unknown_field, unknown_method] | COMPLETE |  |
| TYP-13 | Exported interface annotations required | DD | 7.1.4 | check/callcheck.py | c/test_checker[missing_annotation_param, missing_annotation_return] | COMPLETE | verified only |
| TYP-14 | Frozen verified values may skip repeated checks | P | 9.2 | — | — | DEFERRED | optimisation; may stay unimplemented with rationale; semantics-neutral optimisation; V3 9.2 leaves representation/invalidation open; checks stay transient and shallow |

## 5. Functions, protocols, contracts (V3 5.10, 6.5, 7.5, 7.8)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| FN-01 | Parameters; argument passing by value category | DD | 6.5, 7.2.2 | interp/calls.py | c/test_functions_records::named_and_default_arguments, arity_error_reports_declaration; c/test_tasks::task_isolation_copies_mutable_arguments | COMPLETE |  |
| FN-02 | Methods with explicit self | DD | 6.5 | interp/calls.py call_member | c/test_functions_records::methods_and_associated_functions; r/0012 | COMPLETE |  |
| PRO-01 | Structural protocol conformance; optional `satisfies` | DD/P | 6.2, 7.5.1 | check/typecheck.py conformance; rtypes.py | c/test_checker[protocol_not_satisfied]; i/test_int007_*; c/test_stdlib::order_protocols_structural | COMPLETE | AMB-001 |
| PRO-02 | Protocol contracts inherited, checked on every invocation | D | 5.10.8, 5.10.11 | interp/calls.py inherited contracts | c/test_contracts::protocol_contracts_inherited_on_every_call, protocol_preconditions_inherited | COMPLETE | AMB-001 |
| PRO-03 | Implementations cannot add public preconditions | D | 5.10.9, 7.8.5 | check/contracts_check.py | c/test_contracts::added_precondition_means_nonconforming; c/test_checker[protocol_added_precondition] | COMPLETE |  |
| PRO-04 | Implementation postconditions supplement | D | 5.10.10 | interp/calls.py | c/test_contracts::implementation_postconditions_supplement | COMPLETE |  |
| PRO-05 | Structural conformance does not imply sendability | D | 8.9 | isolation.py | i/test_int029_mutable_implementation_conforms_but_is_not_sendable | COMPLETE |  |
| CON-01 | requires/ensures in signatures, executable | D | 5.10.1-2 | interp/calls.py contracts | c/test_contracts::requires_blames_caller, ensures_with_result_and_old | COMPLETE |  |
| CON-02 | Restricted contract-expression language | D | 5.10.3, 7.8.2 | check/contracts_check.py | c/test_checker[contract_restricted_io, contract_restricted_index] | COMPLETE | AMB-009; AMB-009; quantifier policy SPEC-014 |
| CON-03 | Non-recursive predicates calling only predicates | D | 5.10.4 | contracts_check.py | c/test_contracts::predicates_in_contracts; c/test_checker[recursive_predicate] | COMPLETE |  |
| CON-04 | old(expr) legality by captured result | D | 5.10.5, 7.8.3 | contracts_check.py; interp old snapshot | c/test_contracts::old_must_be_frozen_static, old_must_be_frozen_dynamic; i/test_int008_* | COMPLETE |  |
| CON-05 | Record invariants; controlled mutation of invariant fields | DD/SS | 5.10.6-7, 7.8.4 | interp invariants; check invariant_field_write | c/test_contracts::*invariant* (6 tests) | COMPLETE | SPEC-014 |
| CON-06 | Exit ordering: save, cleanup, post/invariants; invariant failure supersedes | D | 5.10.12-14, 7.8.6 | interp/calls.py exit ordering | c/test_contracts::cleanup_runs_before_postcondition; i/test_int009_*, test_int020_* | COMPLETE |  |
| CON-07 | Violation always abandonment | D | 5.10.15 | interp contracts -> Abandoned | c/test_contracts::requires_blames_caller, postcondition_failure_blames_implementation | COMPLETE |  |

## 6. Errors, Results, effects (V3 5.7-5.9, 6.6, 7.7)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| ERR-01 | Distinct failure classes (recoverable, cancellation, abandonment, hard, catastrophic) | D | 5.6, 6.6, 7.2.3 | runtime/signals.py (Thrown/Cancelled/Abandoned/HardTermination) | c/test_errors::cancellation_and_abandonment_not_catchable; c/test_runtime_diagnostics::*interrupt* | COMPLETE |  |
| ERR-02 | Declared throws sets; try marker in verified; draft still propagates | D | 3.2, 5.15.3, 7.7.3 | check/callcheck.py effects; interp written throws | c/test_checker[missing_try, undeclared_throws]; c/test_errors::written_throws_clause_enforced_at_runtime, draft_unmarked_call_* | COMPLETE | AMB-005 |
| ERR-03 | Concrete nominal errors; zero-or-one category; closed error enums | D | 5.9, 7.7.7 | parser error/category decls; core_types.py | c/test_errors::catch_by_category, catch_error_enum_case, only_errors_can_be_thrown* | COMPLETE | SPEC-011 |
| ERR-04 | Catch by type/category; no broad catch-all | D | 5.7.5, 7.7.3 | interp/res.py try/catch; resolve.py BROAD_CATCH | c/test_errors::catch_by_category, uncaught_types_propagate_through_catch; n/test_rejected_and_deferred::no_broad_untyped_catch | COMPLETE |  |
| ERR-05 | Typed fallback; unqualified fallback only for one known type | D | 5.7.5 | callcheck fallback_qual; interp | c/test_errors::else_fallback_single_known_type; c/test_checker[broad_fallback_multi]; u/test_runtime_annotations | COMPLETE |  |
| ERR-06 | Result for stored failure; cannot both throw and return Result | D | 5.7.2-3, 7.7.4 | callcheck S.EFFECT.THROWS_AND_RESULT | c/test_checker[throws_and_result]; c/test_errors::capture_and_result | COMPLETE |  |
| ERR-07 | Explicit throw↔Result conversion | SS | 5.7.4 | capture/propagate/orThrow (exprs.py, optres.py) | c/test_errors::capture_and_result, or_throw_and_propagate | COMPLETE | SPEC-012 |
| ERR-08 | Err provenance: type, code, creation span, propagation chain, task lineage, bounded context | D | 7.7.8 | signals.ErrorProvenance; error_diag | c/test_errors::propagation_chain_recorded, err_context_provenance | COMPLETE |  |
| ERR-09 | Minimal effect polymorphism: error-set variables, unions, forwarding | D | 5.8, 7.7.5, 8.3 | callcheck effect variables; typesys.substitute_effect | c/test_checker[effect_variable_forwarding]; i/test_int017_*; r/0013 | COMPLETE | SPEC-013 |
| ERR-10 | Checked alternatives for expected branches | DD | 5.7.8, 7.7.2 | builtins get/checkedDiv/tryReceive | c/test_values::checked_get, division_by_zero_int_abandons_checked_alternative | COMPLETE |  |
| ERR-11 | Top-level unhandled exception: cleanup, diagnostic, failure exit, not abandonment | D | 5.7.10, 7.7.9 | interp/__init__.py R.ERROR.UNHANDLED | c/test_errors::top_level_unhandled_is_not_abandonment_and_runs_cleanup | COMPLETE |  |
| ERR-12 | AggregateException: general non-empty aggregate with provenance | D | 5.6, 7.9.8 | interp/stmts.py aggregate | c/test_errors::aggregate_exception_catchable_and_inspectable, defer_failure_during_exception_aggregates | COMPLETE |  |
| ERR-13 | Abandonment uncatchable in failed task | D | 5.6.4, 6.6 | signals.Abandoned not catchable | c/test_errors::cancellation_and_abandonment_not_catchable; n/test_rejected_and_deferred::no_recoverable_abandonment | COMPLETE |  |
| ERR-14 | Hard termination escalation | DD | 5.6.5, 7.10.11 | tooling/cli.py interrupt; conc.py H.RUNTIME.HARD_TERMINATION | c/test_runtime_diagnostics::second_interrupt_escalates_to_hard_termination | COMPLETE | process-level escalation (exit 4) |
| ERR-15 | Catching category does not make open set exhaustive | D | 5.9.6 | check/exhaustive.py | c/test_checker[non_exhaustive_open_type] | COMPLETE |  |
| ERR-16 | Multiple category membership | DEF | 5.9.5 | — | — | DEFERRED | runtime stores categories as a tuple so later extension is not foreclosed |

## 7. Resources and cleanup (V3 5.5, 5.6, 6.7, 7.9)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| RES-01 | Resource providers: acquire, exactly one yield, release, abandonment registration | D | 5.5.3, 7.9.2 | interp/res.py ProviderCtx | c/test_resources::scope_is_expression_valued*, provider_must_yield_exactly_once; r/0001 | COMPLETE | IMPL-003 |
| RES-02 | Providers callable only as scope initialisers | D | 5.5.4 | callcheck; interp | c/test_resources::provider_only_in_use, provider_only_in_use_dynamic | COMPLETE |  |
| RES-03 | Resource values cannot be bound/returned/stored/captured/sent/passed to tasks | D | 5.5.5 | callcheck escape; isolation.py | c/test_checker[resource_escape_let]; c/test_channels::resource_cannot_be_sent; i/test_int019_borrow_cannot_be_spawned | COMPLETE |  |
| RES-04 | Expression-valued scopes; release can change outward outcome | D | 5.5.6, 7.9.5 | interp/res.py | c/test_resources::release_failure_after_success_is_outward; i/test_int011_* | COMPLETE |  |
| RES-05 | Borrows: non-escaping, same-task, may cross await | D | 5.5.7-8, 7.9.4 | callcheck borrow rules; res.py borrow_target | c/test_resources::borrow_*; i/test_int019_* | COMPLETE |  |
| RES-06 | Normal release on return/exception/cancellation; knows exit class; no suppression | D | 5.5.9 | res.py ScopeExit | c/test_resources::release_on_recoverable_exception_knows_exit_class; i/test_int010_* | COMPLETE |  |
| RES-07 | Abandonment-safe release only, restricted actions/inputs | D | 5.5.10-12 | res.py onAbandon | c/test_resources::on_abandon_*; i/test_int030_*; r/0003 | COMPLETE |  |
| RES-08 | Release failure during abandonment appended diagnostically | D | 5.5.13 | res.py _run_abandon_actions | c/test_runtime_diagnostics::release_failure_during_abandonment_is_appended_not_replacing | COMPLETE |  |
| RES-09 | `defer` non-resource cleanup, not on abandonment, LIFO, async under masking | D | 5.6, 7.9.6 | interp/stmts.py defer | c/test_errors::defer_lifo_and_block_scoped, abandonment_skips_defer; c/test_tasks::cancellation_not_catchable_and_masked_cleanup_can_await | COMPLETE | SPEC-016 |
| RES-10 | Cleanup-failure combination table | D | 5.6 | stmts.py cleanup combination | c/test_errors::defer_failure_*; c/test_resources::release_failure_*; c/test_runtime_diagnostics::cleanup_failure_while_cancelling_* | COMPLETE |  |
| RES-11 | Scope-width advisories | P | 7.9.7 | callcheck.scope_width_advice | c/test_runtime_diagnostics::scope_too_wide_advisory, scope_used_until_the_end_has_no_advisory | COMPLETE | best-effort; best-effort syntactic liveness |
| RES-12 | No structural Closeable/RAII | REJ | 6.14, 9.5 | — | n/test_rejected_and_deferred::no_structural_closeable_raii | COMPLETE | verify absence; absence verified |
| RES-13 | Resource-owning records | DEF | 5.5.14 | — | — | DEFERRED | |

## 8. Structured concurrency and cancellation (V3 5.12, 6.8, 7.10)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| TSK-01 | Structured task groups; no fire-and-forget | D | 6.8, 7.10.1 | interp/conc.py parallel/spawn | c/test_tasks::spawn_outside_parallel_rejected; c/test_checker[spawn_outside_group, handle_escape_*] | COMPLETE | AMB-008 |
| TSK-02 | One substrate, four modes: fail-fast, collect-all, race, first-success | D | 5.12.1 | conc.py group modes | c/test_tasks (failfast/collect/race/firstSuccess tests) | COMPLETE | SPEC-017 |
| TSK-03 | Quiescence before exit | D | 5.12.2, 7.10.3 | conc.py quiescence | c/test_tasks::quiescence_before_exit | COMPLETE |  |
| TSK-04 | Stable handles; await exposes concrete exception | D | 5.12.3, 7.10.9 | conc.py handles | c/test_tasks::awaited_and_caught_child_failure_is_observed; c/test_runtime_diagnostics::awaiting_an_abandoned_child_* | COMPLETE |  |
| TSK-05 | Observation: caught/captured not re-reported; unhandled/unawaited aggregated once | D | 5.12.4-5, 8.10 | conc.py observation | c/test_tasks::awaited_*, unawaited_failure_appears_at_boundary, two_failures_one_handled; i/test_int016_* | COMPLETE | AMB-002 |
| TSK-06 | Fail-fast: AggregateException even for one child | D | 7.10.4 | conc.py failfast | c/test_tasks::failfast_one_child_failure_is_aggregate_and_cancels_siblings | COMPLETE |  |
| TSK-07 | Child abandonment dominates fail-fast/race/first-success; TaskGroupFailure | D | 5.12.6, 5.12.9 | conc.py A.TASK.GROUP_FAILURE | c/test_tasks::child_abandonment_dominates_and_abandons_parent; c/test_runtime_diagnostics::task_group_failure_lists_cancelled_siblings | COMPLETE |  |
| TSK-08 | Collect-all returns TaskGroupReport including abandonment as data | D | 5.12.7-8, 7.10.5 | conc.py TaskGroupReport | c/test_tasks::collect_returns_report_with_abandonment_as_data | COMPLETE |  |
| TSK-09 | Race | D | 7.10.6 | conc.py race | c/test_tasks::race_winner_cancels_losers, race_winning_failure_is_aggregate | COMPLETE |  |
| TSK-10 | First-success | D | 7.10.7 | conc.py firstSuccess | c/test_tasks::first_success_* | COMPLETE |  |
| TSK-11 | Lexical task tree preserved; flattened views | D | 5.12.10 | tasks.py paths; render_text.leaves | c/test_tasks::nested_groups_and_task_paths; t/test_cli::diagnostic_display_modes | COMPLETE | nested JSON canonical; flattened quiet view |
| TSK-12 | External cancellation + child failure both preserved | D | 5.12.11, 8.11 | conc.py _propagate_external_cancel | c/test_tasks::external_cancellation_plus_group_failure_preserved; r/0002 | COMPLETE |  |
| TSK-13 | Diagnostic ordering by task path, not arrival time | D | 7.10.3 | conc.py _order | c/test_tasks::failure_ordering_follows_task_paths_not_arrival_time | COMPLETE |  |
| CAN-01 | Cooperative cancellation at visible points; `cancel.check()` | D | 7.10.2 | interp/core.py check_cancel | c/test_tasks::cancel_check_in_cpu_loop | COMPLETE | AMB-004 |
| CAN-02 | Cancellation not catchable/discardable | D | 5.7.9, 7.10.11 | signals.Cancelled | c/test_errors::cancellation_and_abandonment_not_catchable | COMPLETE |  |
| CAN-03 | Cleanup masking + redelivery | D | 6.8 | tasks.py mask; conc.py | c/test_tasks::cancellation_not_catchable_and_masked_cleanup_can_await | COMPLETE |  |
| CAN-04 | Invariants checked before cancellation leaves operation | D | 6.8, 8.8 | interp invariants on cancel exit | i/test_int009_* | COMPLETE |  |
| CAN-05 | Stuck-cleanup diagnostic; hard-termination escalation | DD | 7.10.11 | conc.py W.CLEANUP.STUCK; cli.py | c/test_runtime_diagnostics::slow_cleanup_*, cleanup_that_can_never_finish_*, *interrupt* | COMPLETE |  |
| CAN-06 | Verified reports async regions without cancellation points | D | 5.15.6 | walk.py check_cancel_points | c/test_checker[no_cancellation_point_*] | COMPLETE |  |
| CAN-07 | `within deadline` structured timeout | DD ("may") | 7.12.9 | conc.py eval_Within | c/test_tasks::within_* | COMPLETE | SPEC-017 |

## 9. Isolation / sendability (V3 5.11, 7.10.10)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| ISO-01 | Classification before child start/message commit | D | 5.11 | isolation.Transfer before start/commit | c/test_tasks::task_isolation_copies_mutable_arguments; i/test_int013_* | COMPLETE |  |
| ISO-02 | Share frozen; graph-copy mutable; reject resources/borrows/unsafe | D | 5.11 | isolation.py | c/test_tasks::task_isolation_*, task_result_is_classified_at_the_boundary; c/test_channels::mutable_messages_are_copied | COMPLETE |  |
| ISO-03 | Graph copy preserves cycles/aliases, no alias back | D | 5.11, 7.10.10 | isolation.py memo graph copy | c/test_tasks::graph_copy_preserves_cycles_and_aliases; i/test_int013_cyclic_* | COMPLETE |  |
| ISO-04 | Closures: sendable captures share; mutable captures reject | D | 5.11, 7.4.3 | isolation.py closures; conc.py captures | c/test_tasks::spawn_block_*, closure_with_mutable_capture_not_sendable | COMPLETE | SPEC-003 |
| ISO-05 | Ports share as frozen capabilities; controller retained; handles scoped | D/SS | 5.11 | channels.py ports; isolation.py | c/test_channels::controller_not_sendable_ports_are; c/test_checker[not_sendable_controller] | COMPLETE | AMB-006 |
| ISO-06 | Dynamic values: runtime graph inspection | D | 5.11, 8.2 | isolation.Transfer on Dyn graphs | i/test_int013_resource_deep_in_argument_graph_* | COMPLETE |  |
| ISO-07 | Large-copy advisories | DD | 5.11, 7.10.10 | conc.py large_copy_advisory | i/test_int021_large_copy_advisory; c/test_tasks::large_copy_advisory_names_size_root_and_alternatives | COMPLETE |  |
| ISO-08 | No user copy hooks | D/DEF | 7.10.10, 9.4 | — | (no hook API exists; isolation.py copies structurally) | COMPLETE | verify absence; absence verified by code inspection |

## 10. Channels (V3 5.13, 6.9, 7.11)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| CHN-01 | MPMC competing-consumer, exactly-once delivery | D | 5.13.1-2 | runtime/channels.py; interp/chan.py | c/test_channels::competing_consumers_each_message_once | COMPLETE |  |
| CHN-02 | Controller + send/receive ports; ports frozen sendable duplicable | D sem | 5.13.4-5, 7.11.2 | channels.py Controller/ports | c/test_channels::controller_not_sendable_ports_are | COMPLETE | SPEC-018 |
| CHN-03 | Capacities: rendezvous (default), buffered(n), unbounded | D | 5.13.6-8 | channels.py capacity | c/test_channels::rendezvous_*, buffered_capacity_and_backpressure, closure_is_permanent | COMPLETE |  |
| CHN-04 | Closure permanent; endpoint loss distinctions | D | 5.13.9-11 | chan.py closure/endpoint loss | c/test_channels::close_drains_*, no_receivers_*, no_senders_*; i/test_int014_* | COMPLETE | AMB-006 |
| CHN-05 | Blocking ops cancellation points; commit atomicity | D | 5.13.12-13 | chan.py commit | c/test_channels::cancellation_before_commit_sends_nothing, cancellation_after_commit_keeps_the_committed_message | COMPLETE |  |
| CHN-06 | Nonblocking try operations | DD | 6.9 | chan.py trySend/tryReceive | c/test_channels::try_send_try_receive | COMPLETE |  |
| CHN-07 | Same-task order; global commit sequence | D | 5.13.14 | channels.py next_seq | c/test_channels::same_task_order_preserved | COMPLETE |  |
| CHN-08 | Mutable messages copied once after reservation, before commit | D | 5.13.15, 7.11.8, 8.12 | chan.py copy_message | c/test_channels::mutable_messages_are_copied; i/test_int021_* | COMPLETE |  |
| CHN-09 | Diagnostic event history unavailable to program | DD | 5.13.16, 7.11.5 | channels.py record() (diagnostic only) | c/test_channels::channel_events_in_deadlock_diagnostic; n/test_rejected_and_deferred::channel_event_history_is_not_observable_by_programs | COMPLETE |  |
| CHN-10 | Broadcast, frozen-only | DD | 5.13.3 | chan.py Broadcast | c/test_channels::broadcast_* | COMPLETE |  |
| CHN-11 | FIFO waiter queues; cancellation removes waiter | P | 5.14.18, 7.11.7 | channels.py waiter deques | c/test_channels::waiter_queue_fifo_cancellation_removes_and_reregistration_joins_back | COMPLETE | provisional FIFO |
| CHN-12 | Unbounded growth advisories | DD | 5.13.8 | chan.py W.CHANNEL.UNBOUNDED_GROWTH | c/test_runtime_diagnostics::unbounded_channel_growth_advisory; c/test_channels::deadlock_on_full_buffer_notes_capacity_dependence | COMPLETE | occupancy threshold 10000 |
| CHN-13 | Mutable broadcast | DEF | 9.4 | — | — | DEFERRED | |

## 11. Selection (V3 5.14, 6.10, 7.12)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| SEL-01 | Participants: send, receive, task completion, deadline, closure outcome | D | 5.14.1 | interp/selectx.py | c/test_select (20 tests) | COMPLETE |  |
| SEL-02 | No arbitrary async branches | D | 5.14.2 | parser select branches | n/test_rejected_and_deferred::no_default_branch_*_and_no_arbitrary_async_branch | COMPLETE |  |
| SEL-03 | Static branch syntax, expression-valued | DD | 5.14.3 | parser; selectx.py | c/test_select::select_receive_from_ready_channel | COMPLETE | SPEC-019 |
| SEL-04 | Pure/precomputed branch setup | D | 5.14.4 | check/selectcheck.py | c/test_checker[select_impure_setup] | COMPLETE |  |
| SEL-05 | Atomic single commit; losers no effect | D | 5.14.5-6 | selectx.py claim | c/test_select::losing_branches_have_no_effect, send_branch_commits_once | COMPLETE |  |
| SEL-06 | Rotating fairness cursor per site/activation; N-bound | DD/P | 5.14.7-8 | selectx.py cursor | c/test_select::rotating_fairness_no_starvation, fairness_cursor_is_per_activation | COMPLETE |  |
| SEL-07 | Priority form + starvation diagnostics | D | 5.14.9 | selectx.py priority; selectcheck W.SELECT.STARVATION | c/test_select::priority_select_prefers_source_order; c/test_checker[select_starvation] | COMPLETE |  |
| SEL-08 | Seeded randomisation in stress mode only | D | 5.14.10 | scheduler.choose_index | c/test_select::seeded_random_tie_breaking | COMPLETE |  |
| SEL-09 | Select cancellation semantics | D | 5.14.11 | selectx.py | c/test_select::select_cancellation_before_commit_consumes_nothing; i/test_int015_* | COMPLETE |  |
| SEL-10 | Selecting a task doesn't cancel others | D | 5.14.12 | selectx.py task branch | c/test_select::task_completion_branch_does_not_cancel_other_tasks; i/test_int023_* | COMPLETE |  |
| SEL-11 | No default branch; `select now` with none-ready | D | 5.14.13 | parser select now | c/test_select::select_now_none_ready, blocking_select_has_no_default_branch | COMPLETE |  |
| SEL-12 | Absolute deadlines; relative sugar; reset diagnostics | D | 5.14.14, 8.16 | selectx.py deadlines; selectcheck reset | c/test_select::select_deadline_after_and_at; i/test_int024_* | COMPLETE |  |
| SEL-13 | Guards: precomputed frozen booleans, read once | D | 5.14.15, 8.17 | selectx.py guards | c/test_select::guards_disable_branches; i/test_int025_* | COMPLETE |  |
| SEL-14 | Closed outcomes explicit; loop warnings | D | 5.14.16, 8.13 | selectx.py closed; selectcheck closed loop | c/test_select::closed_branch_explicit_outcome, closed_receive_without_closed_branch_throws; r/0008 | COMPLETE |  |
| SEL-15 | Dynamic homogeneous helpers | DD | 5.14.17, 7.12.13 | selectx.py selectReceive/selectTask | c/test_select::dynamic_select_* | COMPLETE |  |
| SEL-16 | Endpoint FIFO waiter queues | P | 5.14.18 | channels.py waiter deques | c/test_channels::waiter_queue_fifo_* | COMPLETE | provisional |
| SEL-17 | Bounded selection event ring buffer | DD | 5.14.19, 7.12.14 | selectx.record_select; task.select_ring | c/test_select::select_ring_buffer_recorded_in_diagnostics; i/test_int022_* | COMPLETE |  |
| SEL-18 | Dynamic heterogeneous selection | DEF | 9.4 | — | — | DEFERRED | |
| SEL-19 | Numeric priorities | DEF | 9.4 | — | — | DEFERRED | |

## 12. Draft/verified modes (V3 5.15, 7.6.4)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| MOD-01 | Manifest default mode + CLI override | D | 5.15.1 | modules/project.py; cli.py --mode | i/test_modes::project_manifest_selects_mode | COMPLETE |  |
| MOD-02 | Draft accepts incomplete source; diagnoses obligations | D | 5.15.2 | check severity policy | i/test_modes::draft_runs_with_obligation_warnings_verified_refuses | COMPLETE |  |
| MOD-03 | Unmarked throwing call still propagates in draft | D | 5.15.3 | interp propagation | i/test_modes::unmarked_failure_still_propagates_in_draft | COMPLETE |  |
| MOD-04 | Runtime safety rules active in draft | D | 5.15.4 | runtime checks mode-independent | i/test_modes::task_isolation_active_in_draft, contracts_active_in_draft, written_annotations_* | COMPLETE |  |
| MOD-05 | Verified static obligations | D | 5.15.5 | check oblig policy | c/test_checker (obligation table) | COMPLETE |  |
| MOD-06 | Release requires verified | D | 5.15.7 | cli.py --release | i/test_modes::release_requires_verified, release_build_rejects_*; t/test_cli::release_requires_verified | COMPLETE |  |
| MOD-07 | Modes do not change meaning | D | 5.15.8 | IMPL-004/005 | i/test_modes::same_annotation_failure_in_verified_when_value_is_truly_dynamic | COMPLETE |  |

## 13. Modules and imports (V3 2.4, 5.16, 6.11, 7.4.1, 8.19)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| MDL-01 | One file one module; directory modules | D/SS | 6.11 | modules/loader.py | c/test_functions_records::directory_module, imports_and_exports | COMPLETE | SPEC-020 |
| MDL-02 | Exported + module-private only | DD | 6.11, 7.4.1 | resolve.py visibility | n/test_static_errors::private_name_across_modules | COMPLETE |  |
| MDL-03 | Absolute paths | D | 6.11 | loader.py | c/test_functions_records::imports_and_exports | COMPLETE |  |
| MDL-04 | Unresolved names: diagnostic with candidates; visible auto-insert from known deps | D | 2.4, 7.4.1, 8.19 | resolve.py suggestions; tooling/fixes.py | c/test_functions_records::unresolved_name_suggests_import; t/test_cli::check_fix_*; i/test_int027_* | COMPLETE | AMB-010 |
| MDL-05 | New dependencies only via explicit manifest/lockfile | D | 5.16.4 | loader.py UNKNOWN_DEPENDENCY | n/test_static_errors::unknown_dependency_is_never_installed | COMPLETE |  |
| MDL-06 | Runtime init cycles rejected with full trace | D | 6.11 | interp/link.py const init | c/test_functions_records::const_init_cycle_detected | COMPLETE |  |
| MDL-07 | Type/declaration cycle policy | OD/SS | 6.11 | loader/typecheck (declaration cycles allowed) | r/0015::named_import_inside_lambda_and_cycle; LocalFlow (engine<->jobs cycle) | COMPLETE | SPEC-020 |
| MDL-08 | Runtime loading for REPL/agents; explicit reload | D | 6.11, 7.14.4 | tooling/repl.py | t/test_repl::load_and_explicit_reload, redefinition_is_explicit_* | COMPLETE |  |

## 14. Diagnostics (V3 6.12, 7.13)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| DGN-01 | Structured objects independent of rendering | D | 6.12, 7.13.3 | diagnostics/model.py | t/test_cli::check_json_is_machine_readable | COMPLETE |  |
| DGN-02 | Hierarchical codes; JSON outcome/domain/reason | DD | 7.13.2 | diagnostics/codes.py, render_json.py | u/test_docs_consistency::cited_codes_are_registered; t/test_cli | COMPLETE | SPEC-022 |
| DGN-03 | Multi-span, notes, help, task/resource/channel provenance | DD | 7.13.3, 7.13.6 | model.py provenance fields | c/test_errors::abandonment_report_has_frames_and_locals; c/test_channels::channel_events_in_deadlock_diagnostic | COMPLETE |  |
| DGN-04 | Bounded, cycle-safe, side-effect-free, secret-aware local values | D | 7.13.4, 8.20 | runtime/capture.py | c/test_errors::secret_redaction_in_locals; i/test_int028_* | COMPLETE |  |
| DGN-05 | Result provenance | D | 7.7.8 | signals.ErrorProvenance | c/test_errors::err_context_provenance | COMPLETE |  |
| DGN-06 | Concurrent diagnostics: lexical tree + flattened leaves | D | 7.13.6 | conc.py children; render_text.leaves | t/test_cli::diagnostic_display_modes; c/test_runtime_diagnostics::unhandled_aggregate_* | COMPLETE |  |
| DGN-07 | Channel/select diagnostics | DD | 6.12 | chan.py provenance; select ring | c/test_select::select_ring_buffer_*; c/test_channels::channel_events_* | COMPLETE |  |
| DGN-08 | Parser/checker multi-error recovery, root prominent, cascades noted | D | 7.13.7 | parser sync_stmt; resolve cascades | n/test_static_errors::syntax_errors_are_recovered_*; u/test_parser::recovery_*; r/0007 | COMPLETE |  |
| DGN-09 | Modes: default, quiet, deep, JSON | DD | 6.12 | render_text modes; cli flags | t/test_cli::diagnostic_display_modes | COMPLETE |  |
| DGN-10 | Performance/render budgets with explicit truncation | P | 7.13.5 | capture.Budget; render_text.RenderBudget | c/test_runtime_diagnostics::default_view_caps_*, exhausted_render_budget_*; i/test_int028_long_values_bounded | COMPLETE | render/capture budgets implemented; execution-overhead targets (25%/2x) not benchmarked (no instrumentation-free baseline) |
| DGN-11 | Fix suggestions are visible patches | D | 7.13.7 | tooling/fixes.py | t/test_cli::check_fix_inserts_known_import, check_fix_diff_does_not_write | COMPLETE |  |

## 15. Toolchain (V3 6.13, 7.14)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| TL-01 | CLI run/check/format/repl/test with mode & diagnostic options | DD | 7.14.2 | tooling/cli.py | t/test_cli (12 tests) | COMPLETE |  |
| TL-02 | Formatter canonical, deterministic, idempotent; patches | D | 6.1, 7.14.3 | lang/format | t/test_cli::format_*; fuzz/test_formatter_fuzz (860) | COMPLETE |  |
| TL-03 | REPL first-class with runtime loading | D | 7.14.4 | tooling/repl.py | t/test_repl (8 tests) | COMPLETE | SPEC-024 |
| TL-04 | Seeded schedule stress testing; seed recorded on failure | DD | 7.14.5 | scheduler random; testrunner | t/test_cli::test_command_and_seeded_stress; c/test_runtime_diagnostics::random_schedule_failure_records_seed_* | COMPLETE |  |
| TL-05 | Python differential oracle on declared domain | D | 5.16.5-8, 7.16.4 | examples/localflow/reference_model | examples/localflow/blackbox_tests (216) | COMPLETE | applied to LocalFlow |
| TL-06 | Test framework | SS | 9.3#22 | tooling/testrunner.py `test` decls | t/test_cli::test_command_*, test_json | COMPLETE | SPEC-021; SPEC-025 |

## 16. Core / standard library boundary (V3 6.14, 7.15)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| STD-01 | File resource providers | std | 6.14 | builtins/fs.py | c/test_resources::fs_*; i/test_int030_* | COMPLETE |  |
| STD-02 | JSON, math, datetime/time, regex, strings | std | 6.14 | builtins/jsonmod, mathmod, regexmod, datetimemod, strings | c/test_stdlib::regex_*, datetime, json_and_math | COMPLETE | regex delegates to Python `re` (documented leakage boundary); IMPL-007 (regex = Python re syntax) |
| STD-03 | Ordinary protocols Comparable/Hashable/Iterable | std | 6.14 | lang/stdlib/order.lang | c/test_stdlib::order_* | COMPLETE |  |
| STD-04 | Standard concrete errors and categories | std | 6.14 | core_types.py errors/categories | c/test_errors::catch_by_category; c/test_stdlib::invalid_pattern_is_recoverable_data_error | COMPLETE |  |
| STD-05 | Channel helpers: fan-in, receive-until-closed, request-response, homogeneous selection | std | 6.14, 7.11.9 | lang/stdlib/chan.lang; selectx helpers | c/test_stdlib::chan_*; c/test_select::dynamic_select_* | COMPLETE |  |
| STD-06 | Network/HTTP/process/database providers | std | 6.14 | — | — | OUT_OF_SCOPE | environment has no services; lowest priority, decide during audit; IMPL-007: network/HTTP/process/database providers not provided (no services; no new core mechanism needed) |

## 17. Interactions (V3 Part VIII) → TEST-INT-* work items

8.1 dynamic×protocols×contracts · 8.2 dynamic×tasks/channels · 8.3 effects×higher-order ·
8.4 exceptions×Results×channels · 8.5 resources×async · 8.6 resources×abandonment ·
8.7 resources×expression blocks×contracts · 8.8 mutable×invariants×cancellation ·
8.9 protocol contracts×mutable impls · 8.10 handles×aggregation · 8.11 external
cancellation×group failure · 8.12 channels×copy×backpressure · 8.13 closure×select loops ·
8.14 fairness×diagnostics · 8.15 select×task lifetimes · 8.16 relative timeout×loops ·
8.17 guards×mutable state · 8.18 modules×state×tasks · 8.19 auto-import×reproducibility ·
8.20 diagnostics×privacy · 8.21 Python differential testing (LocalFlow oracle).

**Evidence:** TEST-INT-001..030 in tests/interactions/test_interactions_{a,b,c}.py (state
COMPLETE in WORK_ITEMS.json); 8.21 is examples/localflow (oracle + 216 black-box tests).

## 18. Deferred / rejected (verify absence, do not implement)

Deferred (9.4): resource-owning records; multiple categories; module-state facility;
algebraic effects; dynamic heterogeneous select; mutable broadcast; numeric priorities;
general pure-function effect; user copy hooks; fixed-width ints; reflection/metaprogramming;
operator overloading beyond narrow core; FFI; deterministic replay across I/O.
Rejected (9.5): class inheritance; Closeable RAII; affine/move semantics; final-reference
cleanup; advisory-only annotations; guarded/proxy gradual typing; automatic coercion;
unchecked exceptions; Java-style checked exceptions without forwarding; Go-style error
values everywhere; throw+Result functions; recoverable abandonment; broad untyped
catch; structural error matching; theorem-proving contracts; general purity inference;
mutable globals; locks; channels as lifetime model; universal channel mode; implicit
unbounded default; reopenable channels; arbitrary async select; readiness-only select;
permanent source-order default; random default; opaque global round-robin; blocking
select default branch; reactive guards; silent removal of closed branches; dynamic
heterogeneous select; dual representations; silent dependency installation.

**Evidence of absence:** tests/negative/test_rejected_and_deferred.py (exact codes for each
construct an LLM might reach for), plus rows VAL-15, RES-12, ISO-08, CHN-09 above.
