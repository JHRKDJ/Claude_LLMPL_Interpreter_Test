"""Registry of stable hierarchical diagnostic codes (V3 7.13.2).

Every code emitted anywhere in the toolchain must be registered here with a one-line
description; `code()` raises on unknown codes so typos cannot silently invent new
codes. Tests assert the registry is well-formed.
"""
from __future__ import annotations

from .model import Code, OUTCOME_NAMES

CODES: dict[str, str] = {
    # ---- syntax (static) ----
    "S.SYNTAX.UNEXPECTED_TOKEN": "a token that cannot start or continue the construct",
    "S.SYNTAX.UNTERMINATED_STRING": "string literal not closed before end of line/file",
    "S.SYNTAX.UNTERMINATED_COMMENT": "block comment not closed",
    "S.SYNTAX.INVALID_ESCAPE": "unknown escape sequence in string literal",
    "S.SYNTAX.INVALID_NUMBER": "malformed numeric literal",
    "S.SYNTAX.INVALID_CHARACTER": "character that is not part of the language",
    "S.SYNTAX.UNCLOSED_DELIMITER": "opening bracket/brace/paren without a matching close",
    "S.SYNTAX.MISMATCHED_DELIMITER": "closing delimiter does not match the opening one",
    "S.SYNTAX.LEADING_OPERATOR": "line starts with a binary operator (no implicit continuation)",
    "S.SYNTAX.EXPECTED_EXPRESSION": "an expression was required",
    "S.SYNTAX.EXPECTED_TYPE": "a type was required",
    "S.SYNTAX.EXPECTED_PATTERN": "a pattern was required",
    "S.SYNTAX.EXPECTED_BLOCK": "a braced block was required",
    "S.SYNTAX.MISSING_SEPARATOR": "statements on one line must be separated",
    "S.SYNTAX.INVALID_ASSIGNMENT_TARGET": "left side of assignment is not assignable",
    "S.SYNTAX.MISPLACED_CONSTRUCT": "construct not allowed in this position",
    "S.SYNTAX.UNSUPPORTED_SYNTAX": "syntax from another language that this language does not have",
    "S.SYNTAX.INTERPOLATION": "malformed string interpolation",
    # ---- names / modules ----
    "S.NAME.UNRESOLVED": "name is not defined in scope or imports",
    "S.NAME.DUPLICATE": "name declared twice in the same scope",
    "S.NAME.CAPTURED_REASSIGN": "closure reassigns a captured binding without `nonlocal`",
    "S.NAME.CONST_REASSIGN": "assignment to a const binding",
    "S.NAME.UNINITIALISED": "binding read before definite initialisation",
    "S.NAME.NOT_A_TYPE": "name used as a type does not denote a type",
    "S.NAME.PRIVATE": "name is module-private in its defining module",
    "S.NAME.NONLOCAL_INVALID": "`nonlocal` target is not an enclosing function binding",
    "S.MODULE.NOT_FOUND": "imported module does not exist in project, stdlib or pinned deps",
    "S.MODULE.INIT_CYCLE": "module constant initialisers depend on each other cyclically",
    "S.MODULE.MUTABLE_GLOBAL": "module-level state must be frozen constants",
    "S.MODULE.MANIFEST": "manifest/lockfile problem",
    "S.MODULE.UNKNOWN_DEPENDENCY": "import names a package that is not a pinned dependency",
    "S.MODULE.NO_MAIN": "program has no `main` function",
    # ---- static types ----
    "S.TYPE.STATIC_MISMATCH": "statically known type is inconsistent with the expected type",
    "S.TYPE.UNKNOWN_FIELD": "record/enum has no such field",
    "S.TYPE.UNKNOWN_METHOD": "type has no such method",
    "S.TYPE.ARITY": "wrong number of arguments",
    "S.TYPE.MISSING_ANNOTATION": "exported interface requires an annotation in verified mode",
    "S.TYPE.MISSING_FIELD": "record construction is missing a required field",
    "S.TYPE.NOT_CALLABLE": "value is not callable",
    "S.TYPE.FROZEN_MUTATION": "attempt to mutate a frozen value",
    "S.TYPE.FROZEN_FIELD_TYPE": "frozen record field type is not transitively frozen",
    "S.TYPE.GENERIC_ARITY": "wrong number of type arguments",
    "S.TYPE.INVALID_OPERATOR": "operator not defined for statically known operand types",
    "S.TYPE.DYNAMIC_CALL": "verified code calls a Dyn callable without narrowing it",
    "S.TYPE.ALWAYS_FALSE_EQUALITY": "comparison between statically disjoint types",
    "S.TYPE.INVALID_WITH": "`with` update applied to a non-frozen-record value",
    # ---- protocols ----
    "S.PROTOCOL.NOT_SATISFIED": "type does not structurally satisfy the declared protocol",
    "S.PROTOCOL.ADDED_PRECONDITION": "implementation adds a precondition to a protocol method",
    # ---- matching ----
    "S.MATCH.NON_EXHAUSTIVE": "match does not cover all cases",
    "S.MATCH.UNREACHABLE_ARM": "match arm can never be selected",
    "S.MATCH.INVALID_PATTERN": "pattern cannot match the scrutinee type",
    # ---- effects / errors ----
    "S.EFFECT.MISSING_TRY": "call that may throw lacks a `try` marker or handler",
    "S.EFFECT.UNDECLARED_THROWS": "error may escape but is not in the function's throws clause",
    "S.EFFECT.BROAD_FALLBACK": "unqualified `else` fallback over an open or multi-type error set",
    "S.EFFECT.THROWS_AND_RESULT": "function both declares throws and returns Result",
    "S.EFFECT.NOT_AN_ERROR": "thrown/caught type is not a declared error type",
    "S.EFFECT.CATCH_UNREACHABLE": "catch clause names an error that cannot be thrown here",
    "S.EFFECT.PROPAGATE_CONTEXT": "`propagate` used outside a Result-returning function",
    # ---- contracts ----
    "S.CONTRACT.RESTRICTED": "expression not allowed in the restricted contract language",
    "S.CONTRACT.RECURSIVE_PREDICATE": "predicates may not be recursive",
    "S.CONTRACT.OLD_NOT_SNAPSHOTTABLE": "old(expr) result is not primitive/frozen",
    "S.CONTRACT.OLD_OUTSIDE_ENSURES": "old() used outside an ensures clause",
    "S.CONTRACT.INVARIANT_FIELD_WRITE": "invariant-relevant field assigned outside the record's methods",
    "S.CONTRACT.RESULT_OUTSIDE_ENSURES": "`result` used outside an ensures clause",
    # ---- resources ----
    "S.RESOURCE.PROVIDER_OUTSIDE_USE": "resource provider called outside a `use` initialiser",
    "S.RESOURCE.ESCAPE": "resource or borrow may escape its scope",
    "S.RESOURCE.YIELD_COUNT": "provider does not yield exactly once on every path",
    "S.RESOURCE.YIELD_OUTSIDE_PROVIDER": "`yield` outside a resource provider",
    "S.RESOURCE.ON_ABANDON_RESTRICTED": "onAbandon accepts only built-in abandonment-safe release primitives",
    "S.RESOURCE.BORROW_PARAM": "resource passed to a parameter not declared `borrow`",
    # ---- async / tasks / isolation ----
    "S.ASYNC.AWAIT_OUTSIDE_ASYNC": "`await` outside an async function",
    "S.ASYNC.MISSING_AWAIT": "call to async function without `await`",
    "S.ASYNC.SYNC_CALLS_ASYNC": "non-async function calls an async function",
    "S.ASYNC.AWAIT_NON_ASYNC": "`await` applied to a value that is not awaitable",
    "S.TASK.SPAWN_OUTSIDE_GROUP": "`spawn` is only legal lexically inside a parallel block",
    "S.TASK.NOT_SENDABLE": "value cannot cross a task/channel boundary",
    "S.TASK.CAPTURE_MUTABLE": "spawned closure captures mutable state",
    "S.TASK.HANDLE_ESCAPE": "task handle used outside its structured scope",
    "S.SELECT.IMPURE_SETUP": "select branch setup must be pure/precomputed",
    "S.SELECT.INVALID_GUARD": "select guard must be a frozen local Bool",
    "S.SELECT.NONE_READY_PLACEMENT": "`none ready` only allowed in `select now` (and required there)",
    # ---- mode policy ----
    "S.MODE.RELEASE_REQUIRES_VERIFIED": "release builds require verified acceptance",
    # ---- warnings / advisories ----
    "W.CANCEL.NO_CANCELLATION_POINT": "async loop without a reachable cancellation point",
    "W.EFFECT.USELESS_TRY": "`try` applied to an expression that cannot throw",
    "W.SELECT.DEADLINE_RESET": "relative `after` deadline inside a loop is recomputed each iteration",
    "W.SELECT.CLOSED_LOOP": "closed branch in a loop does not exit or change eligibility",
    "W.SELECT.STARVATION": "priority select in a loop may starve later branches",
    "W.SELECT.BUSY_POLL": "`select now` repeats without any suspension point",
    "W.RESOURCE.SCOPE_TOO_WIDE": "resource scope stays open well after its last use",
    "W.STATE.LARGE_MUTABLE_RECORD": "mutable record with many unrelated fields (state bag)",
    "W.STATE.PASS_THROUGH": "mutable state passed through a function that does not use it",
    "W.TASK.LARGE_COPY": "large implicit graph copy at a task/channel boundary",
    "W.CHANNEL.UNBOUNDED_GROWTH": "unbounded channel occupancy keeps growing",
    "W.TYPE.IDENTITY_EQUALITY": "`==` on mutable values compares identity",
    "W.INVARIANT.ACROSS_AWAIT": "invariant field mutated before a cancellation point",
    "W.CLEANUP.FAILED_DURING_CANCELLATION": "cleanup/release failed while cancellation was pending",
    "W.CLEANUP.STUCK": "cleanup appears stuck while cancellation is pending",
    "W.TEST.SEED": "schedule stress seed",
    # ---- runtime abandonment ----
    "A.TYPE.DYNAMIC_MISMATCH": "value crossing a typed boundary does not have the annotated type",
    "A.TYPE.OPERAND_MISMATCH": "operator applied to operands of incompatible runtime types",
    "A.TYPE.NON_BOOL_CONDITION": "condition is not a Bool (no truthiness)",
    "A.TYPE.UNHASHABLE": "map key / set element is not a frozen value",
    "A.TYPE.NOT_CALLABLE": "value called is not a function",
    "A.TYPE.UNKNOWN_FIELD": "value has no such field",
    "A.TYPE.UNKNOWN_METHOD": "value has no such method",
    "A.TYPE.ARITY": "wrong number of arguments at runtime",
    "A.TYPE.FROZEN_MUTATION": "attempt to mutate a frozen value",
    "A.TYPE.NOT_ITERABLE": "value is not iterable",
    "A.TYPE.MISSING_FIELD": "record construction lacks a required field",
    "A.CONTRACT.INVARIANT_FIELD_WRITE": "invariant-relevant field assigned outside the record's own methods",
    "A.BINDING.UNINITIALISED": "binding read before initialisation",
    "A.MATCH.NO_ARM": "no match arm matched the value",
    "A.CONTRACT.PRECONDITION_FAILED": "precondition violated by caller",
    "A.CONTRACT.POSTCONDITION_FAILED": "postcondition violated by implementation",
    "A.CONTRACT.INVARIANT_VIOLATED": "record invariant does not hold at a public boundary",
    "A.CONTRACT.EVALUATION_FAILED": "contract expression could not be evaluated",
    "A.ASSERT.FAILED": "assertion failed",
    "A.INDEX.OUT_OF_RANGE": "index outside collection bounds (use .get for a checked alternative)",
    "A.MAP.MISSING_KEY": "map has no such key (use .get for a checked alternative)",
    "A.OPTION.UNWRAP_NONE": "unwrap() of None",
    "A.RESULT.UNWRAP_ERR": "unwrap() of Err",
    "A.NUMERIC.DIVISION_BY_ZERO": "integer division or modulo by zero",
    "A.NUMERIC.NAN_KEY": "NaN used as map key or set element",
    "A.NUMERIC.INVALID_CONVERSION": "NaN/Infinity converted to Int",
    "A.COLLECTION.MODIFIED_DURING_ITERATION": "mutable collection changed while being iterated",
    "A.EFFECT.UNDECLARED_EXCEPTION": "error escaped a function/callable whose throws clause excludes it",
    "A.EFFECT.UNDECLARED_PROPAGATE": "propagate used in a function not returning Result",
    "A.RESOURCE.ESCAPE": "resource or borrow escaped its scope",
    "A.RESOURCE.USE_AFTER_RELEASE": "resource used after its scope ended",
    "A.RESOURCE.NO_YIELD": "provider finished without yielding",
    "A.RESOURCE.MULTIPLE_YIELD": "provider yielded more than once",
    "A.RESOURCE.PROVIDER_OUTSIDE_USE": "provider invoked outside a use scope",
    "A.RESOURCE.ON_ABANDON_RESTRICTED": "onAbandon action is not a built-in abandonment-safe release primitive",
    "A.RESOURCE.CROSS_TASK": "borrow used from a different task",
    "A.TASK.NOT_SENDABLE": "value cannot cross a task/channel boundary",
    "A.TASK.GROUP_FAILURE": "child abandonment abandoned the enclosing task group",
    "A.TASK.AWAITED_ABANDONED": "awaited task abandoned; its value is unavailable",
    "A.TASK.AWAITED_CANCELLED": "awaited task was cancelled; its value is unavailable",
    "A.TASK.HANDLE_OUTSIDE_SCOPE": "task handle awaited outside its group scope",
    "A.TASK.SPAWN_OUTSIDE_GROUP": "spawn executed without an active parallel group",
    "A.TASK.EMPTY_GROUP": "race/firstSuccess requires at least one child",
    "A.ASYNC.SYNC_CONTEXT": "async function called from a non-async context",
    "A.CONCURRENCY.DEADLOCK": "every task is blocked and no deadline can wake any of them",
    "A.CHANNEL.BROADCAST_MUTABLE": "broadcast messages must be transitively frozen",
    "A.CHANNEL.PORT_RELEASED": "port used by a task that released (or never held) it",
    "A.RUNTIME.STACK_OVERFLOW": "call depth limit exceeded",
    "A.RUNTIME.MEMORY": "memory exhaustion",
    "A.RUNTIME.INVALID_ARGUMENT": "builtin called with an argument violating its precondition",
    "A.RUNTIME.UNREACHABLE": "impossible state reached",
    # ---- runtime recoverable (unhandled at top level) ----
    "R.ERROR.UNHANDLED": "recoverable error escaped the program entry point",
    "R.TASK.AGGREGATE": "one or more recoverable failures inside a structured scope",
    # ---- cancellation / hard termination ----
    "C.TASK.CANCELLED": "task terminated by cooperative cancellation",
    "C.PROGRAM.INTERRUPTED": "program cancelled by external interrupt",
    "H.RUNTIME.HARD_TERMINATION": "explicit runtime escalation; no cleanup guarantee",
    "H.RUNTIME.INTERNAL_ERROR": "interpreter defect (please report)",
    # ---- tests ----
    "I.TEST.PASSED": "test passed",
    "I.RUNTIME.REPORT": "informational runtime report",
}


def code(stable: str) -> Code:
    if stable not in CODES:
        raise KeyError(f"unregistered diagnostic code {stable!r}")
    outcome, domain, reason = stable.split(".")
    return Code(outcome, domain, reason)


def validate_registry() -> list[str]:
    problems = []
    for stable in CODES:
        parts = stable.split(".")
        if len(parts) != 3:
            problems.append(f"{stable}: not three parts")
            continue
        if parts[0] not in OUTCOME_NAMES:
            problems.append(f"{stable}: unknown outcome class")
        if not all(p.replace("_", "").isalnum() and p.upper() == p for p in parts[1:]):
            problems.append(f"{stable}: domain/reason must be UPPER_SNAKE")
    return problems
