# LLM-Native Programming Language: Design Document
## Version 3

---

## Preface

This document records the design of an unnamed LLM-native programming language. Its purpose is to carry design intent from the research and reasoning phase into the language specification phase without loss of context.

### Who this document is for

**The designer** — reviewing decisions, filling gaps, extending the design.

**The specification writer** — a Claude instance (or the designer with Claude) writing the formal language reference. The specification writer reads this document as its primary input and uses it to make both semantic and syntax decisions. For semantic questions, this document is authoritative. For syntax, this document provides principles and guidance; the specification writer exercises judgment within that framework and those decisions are reviewed by the designer. Where this document marks something as a specification-stage decision, the writer must make a choice and record it; it is not acceptable to leave it unresolved in the specification.

**The implementation-plan writer** — reads this document and the language specification to produce implementation notes and staging. Should not need to consult this document except to resolve rationale-level questions that the specification does not answer.

**The implementer** — reads the specification and implementation notes. Should not need to consult this document; where they do, this document should resolve the question.

### Document pipeline

```
Design Document (this document)
        ↓ primary input
Language Specification
(specification writer makes reviewed syntax decisions)
        ↓ both used
Implementation Notes / Staging Plan
        ↓ both used
Python Interpreter
        ↓
Bootstrapping (ICL templates + validated example library)
```

### Status notation

- **Decided** — firm decision with high confidence.
- **Decided direction** — architectural direction settled; exact semantics or syntax remain open.
- **Provisional** — preferred but should be tested or confirmed.
- **Specification-stage decision** — the spec writer must determine this, applying design principles and precedent; the choice will be reviewed.
- **Open detail** — spec writer must not invent an answer; flag for resolution.
- **Deferred** — potentially useful; not required in version 1.
- **Rejected** — considered and deliberately excluded.

For multi-part sections, statuses are nested: the section heading carries the status of the architectural direction; sub-items carry their own statuses.

### What this document is not

Not a language specification. No formal grammar, normative evaluation rules, or complete built-in-function list. Those belong in the specification. Not implementation notes. Notes on interpreter architecture, phasing, and Python semantics to prevent leaking belong in the Implementation Notes document.

---

## Part I — Context

### 1. Project Overview

#### 1.1 Purpose

This project designs and implements a programming language whose primary design target is LLM-assisted and LLM-generated code combined with human review of that output. Existing programming languages were designed assuming a human writes code in a text editor, making targeted edits. The dominant workflow has shifted: LLMs generate most code; humans review it. No mature, widely adopted general-purpose language is designed around the complete combination of goals pursued here. This language is designed explicitly around that combination.

#### 1.2 Intended Users and Programs

**Users**: Developers using frontier LLM coding agents (GPT-5.6 class and comparable). The language does not primarily target small or medium models; those lack the in-context learning capability required to work reliably with a language they have not been pre-trained on.

**Programs in scope**: data science and analysis; desktop applications; web services (personal or low-stakes); compilers, interpreters, and language tools including the interpreter for this language itself; automation scripts and task pipelines; simulations.

**Programs not in scope (non-goals)**: distributed systems at production scale; operating systems and kernels; cryptography and security-critical code; high-frequency trading or real-time control; programs where reliability requirements exceed what LLM-generated code can satisfy regardless of language. These are excluded not because the language cannot help at all but because the bottlenecks for LLM-generated code in those domains lie elsewhere, and optimising for them would compromise the primary use cases.

#### 1.3 The LLM-Native Design Goal

LLM coding agents can search files, retrieve definitions, navigate codebases, edit specific locations, and execute commands through tools. However, every tool call consumes context, tokens, latency, and attention, and introduces additional opportunities for retrieval, editing, and coordination errors. Information already present in the active context is generally richer and more reliably used than information reconstructed after context compaction or across sessions.

The language should therefore minimise the amount of navigation and cross-file state required to understand or modify a unit of code, without assuming that LLMs lack navigation tools entirely.

Additionally, the language and toolchain must work through provider-neutral interfaces — source files, command-line invocations, deterministic formatting, machine-readable diagnostics, and ordinary IDE integration. The design must not require access to any LLM provider's internal reasoning trace, hidden memory state, or proprietary agent harness. Both of these settings must work:

1. A user gives an ordinary LLM the language reference document, copies generated code into local files, and invokes the installed tools manually.
2. A coding agent receives the reference document and the path to the installed toolchain and independently invokes the formatter, checker, test runner, and interpreter.

"LLM-native" means **not** a language for writing programs that call LLMs — it is a general-purpose programming language designed for LLM-generated programs.

#### 1.4 The Targeted Coding Workflow

**Loop A** — Human-in-the-loop at every iteration: LLM writes → human reviews → LLM fixes. Human review quality and LLM correction efficiency matter most.

**Loop B** — LLM autonomously iterates many times before a human sees output: LLM generates → tests run → LLM reads error messages → LLM corrects → repeat. Error message quality for LLM consumption, structural stability under repeated editing, and correctness by construction matter most.

Loop B will increasingly dominate as LLM capability increases. Where the two loops conflict, Loop B takes priority.

#### 1.5 Document Pipeline

See Preface.

---

## Part II — Constraints and Non-Goals

Constraints are firm boundaries on the design space. Each follows: **Constraint → What it rules out → Why → Example of ruled-out design.**

---

### 2.1 Diagnostic quality takes priority over execution speed, within feasibility bounds

**Rules out**: Any design choice that improves runtime performance at the cost of diagnostic precision, error recovery, or trace richness — except where the performance cost would damage the practical development feedback loop.

**Why**: LLM-generated code has a higher error rate than human-written code. The primary bottleneck is the error-correction loop, not execution speed. However, a language that makes programs run ten times slower than their Python equivalents damages the feedback loop for both the human reviewer and the LLM coding agent. Rich diagnostics are worth bounded overhead; indefinite overhead is not acceptable. See Section 7.13.4 for provisional performance targets.

**Example of ruled-out design**: Stripping stack-trace information from abandonment diagnostics to reduce overhead.

**Example of acceptable trade-off**: A 25% geometric-mean slowdown in normal execution in exchange for always-available lightweight propagation metadata.

---

### 2.2 No nominal class inheritance

**Rules out**: Classes that inherit fields and methods from parent classes via an `extends` or similar relationship.

**Why**: Class inheritance creates cross-cutting dependencies requiring non-local understanding. Changes to a base class can silently break subclasses. LSP violations in LLM-generated code are particularly harmful because the LLM generates superclass and subclass in separate generation contexts without invariant-consistency guarantees. Records and structural protocols achieve the same code-reuse goals without these problems. Note: removing class inheritance eliminates one major source of hierarchy-related substitutability errors, but protocol-satisfying values still require behavioural substitutability relative to the protocol's declared methods and contracts.

**Example of ruled-out design**: `class Square extends Rectangle { ... }`

---

### 2.3 No manual memory management

**Rules out**: Explicit `malloc`/`free`, reference counting with manual `retain`/`release`, general affine or move-only value systems in version 1.

**Why**: Memory management bugs are among the hardest to diagnose. For LLM-generated code, memory safety issues frequently escape LLM notice because correct and incorrect programs look syntactically identical. Garbage collection handles memory. Scoped resource providers handle non-memory resources. This constraint covers version 1; later versions may revisit more nuanced ownership for specific use cases.

**Example of ruled-out design**: An `unsafe` block permitting raw pointer arithmetic.

---

### 2.4 Missing imports must never produce unexplained failures

**Rules out**: Any module system where an unresolved name silently produces a runtime failure with no indication that a missing import is the cause.

**Why**: Missing imports are among the most common mechanically diagnosable LLM errors. The language eliminates the silent-failure form of this error class: when the compiler encounters an unresolved name, it produces a diagnostic naming the missing import and likely candidate packages. For names resolvable from the project's known dependencies, the compiler may insert the import automatically, making the insertion a visible source edit. Adding a new external dependency requires an explicit action; a hallucinated package name must not silently alter the project's dependency graph.

**Example of ruled-out design**: `NameError: name 'json' is not defined` with no indication that `import json` is the fix.

---

### 2.5 No implicit mutable global dependencies or shared mutable task state

**Rules out**: Ordinary mutable module globals that any code can read or write implicitly; shared-memory concurrency with locks, semaphores, or mutexes as the primary coordination mechanism.

**Why**: The design concern is not mutation in the abstract. Useful programs need local accumulators, state machines, caches, and long-lived services. The concern is the *mutable-state horizon*: how many changing facts must be remembered simultaneously, how often they change, how many sites may change them, and how far across the code their history remains relevant. Implicit module-global state maximises that burden. Mutable state shared between tasks additionally requires global reasoning about races and synchronisation.

Version 1 therefore allows short-lived and long-lived mutable state with one visible owner, but requires long-lived state to be created explicitly, narrowly decomposed, and passed only to code that needs it. Frozen module constants are allowed. Ordinary mutable module globals are prohibited. Mutable values crossing task boundaries are graph-copied; resources and runtime capabilities are rejected.

**Example of ruled-out design**: A module-level `MutableDict` that any function or concurrent task can update.

**Example of conforming design**: `main` constructs a small set of separately owned services and passes each service only to the component that uses it.

---

### 2.6 Suitability for the primary use cases is never traded away for edge-case use cases

**Non-goal, not constraint**: The language is not optimised for distributed systems at production scale, operating systems, or security-critical programs. This does not mean such programs cannot be written in the language. If a design choice simultaneously improves the language for its primary use cases and for these edge cases, it should be adopted. The constraint is that a design choice that worsens the primary experience for the benefit of edge cases is rejected.

**Why**: LLM-generated code in the excluded domains faces bottlenecks (reliability at scale, hard latency guarantees, formal security proofs) that no programming language design can address. Optimising for them would degrade the primary design without proportionate benefit.

---

### 2.7 Python semantics must not become language defaults by accident

**Rules out**: Inheriting Python's truthiness coercions, Python's `None` propagation model, Python's `__dunder__` dispatch semantics, Python's GIL-based concurrency model, Python's module load order, or Python's exception hierarchy as implicit language semantics.

**Why**: The first interpreter is written in Python. This creates a risk that Python semantics become de facto language semantics through implementation convenience. Every place where Python's underlying behaviour would be observable to a language user must be explicitly mediated by the interpreter. Python is valuable as an implementation substrate, an edge-case discovery tool, and a source of familiar patterns; it is not a semantic authority.

**Example of ruled-out design**: `if myList:` testing whether a list is non-empty, silently inherited from Python's truthiness rules.

---

### 2.8 There is one canonical persisted source representation

**Rules out**: Any dual-representation grammar where the LLM sees a compact tokenisation-optimised form and humans see an expanded readable form; any source transformation that alters semantics without producing a visible, reviewable source edit.

**Why**: DualCode-style architecture was considered and rejected. The primary LLM cost driver is the number of error-correction turns, not tokens per turn. A gap between what the LLM sees and what the human reviewer sees creates an audit gap that is specifically harmful for the primary use case. A canonical formatter achieves consistent formatting and enables meaningful diffs without any representation gap. Tool-generated changes — import insertion, formatting — are ordinary visible source edits reviewed normally.

**Example of ruled-out design**: A grammar transformation that strips whitespace and braces before presenting source to the LLM.

---

### 2.9 No performance-motivated type system complexity

**Rules out**: Linear types, uniqueness types, region types, or other type system features whose primary motivation is enabling compiler optimisation.

**Why**: The type system's purpose in this language is to catch errors and aid review, not to enable optimisation. Complexity in the type system costs LLM generation reliability and costs human review quality. Features must earn their place by improving correctness or diagnosability. The initial implementation does not compile to native code; performance concerns of this kind do not yet apply.

**Example of ruled-out design**: Ownership types designed to eliminate reference-counting overhead.

---

### 2.10 The implementation must be staged and semantically consistent

**Rules out**: An implementation strategy that does not divide the interpreter into explicit semantic phases with conformance tests at each phase boundary.

**Why**: A staged, test-driven implementation of the language is feasible with current frontier coding agents. The principal risks are not raw code volume but inconsistent semantics across independently implemented subsystems, inadequate feature-interaction tests, context compaction losing design rationale, and accidental leakage of Python behaviour. The constraint is not about implementation scale (current frontier agents can sustain large multi-session projects) but about implementation discipline.

**Example of ruled-out design**: Implementing the entire interpreter in one undivided pass without conformance tests between stages.
---

## Part III — Design Principles

Principles are abstract values that govern design choices. They are not themselves design choices. Each principle is followed by: its meaning, why it matters for LLM-native code, a conforming example, a non-conforming example, the decisions it most affects, and known tradeoffs.

---

### 3.1 Comparative Locality and the Mutable-State Horizon

**Principle**: Where non-local or mutable state must be tracked, prefer the design requiring the smallest, least variable body of state over the shortest practical span of code.

**What it means**: Code should be understandable from its immediate context with minimal need to reconstruct distant execution history. Absolute locality is impossible in realistic programs; the question is comparative. Minimise the number of mutable facts that must be remembered simultaneously and the span over which each fact remains relevant.

When comparing designs, consider:

- the quantity of live mutable state;
- how frequently it changes;
- the number of possible mutation sites;
- the number of aliases;
- how many functions must know about it;
- the distance between a mutation and later uses;
- how much prior execution history determines its meaning;
- whether it crosses a concurrency boundary;
- and whether it has one visible owner.

Do not turn these considerations into a pseudo-mathematical formula. They are qualitative design criteria.

**Why it matters for LLM-native code**: An LLM correcting a function should not need to reconstruct a large, changing program state from many files or earlier turns. A reviewer should be able to identify the state relevant to a block without tracing unrelated code. Tool-assisted navigation remains possible, but every search, retrieval, and edit consumes context, tokens, latency, and creates another opportunity for error.

**Conforming example**: A loop-local accumulator, or a root-owned database service passed explicitly only to functions that use it.

**Non-conforming example**: A monolithic mutable `AppState` with dozens of unrelated fields threaded through the whole codebase, or a function whose behaviour depends on a mutable registry initialised elsewhere.

**Decisions it affects**: Frozen records by default; explicit mutable record types; no ordinary mutable module globals; explicit task arguments preferred over closure captures; resource scopes; controlled mutation for invariant-bearing fields; structured task lifetimes; state-bag diagnostics.

**Known tradeoffs**: Explicit state passing and decomposition can be more verbose. The language accepts this when it materially reduces hidden dependencies, but does not prohibit mutation merely because it is mutation.

---

### 3.2 Explicit Failure and Control Flow

**Principle**: In verified source, every recoverable-failure propagation point and every task creation point is visible locally.

**What it means**: A reader scanning a function body for potential failure points can do so by looking for explicit markers. No recoverable exceptions propagate invisibly through the call stack. No task runs in the background without a visible spawn. No resource is acquired without a visible cleanup scope. The principle applies to verified source; draft source accepts incomplete annotations while diagnosing where they are missing.

**Why it matters for LLM-native code**: Invisible control flow is a primary source of LLM-generated bugs. An LLM writing a function that calls `readFile` has no signal that `readFile` can fail unless the language places a signal at the call site. In draft mode, missing signals are diagnosed but do not block happy-path execution; in verified mode, they are errors. Human reviewers scanning LLM-generated code for failure surfaces can identify them by searching for a small number of distinct markers.

**Conforming example**:
```
fn loadConfig(path: Str) -> Config throws IOError, ParseError {
    let data = try readFile(path)
    let config = try parseJSON(data)
    return config
}
```
Every potential recoverable failure is marked with `try`.

**Non-conforming example**: `let data = readFile(path)` — can fail with no indication at the call site.

**Decisions it affects**: `try` required at throwing callsites in verified mode; `spawn` for task creation; explicit resource scopes with visible entry/exit; structured concurrency; `cancel.check()` as an explicit cancellation point.

**Known tradeoffs**: Code with many potential failure points requires many `try` markers, increasing visual density. This is deliberate — the density reflects the true failure surface. In draft mode, the overhead is absent; in verified mode, the overhead is informative.

---

### 3.3 Exhaustive Handling

**Principle**: When a value can be one of several distinct shapes, the language ensures all shapes are handled.

**What it means**: Variant types (closed sum types) paired with pattern matching must cover all cases. The interpreter catches missing cases at runtime in draft mode and the static checker catches them in verified mode. Missing corner cases is one of the most common LLM error categories; the language reduces this structurally for values whose variants are known at compile time.

**Why it matters for LLM-native code**: LLMs systematically undersample edge cases. When a value can be `Ok(data)` or `Err(error)`, an LLM that writes only the `Ok` branch and omits `Err` produces code that passes happy-path tests and fails silently in production. A closed variant type with exhaustive pattern matching turns this into a detectable error.

**Conforming example**:
```
match result {
    Ok(data)  => process(data)
    Err(error) => log(error)
    // Checker enforces all variants are covered
}
```

**Non-conforming example**: An open-ended polymorphic dispatch where new cases can be added without updating existing code and no mechanism detects the omission.

**Decisions it affects**: Closed enum/variant types; exhaustive pattern matching with checker enforcement; `Result[T, E]` as a core type; nominal error categories rather than open structural hierarchies.

**Known tradeoffs**: Adding a new variant to an enum requires updating every match expression that covers it. LLMs can update all match expressions cheaply; the benefit of catching missed cases is high. The tradeoff favours exhaustiveness for this language's use cases.

---

### 3.4 Diagnostic Quality Over Speed, Within Feasibility Bounds

**Principle**: Rich, precise, actionable diagnostic information is always worth bounded performance overhead; unbounded overhead is not acceptable.

**What it means**: The language and toolchain always collect and surface the diagnostic information that helps LLMs and humans understand what went wrong and where — subject to provisional time, memory, and output budgets that preserve a practical development feedback loop. Lightweight diagnostic metadata (source spans, propagation chains, error codes, task lineage) is always present. Substantially more expensive instrumentation belongs in explicit verification or deep-diagnostic modes.

**Why it matters for LLM-native code**: The error-correction loop is the primary productivity bottleneck. A precise, multi-span diagnostic pointing to the exact location and contributing variables enables a one-shot LLM correction. A vague traceback requires the LLM to re-read code and reason about what went wrong, taking multiple turns. However, a language whose programs take an order of magnitude longer to run breaks the human's feedback loop and slows the LLM's iteration cycle — so overhead must be bounded.

**Conforming example**: An abandonment message showing the violated contract expression, the actual values that violated it, and local variable values at each frame within budget — all rendered in under 5 seconds.

**Non-conforming example**: A runtime that serialises entire DataFrames into every error message without budget limits, causing 10-minute diagnostic rendering times.

**Decisions it affects**: Bounded, sanitised local-variable capture; lightweight propagation metadata on Results; structured diagnostic objects; provisional performance targets in Section 7.13.5; three diagnostic modes (default, verified, deep).

**Known tradeoffs**: Bounded diagnostics mean that in some cases, relevant information is truncated. Truncation markers must be clear. Extended-report modes are available for cases requiring more detail.

---

### 3.5 Designed for LLM Generation

**Principle**: When choosing between two otherwise equivalent designs, prefer the one that LLM coding agents are more likely to generate correctly under in-context learning, while remaining accessible to ordinary LLM chat users without agent tooling.

**What it means**: Syntax and semantics choices must account for how LLMs actually behave, informed by empirical evidence where available. The language must work for both (a) an LLM agent with full tool access and (b) a user who pastes generated code manually. Keywords should create accurate priors at their point of use. Syntax should avoid constructs that LLMs systematically fail on. The language should not depend on any provider's proprietary orchestration.

**Why it matters**: A language that is theoretically elegant but that LLMs generate incorrectly under ICL fails its design goal. The Vera experiment demonstrates that frontier models can achieve Python-level performance on a zero-training-data language from a reference document alone — but only if the spec is well-structured and the language design aligns with how frontier models reason about code.

**Conforming example**: Using `fn` for function definitions — borrowed from Rust, which has massive training representation and semantics that closely match this language's function semantics — rather than a novel keyword like `proc`.

**Non-conforming example**: A block syntax requiring exactly three spaces of indentation, which LLMs systematically get wrong (documented in LlmFix as a top mechanically fixable error class).

**Decisions it affects**: Keyword selection (see principle 3.7); brace syntax over indentation; optional return type annotations; draft mode permitting incomplete source; gradual typing; `try` as propagation operator; pattern matching syntax; string interpolation format; lambda syntax.

**Known tradeoffs**: Optimising for LLM generation may produce syntax that is less theoretically principled. This is an explicit tradeoff. Practical generation quality over theoretical elegance is the tiebreaker.

---

### 3.6 Designed for Human Review

**Principle**: A human auditing LLM-generated code should be able to understand each component locally, identify failure points quickly, and verify that the code matches its stated intent.

**What it means**: Function signatures state preconditions and postconditions explicitly. Every failure point is marked in verified source. Resource acquisition and cleanup are adjacent and within the same visible scope. Type annotations, when present, add information rather than just restricting behaviour. Diagnostic messages help the reviewer understand the failure, not just locate it.

**Why it matters**: Human review is the final quality gate in Loop B. If LLM-generated code is hard to review, either bugs slip through or review becomes the bottleneck. The goal is that a competent reviewer can audit a function in the time it takes to read it once.

**Conforming example**: A function with `requires`/`ensures` in its signature, a `use` block for resource acquisition and cleanup visible at a glance, and `try` at every throwing call site — all visible without scrolling.

**Non-conforming example**: Exception handling logic in a centralised handler 200 lines away from the code that throws, requiring the reviewer to cross-reference two distant locations.

**Decisions it affects**: Contracts in signatures (not bodies); `try` at callsites; resource scopes with visible boundaries; structured concurrency (no invisible background tasks); explicit exports; two-level visibility; diagnostic format with source spans; canonical formatter for consistent presentation.

**Known tradeoffs**: Review-oriented verbosity adds code that slows generation slightly. Accepted because review quality is as important as generation speed.

---

### 3.7 Locally Accurate Syntactic Priors

**Principle**: Prefer the keyword or operator whose local syntactic role and immediately relevant operational behaviour most closely match the intended construct, provided that remaining semantic differences are visible in the surrounding syntax and are unlikely to induce systematic errors.

**What it means**: The relevant benefit of borrowing familiar syntax is not that another language's construct is globally identical — it rarely is. It is that the LLM and reviewer have an accurate prior at the point where the construct appears. Evaluate candidate syntax using: (1) what action does the keyword locally signal? (2) what syntax does an LLM expect to follow it? (3) which semantic differences affect nearby code? (4) are those differences visible from the surrounding syntax? (5) is a reviewer likely to transfer a harmful assumption? (6) does the choice aid human familiarity as well as LLM generation?

**Why it matters**: Keywords carry semantic priors. When an LLM sees `await`, it expects a suspension point. When it sees `match`, it expects pattern matching. Confirming these expectations by making semantics match the prior reduces the learning cost when using the reference document. Violating the expectation with a keyword whose semantics differ materially from its most prominent usage causes systematic errors that are hard to trace to the source.

**Conforming example**: Using `spawn { ... }` inside a `parallel {}` block to create a concurrent task. The word "spawn" locally signals concurrent work. The surrounding `parallel` block makes the structured lifetime explicit, so the difference from unstructured spawning in Erlang or Go is visible in the surrounding syntax. An LLM seeing `spawn` inside `parallel` is unlikely to assume the task has an unbounded lifetime.

**Non-conforming example**: Using `class` for record definitions when records in this language have no inheritance, no designated initializer, and no `self` passed implicitly — all of which the LLM would expect from `class`.

**Decisions it affects**: All syntax decisions made by the specification writer; keyword selection policy; operator naming; the syntax guidance section (Part IV).

**Known tradeoffs**: Some constructs have no good precedent. New keywords must be introduced in those cases, ideally natural English words that appear in code contexts with meaning close to the intended semantics.

---

### 3.8 One Mechanism Per Concern

**Principle**: There should be one primary way to accomplish each common programming task; where multiple mechanisms exist, they must be clearly stratified with distinct roles.

**What it means**: Resource lifetime management uses one mechanism (`use` scopes). Non-resource cleanup uses one mechanism (`defer`). Error propagation uses one operator. Concurrency structure uses one substrate (structured task groups). Multiple mechanisms are acceptable when they serve genuinely distinct purposes; they are not acceptable as equivalent alternatives for the same purpose.

**Why it matters for LLM-native code**: When multiple equivalent mechanisms exist, LLMs choose inconsistently, producing incoherent code. More importantly, LLMs may mix mechanisms in ways that produce subtle bugs. One mechanism per concern means the LLM always reaches for the same construct.

**Conforming example**: `use file = openFile(path) { ... }` for resource acquisition and cleanup; `defer log("done")` for non-resource cleanup. These are not competing mechanisms — they handle distinct concerns.

**Non-conforming example**: Providing both `use` scopes and a `Closeable` protocol with automatic structural RAII as two equivalent resource-cleanup mechanisms for the same file type.

**Decisions it affects**: Resource management (`use` for resources, `defer` for other cleanup); error representation (exceptions for immediate control flow, `Result` for stored failure data — stratified, not equivalent alternatives); concurrency (one task-group substrate with four operation modes).

**Known tradeoffs**: Stratified mechanisms require the LLM to understand which stratum applies. Clear stratification and good error messages when the wrong stratum is used mitigate this.

---

### 3.9 Structured Lifetimes

**Principle**: Tasks and resources should have lifetimes represented by visible lexical structure, with guarantees matched to the kind of exit.

**What it means**: A task cannot silently outlive the structured scope that created it. A resource-owning value exists only inside a visible resource scope. Ordinary cleanup is tied to the operation that established the lifetime.

Structured release is guaranteed on normal return, recoverable exception, and cooperative cancellation. During abandonment, only restricted best-effort release actions run. Under runtime hard termination or catastrophic external termination, cleanup is not guaranteed.

**Why it matters for LLM-native code**: Lifetime obligations become visible and reviewable. The LLM does not need to remember a distant close call or an unstructured background task. The runtime can report exactly which scope owns a task or resource.

**Conforming example**: A `parallel` block that waits for all spawned tasks before exiting, and a `use` block that releases its resource before producing the block result.

**Non-conforming example**: Fire-and-forget tasks, final-reference cleanup, or an ordinary resource handle stored indefinitely with no visible owner.

**Decisions it affects**: Structured concurrency; scoped resource providers; stable task handles; cancellation masking; abandonment-safe release; no structural RAII.

**Known tradeoffs**: Some intentionally long-lived services require a root structured scope. Hard termination necessarily weakens cleanup guarantees.

---

## Part IV — Syntax Guidance for the Specification Writer

This section provides derived intermediate principles for syntax decisions. It does not specify keywords, punctuation, or grammar — those are specification-stage decisions. It provides principles strong enough to narrow the decision space substantially, illustrated with hypothetical examples showing how the principles apply. The specification writer should record their syntax choices and the reasoning; those choices will be reviewed by the designer.

This section is specifically about syntax decisions: keyword names, operator symbols, punctuation, block delimiters, declaration forms, annotation placement. It does not cover semantic decisions, which are settled in Parts V through VII.

---

### 4.1 Scope Boundaries Must Be Visually Unambiguous

Resource scopes, task scopes, function bodies, and conditional branches all define regions with distinct semantics. Syntax must make the start and end of every scope unambiguous without requiring the reader to count indentation levels or infer from context.

**Implication**: Block delimiters (open and close) should be explicit tokens that cannot be confused for each other or for statement bodies. Indentation should be meaningful for readability (enforced by the canonical formatter) but not syntactically load-bearing.

**Hypothetical choice**: If choosing between indentation-significant syntax (Python style) and brace-delimited syntax (C/Rust style), the correct application of this principle and the LLM generation principle is to choose brace-delimited syntax. Documented LLM errors include inconsistent indentation as one of the three mechanically fixable error classes (LlmFix paper). Braces make scope boundaries unambiguous regardless of whitespace. The canonical formatter enforces consistent indentation on top of braces, so human reviewers still see clean indented code.

---

### 4.2 Keywords Must Create Locally Accurate Priors

When an LLM reads a keyword, it predicts what follows. That prediction should be accurate for this language's local syntax and nearby operational behaviour. Where no candidate carries a uniformly accurate prior, the surrounding syntax should make the difference explicit.

**Implication**: For any borrowed keyword, ask:

1. What action does it signal locally?
2. What syntax is expected immediately afterward?
3. Which transferred assumptions could change nearby code?
4. Does surrounding syntax visibly correct those assumptions?
5. Would a reviewer reasonably misread the construct?

**Hypothetical choice**: Boolean operator spelling should be chosen only after boolean semantics are settled. Python's `and`/`or` return operands, while many `&&`/`||` operators produce Booleans. If this language requires Boolean operands and Boolean results, claiming Python-identical behaviour would be wrong even if keyword spelling remains attractive. The specification writer should compare the actual local semantics rather than selecting a keyword solely by popularity.

---

### 4.3 Short Keywords Preferred, Excluding Truncations That Mislead

Short keywords tokenize to fewer tokens and appear more cleanly in code. However, truncations that create misleading priors are worse than slightly longer accurate keywords.

**Implication**: Prefer keywords of 2–5 characters when they are natural English words or well-established PL keywords. Avoid abbreviations that are not universally recognised. A longer keyword with a clear prior (`return`) is preferable to a short keyword with an ambiguous prior.

**Hypothetical choice**: For function declaration, if choosing between `function`, `fn`, `def`, or `func`, the correct application is `fn` (from Rust) or `fn` combined with context. `function` is long; `def` creates a Python prior for function bodies (acceptable only if semantics closely match); `fn` is short, unambiguous, well-established. Among `fn`, `func`, and `def`, the choice depends on which has the strongest prior consistent with the language's function semantics.

---

### 4.4 Left-to-Right Generation Order Should Match Discovery Order

When an LLM generates code left-to-right, declarations should place information in an order that can usually be determined without anticipating a distant implementation detail. This is a preference, not a prohibition on later targeted edits.

**Implication**: Parameter and return information should follow a familiar readable sequence. Optional annotations should be addable later without restructuring the declaration. Resource, failure and concurrency distinctions that affect body construction must appear before the body begins.

**Hypothetical choice**: Postfix return types (`fn foo(x: Int) -> Int`) follow the parameter list and match strong existing priors. Prefix return types are possible but give no compensating locality advantage. Contracts remain in the signature because callers and reviewers need them there, even though an LLM may add or revise them after drafting the body through an ordinary targeted edit.

---

### 4.5 Consequential Distinctions Must Be Explicit

When two constructs have different semantics with real consequences — especially consequences relating to resource lifetimes, mutation, or task boundaries — their syntax must visibly distinguish them.

**Implication**: The syntax for binding an ordinary value and binding a resource-owning value must be visually distinct. The syntax for declaring a frozen record and a mutable record must be visually distinct. The syntax for a function that may throw and one that cannot must be visually distinct in verified source.

**Hypothetical choice**: For resource binding, if choosing between reusing `let` (with a type-level distinction only) versus a distinct keyword (`use`, `with`, `resource`), the correct application is a distinct keyword. An LLM that sees `let file = openFile(path)` might reasonably attempt to store, return, or pass `file` to another function — all of which are illegal for resource-owning values. A distinct keyword creates a visible signal that different rules apply.

---

### 4.6 Happy-Path Code Must Remain Readable

The language has substantial machinery for error handling, contracts, and resource management. The syntax must not make the happy-path logic of a function hard to read due to the surrounding scaffolding.

**Implication**: Error propagation should be concise at callsites (a short marker, not a full try-catch block). Contracts should be in the signature but should not visually dominate simple functions. Resource scopes should open near the top and be indented naturally. The canonical formatter should produce layouts where the functional core of a function is visually prominent.

**Hypothetical choice**: For error propagation, if choosing between `try expr` (marker before the expression), `expr?` (marker after the expression, Rust-style), or a full `try { expr } catch E { ... }` block for propagation, the correct application for the common case of propagation (not local handling) is a short prefix or suffix marker. Rust's `?` is very short but single-character and easy to miss in review; `try expr` is slightly longer but more searchable and readable. The choice between them is for the specification writer; either satisfies this principle better than requiring a full block for propagation.

---

### 4.7 Error Paths Must Be Searchable in Code Review

Human reviewers auditing LLM-generated code for error-handling completeness must be able to search for all potential failure points. The syntax for marking a potential failure point should be a distinctive, searchable token rather than an invisible semantic property.

**Implication**: The marker for a throwing call site should be a keyword or distinctive symbol, not a convention or type-level annotation alone. It should appear at the call site, not only in the function's signature.

**Hypothetical choice**: For the call-site failure marker, if choosing between `try`, `throws`, `!`, `?`, or an annotation, a keyword (`try`) is more searchable than a symbol (`!` or `?`). `try expr` makes every potential failure point greppable with a single keyword search. This is the decision taken in this language's design; the spec writer chooses the exact keyword.

---

### 4.8 The Canonical Formatter Is the Arbiter of Style

Any syntax choice that the canonical formatter can normalise is less important than it appears. If two syntactic forms for the same construct are semantically equivalent and the formatter canonicalises one, the specification writer should not spend excess effort on the non-canonical form.

**Implication**: The specification writer should define one canonical form for each construct and defer to the formatter for enforcement. Optional trailing commas, optional parentheses on simple expressions, and similar micro-syntactic choices should be normalised by the formatter rather than generating multiple valid forms that reviewers must track.

---

## Part V — Semantic Commitments

This section states the foundational semantic commitments that the specification writer must preserve. It is intentionally denser than the Current Design Summary. The specification may choose syntax and formalisation, but may not weaken these commitments without returning the question to the designer.

---

### 5.1 Value identity and mutability

1. **Frozen values are value-like.** Primitives, strings, ordinary records, closed variants containing only frozen values, and frozen collections have structural equality and no observable reference identity.
2. **Mutable records are identity-bearing.** Two bindings may refer to the same mutable record inside one task; mutation through one binding is visible through the other.
3. **Freezing is transitive.** An ordinary `record` may contain only transitively frozen fields. A frozen collection may contain only frozen values.
4. **Mutability is a type-level distinction.** `record Foo` and `mutable record Foo` are distinct declarations; there is no per-instance mutable/frozen switch.
5. **Binding reassignment is separate from object mutation.** Rebinding `count` to a new integer is not the same operation as mutating `account.balance`. Bindings are reassignable by default. Exact binding and constant syntax is a specification-stage decision.
6. **Frozen updates produce new values.** Updating a frozen record or collection never changes an existing value. The implementation may use structural sharing or copy-on-write so long as it is unobservable.
7. **Mutable/frozen conversions preserve isolation.** `mutable.freeze()` creates an immutable snapshot; `frozen.mutableCopy()` creates an independently mutable graph. Later mutation cannot change the frozen value.

### 5.2 Mutable-state ownership

1. Frozen module constants are allowed.
2. Ordinary mutable module globals are prohibited in version 1.
3. Long-lived mutable state is created explicitly in a root scope, decomposed into narrowly purposed components, and passed only to code that requires it.
4. Mutable state has one owning task. It is not directly shared between concurrent tasks.
5. An explicit owner-bound module-state facility is deferred. The design must not assume that version 1's prohibition is an eternal impossibility, but no version-1 feature may rely on implicit mutable globals.

### 5.3 Gradual typing and dynamic boundaries

1. Unannotated code is dynamically typed. The conceptual dynamic type is provisionally called `Dyn`; exact spelling is a specification-stage decision.
2. Explicit annotations are enforced at runtime in both draft and verified execution.
3. Draft mode relaxes the obligation to write annotations and complete static proofs; it does not make written annotations advisory.
4. There is no automatic cross-type coercion. A string does not silently become an integer; a structurally similar record does not silently become a concrete nominal record type.
5. A concrete record annotation requires the concrete runtime type.
6. A protocol annotation performs an immediate shallow shape check at the typed boundary: required methods, compatible arities, declared recoverable effects, and required runtime metadata must be present.
7. Nested and generic contents use transient checking. Values are checked when typed code reads, writes, calls, returns, or performs a bulk operation that relies on the nested type. The runtime does not recursively traverse every reachable object at every boundary.
8. Annotated return values are checked before leaving the typed function.
9. A dynamic mismatch at a written annotation is abandonment: the program asserted a type assumption and that assumption was false.
10. Dynamic callables must be narrowed to a function type with a known `throws` effect before they may be invoked in verified code.
11. Dynamic values are not sendable by default. Task creation and channel send must establish sendability before execution or commit.
12. Dynamic-type diagnostics identify the boundary crossing, relied-upon annotation, actual runtime type, typed use site where applicable, and value origin where known.

### 5.4 Nullability and binding state

1. `T?` is syntax for `Option[T]`.
2. `null` is syntax for `None`.
3. A binding may be uninitialised, initialised to `None`, or initialised to `Some(value)`.
4. Uninitialised is a binding state, not a null value.
5. There is no second raw-null representation distinct from `Option.None`.
6. Domains requiring several kinds of absence should define a closed variant with domain-specific cases.

### 5.5 Resource providers, scopes, and borrows

1. Garbage collection manages ordinary memory.
2. Non-memory resource lifetimes are established by resource providers and lexical resource scopes.
3. A resource provider has four semantic phases: acquisition, exactly one yield, normal release, and registration of abandonment-safe release actions.
4. A provider may be invoked only as the initializer of a resource scope. A resource-producing expression is not an ordinary freely storable return value.
5. A resource-owning value may not be ordinarily bound, returned, stored in an ordinary record or collection, captured by an escaping closure, sent through a channel, or passed to another task.
6. A resource scope is expression-valued: its body result is saved, release runs, and the saved value becomes the scope result unless release changes the outward recoverable outcome.
7. Ordinary helper functions may receive a scoped borrow. A borrow may pass through nested non-escaping calls and may cross `await` in the same task while the owning scope remains active.
8. A borrow may not escape the call chain, be stored, be returned, enter an ordinary record, cross a task boundary, or be sent through a channel.
9. Normal provider release runs after normal return, recoverable exception, and cooperative cancellation. It may know which of those exit classes occurred. It may not suppress the pending exception or cancellation in version 1.
10. Abandonment does not resume arbitrary post-yield provider code. The runtime executes only registered best-effort abandonment-safe release actions.
11. Abandonment-safe release may close, release, revoke, discard, roll back, or relinquish a resource. It may not commit, flush business output, publish, notify, invoke user callbacks, or create new application effects.
12. Abandonment-safe release receives only the resource handle, frozen acquisition metadata, and the coarse exit classification. It cannot depend on ordinary application allocation succeeding.
13. A release failure during abandonment cannot replace or suppress the original abandonment. It is appended as secondary diagnostic information.
14. Resource-owning records remain a deferred extension. Version-1 choices should not foreclose a restricted non-copyable, non-sendable, scope-bound resource container later.

### 5.6 Cleanup and exit mechanisms

The language distinguishes these outward control effects:

1. **Normal return**: permitted `defer` callbacks and normal resource release run; postconditions and invariants are checked against final visible state; the saved value is returned.
2. **Recoverable exception**: permitted `defer` callbacks and normal release run; invariants are checked; the exception propagates if they hold; invariant failure causes abandonment instead.
3. **Cooperative cancellation**: permitted cleanup and normal release run under cancellation masking; invariants are checked; cancellation is redelivered afterward. Invariant failure supersedes cancellation with abandonment.
4. **Abandonment**: arbitrary `defer` callbacks and ordinary provider continuation do not run. Only best-effort abandonment-safe release runs. The failed task terminates and cannot catch or resume the abandonment.
5. **Runtime hard termination**: explicit runtime escalation. No user cleanup, invariant checking, or release guarantee. A diagnostic is best-effort if the runtime remains capable of reporting.
6. **Catastrophic external termination**: operating-system force kill, process crash, fatal out-of-memory, machine loss, or equivalent. Outside ordinary language control-flow semantics; no guarantee exists.

Cleanup failures combine according to one model:

| Pending outcome | Cleanup or release failure |
|---|---|
| Normal return | Throw the cleanup/release exception |
| Recoverable exception | Aggregate the original and cleanup/release exceptions |
| Cooperative cancellation | Report cleanup failure while preserving pending cancellation; redeliver cancellation afterward |
| Abandonment | Preserve abandonment; append release failure diagnostically |
| Hard/catastrophic termination | No guarantee |

`AggregateException` is therefore a general non-empty aggregate of recoverable exceptions with structured provenance such as task group, cleanup, or resource release.

### 5.7 Recoverable exceptions, Results, cancellation, and abandonment

1. Recoverable exceptions represent immediate failure control flow that must be handled or propagated now.
2. `Result[T, E]` represents failure materialised as data for storage, accumulation, batch processing, channel messages, or later inspection.
3. A function may not both declare recoverable `throws` and return `Result[T, E]`.
4. Conversion between a throwing computation and a Result is explicit. Exact syntax is a specification-stage decision.
5. A broad fallback may not silently suppress an open set of errors. An unqualified default is legal only when the statically known throws set contains one concrete recoverable error type; otherwise handled types must be named.
6. Abandonment is reserved for violated programming assumptions or circumstances where safe continuation is unavailable.
7. If a condition can occur despite the caller satisfying documented preconditions and the program can safely choose a response, it is recoverable rather than abandonment.
8. APIs expose checked alternatives when a condition is a legitimate expected branch, for example checked indexing or bounded allocation refusal.
9. Cancellation is distinct from recoverable exceptions. Ordinary `catch` cannot consume or discard it.
10. A top-level unhandled recoverable exception performs ordinary exception cleanup, terminates the program unsuccessfully, and remains classified as an unhandled recoverable exception rather than abandonment.

### 5.8 Error effects

1. Version 1 includes minimal forwarding error-effect polymorphism.
2. Higher-order function types may contain nominal error-set variables.
3. Finite error sets may be unioned and forwarded through callbacks.
4. The language does not require a general algebraic-effect system or user-defined effect handlers in version 1.
5. A completely dynamic callable must be narrowed to a function type with a known error effect before verified invocation.

### 5.9 Error types and categories

1. Every recoverable error has a concrete nominal type.
2. A concrete error may belong to zero or one nominal catch category in version 1.
3. Categories affect catch matching only. They do not inherit fields, methods, implementations, or override behaviour.
4. Closed error enums remain available for deliberately closed domains.
5. Multiple category membership is unavailable in version 1, but runtime metadata and serialisation should not foreclose it in a later version.
6. Catching a category does not make an open future error universe exhaustive. Exhaustiveness applies only where the declared finite throws set or a closed error enum is known.

### 5.10 Contracts and invariants

1. Contracts are executable runtime predicates at interface boundaries, not a promise of general theorem proving.
2. `requires` and `ensures` belong in function or method signatures.
3. Version 1 uses a restricted contract-expression language. It permits bounded total operations over primitives and frozen values; it prohibits mutation, I/O, resource access, awaiting, spawning, throwing, cancellation, time, randomness, unsafe indexing, unbounded allocation, arbitrary recursion, and general function calls.
4. Reusable contract logic uses restricted non-recursive `predicate` declarations that may call only other predicates.
5. `old(expr)` captures the entry value of an expression. It is legal only when the captured result is primitive, transitively frozen, a frozen collection, or explicitly safely snapshot-capable.
6. Method preconditions and postconditions describe one call. Record invariants are type-level boundary properties.
7. Fields contributing to an invariant may be modified only through operations participating in invariant checks. Exact visibility/control syntax is specification-stage work.
8. Protocol contracts are inherited by every conforming implementation and checked at runtime.
9. Implementations may not add stronger public preconditions to a protocol method in version 1. A narrower operation must use a different method.
10. Implementations may add postconditions; both inherited protocol and implementation postconditions run.
11. Protocol contracts apply consistently whenever the conforming method is invoked, not only when the caller's static type is the protocol.
12. On normal return: save value, perform cleanup, check postconditions and invariants, return.
13. On recoverable exception: perform cleanup, check invariants, propagate if valid; abandon if invalid.
14. On cooperative cancellation: perform cleanup under masking, check invariants, continue cancellation if valid; abandon if invalid.
15. Contract or invariant violation always causes abandonment.

### 5.11 Task-boundary sendability

Every value crossing through task arguments, closure captures, task results, or channel messages is classified before child execution or message commit.

| Value category | Boundary behaviour |
|---|---|
| Primitive, string, frozen record or variant | Share |
| Frozen persistent collection | Share |
| Mutable record or mutable collection | Graph copy |
| Closure with only sendable captures | Share |
| Closure with mutable captures | Reject |
| Resource-owning value or resource borrow | Reject |
| Send port or receive port | Share as a frozen runtime capability |
| Channel controller | Normally retained by owning scope; transfer rules specification-stage |
| Task handle | May be observed only under structured-scope rules; not an arbitrary message value |
| Interpreter or other unsafe runtime capability | Reject |
| Dynamic value | Runtime graph inspection, then share/copy/reject |

Graph copy preserves cycles and alias relations inside the copied graph while producing no mutable alias back into the source graph. Large implicit copies produce advisories. Explicit task arguments are preferred over implicit closure capture.

### 5.12 Structured task groups and outcomes

1. One structured task-group substrate supports fail-fast, collect-all, race, and first-success operations.
2. Every child reaches a terminal state before its structured operation exits, except under hard or catastrophic termination.
3. Spawn returns a stable task handle. Awaiting a handle exposes that child's concrete recoverable exception inside the group.
4. Catching or explicitly converting an awaited child exception to Result marks it observed. An observed exception does not reappear at group exit unless rethrown.
5. An unhandled or unawaited child recoverable exception contributes once to the group's outward `AggregateException`.
6. Any child abandonment dominates ordinary group outcomes and causes parent abandonment in fail-fast, race, and first-success operations. The complete diagnostic retains recoverable exceptions and cancellations observed before quiescence.
7. Explicit collect-all/supervision returns child abandonments as data rather than resuming the failed child.
8. `TaskGroupReport[T, E]` is the general result-bearing tree containing successful values and other outcomes.
9. `TaskGroupFailure` is the diagnostic projection used when abandonment is the outward effect.
10. Lexical task-tree nesting is preserved canonically. Diagnostic views may also flatten leaves.
11. External cancellation coinciding with child failure preserves both. The group failure is reported or processed, and cancellation remains pending for redelivery.

### 5.13 Channel semantics

1. The ordinary channel is a multiple-producer, multiple-consumer competing-consumer queue.
2. Every committed message is delivered exactly once to one receiver.
3. A separate broadcast abstraction delivers each message to every subscriber; version-1 broadcast accepts only transitively frozen messages.
4. A channel exposes a controller, send ports, and receive ports. Exact names and syntax are specification-stage decisions.
5. Ports are frozen, sendable runtime capabilities and are conceptually duplicable without requiring explicit clone syntax.
6. Channel capacity is explicit: rendezvous, buffered with a stated capacity, or unbounded.
7. Rendezvous is the default construction. Capacity describes simultaneously queued messages, not lifetime message count.
8. Unbounded channels are explicit and subject to advisories for unbounded production or memory growth.
9. Closure is permanent and monotonic. A closed channel cannot reopen; a new lifetime requires a new channel.
10. Dropping one endpoint is distinct from globally closing the channel or losing all endpoints on one side.
11. Sending fails when globally closed or when no receivers remain. Receiving drains buffered messages and then reports closure when no further sends are possible.
12. Blocking send and receive are cooperative cancellation points. Nonblocking try operations are separate.
13. Cancellation before commit sends or consumes nothing. Cancellation after commit is delivered after the committed result is obtained.
14. Sends from one task commit in program order. Concurrent sends from different tasks have no source-defined relative order. The channel assigns monotonic commit sequence numbers.
15. Frozen messages are shared. Mutable messages are graph-copied once into channel-owned storage after capacity or receiver reservation and before atomic commit.
16. Channel misuse diagnostics may retain a bounded diagnostic-only event history unavailable to program logic.

### 5.14 Channel selection

1. Version-1 selection supports channel send, channel receive, task-handle completion, absolute deadline, and channel closure as a receive outcome.
2. Arbitrary async expressions are not directly selectable in version 1. They participate through structured child-task handles.
3. Static branch-oriented syntax is the primary form. Operation and handler are colocated; the construct may be expression-valued.
4. Branch setup may use endpoints, task handles, precomputed values, frozen local guards, deadlines, and restricted pure expressions. Effectful branch construction is prohibited.
5. Selection atomically commits exactly one operation. Losing branches have no visible effect.
6. Until selected, a selectable operation has no externally visible program effect; once selected, it commits exactly once.
7. Default tie-breaking uses deterministic rotating fairness local to one lexical select site and task activation. The first invocation begins in source order; later scans begin after the previous winner.
8. A continuously ready enabled branch in a static N-branch select is selected within at most N successful selections of that site.
9. An explicit priority form uses source-order preference and is subject to starvation diagnostics.
10. Randomised scheduling and tie-breaking belong in seeded test/stress mode rather than normal execution.
11. Blocking select is a cancellation point. Cancellation before commit selects nothing; cancellation after commit is delivered after the branch obtains its committed result.
12. Selecting one task completion does not cancel other tasks. Use the race operation to cancel losers.
13. Blocking select has no ordinary default branch. A visibly separate nonblocking `select now` form atomically checks ready operations and includes an explicit none-ready outcome.
14. Absolute deadlines are the semantic primitive. Relative timeout syntax may compute one deadline on entry and is subject to loop-reset diagnostics.
15. Conditional branches use precomputed local frozen booleans evaluated once on entry. Guards are not reactively reevaluated.
16. Closed-channel outcomes are explicit and ordinary select does not silently remove a branch.
17. Static heterogeneous selection is primary; dynamic homogeneous helpers support runtime-sized collections of receivers or task handles. Dynamic heterogeneous operation lists are deferred.
18. Endpoint waiter queues use FIFO fairness provisionally. Cancellation removes a waiter; re-registration joins the back.
19. The runtime maintains a bounded selection-event ring buffer containing ready sets, chosen branches, fairness cursor state, task/channel identities, and schedule seed in randomised tests.

### 5.15 Draft and verified modes

1. The project manifest sets a default mode; command-line overrides are available.
2. Draft mode accepts incomplete source and diagnoses missing annotations, propagation markers, and verified obligations without blocking happy-path execution where safe.
3. If an unmarked throwing call actually fails in draft mode, the recoverable exception still propagates.
4. Written annotations, contracts, resource scopes, no-escape rules, task isolation, channel sendability, protocol checks, abandonment, and cancellation semantics remain active in draft mode. Runtime checks fill gaps where static proof is unavailable.
5. Verified mode requires explicit failure propagation or handling, type consistency, exhaustive matching, resource correctness, sendability, effect compatibility, and other statically enforceable obligations.
6. Verified mode reports async regions where it cannot identify a reachable cancellation point; it does not prove termination.
7. Release builds require verified acceptance.
8. The two modes are development stages and acceptance standards, not two operationally different production languages.

### 5.16 Canonical source, imports, and differential testing

1. There is one canonical persisted source representation.
2. Formatting and automatically inserted known imports are visible ordinary source edits.
3. The toolchain may insert imports from the current project, standard library, and pinned dependencies.
4. Adding a new external dependency requires an explicit manifest and lockfile change. A hallucinated package name cannot silently alter dependencies.
5. Python is a differential behavioural oracle only for semantically matched programs over a declared common input and observation domain.
6. Before differential testing, define the valid input domain, observable outputs and effects, canonicalisation rules, intended semantic differences, and resource/time limits.
7. For finite conformance suites, every declared shared-domain case should match. For fuzzing, any tolerance must be specified before observing results.
8. The target-language specification and direct conformance tests remain authoritative for target-specific semantics.

### 5.17 Specification-stage choices

The specification writer must choose and record exact syntax or surface API for:

- binding and constant declarations;
- record update/copy syntax;
- frozen and mutable collection names;
- `Dyn` spelling;
- resource-provider declarations, yield, scope and borrow syntax;
- exception-to-Result conversion and Err propagation;
- error-effect variables and unions;
- protocol and predicate declaration syntax;
- invariant field-control mechanisms;
- channel controller and port names;
- rendezvous, buffered and unbounded construction;
- send, receive, closure and nonblocking operations;
- static select, priority select, nonblocking select, deadlines and guards;
- dynamic homogeneous selection helpers;
- task-group operation syntax;
- cancellation-check syntax;
- error-category syntax and catches;
- hierarchical diagnostic-code display punctuation;
- directory-module mechanism;
- type-only module-cycle policy;
- closure reassignment annotation;
- package manifest format;
- and test-framework syntax.

These are reviewed specification-stage choices, not permission to alter the semantic commitments above.

---

## Part VI — Current Design Summary

A concise snapshot of the current language design. Detailed rationale appears in Part VII. Status markers are granular.

---

### 6.1 Syntax and source files

- **Blocks**: Curly braces; indentation is not syntactically significant. **Decided**
- **Statements**: Newline-oriented; no mandatory semicolon. Exact multiline-expression rules are specification-stage. **Decided direction**
- **Functions**: Working declaration prior is `fn`; explicit `self`; postfix optional return annotation. **Decided direction**
- **Async functions**: Explicit `async fn`; only async functions may suspend. **Decided**
- **Strings**: Unicode strings; interpolation syntax specification-stage, with familiar brace interpolation preferred. **Decided direction**
- **Lambdas**: Concise arrow-style form plus block form. **Decided direction**
- **Formatter**: Canonical, deterministic, idempotent, available from the first implementation. **Decided**
- **Source representation**: One canonical persisted form; tool transformations are visible edits. **Decided**

### 6.2 Values, records, and collections

- **Primitives**: Arbitrary-precision `Int`; IEEE-754 64-bit `Float`; non-coercing `Bool`; immutable Unicode `Str`; `Unit`. **Decided direction**
- **Ordinary records**: Transitively frozen, structural equality, value-like, no observable identity. **Decided**
- **Mutable records**: Explicit identity-bearing reference types. **Decided**
- **Frozen updates**: Return new values; old values remain unchanged. **Decided**
- **Collections**: Separate frozen and mutable categories. Exact names specification-stage. **Decided semantics**
- **Frozen collection conversions**: Immutable snapshots and independent mutable copies; no mutable alias may change a frozen value. **Decided**
- **Variants**: Closed nominal sum types with exhaustive matching. **Decided**
- **Protocols**: Structural conformance; optional explicit conformance declaration may be provided for diagnostics. **Decided direction**
- **No class inheritance**. **Decided**

### 6.3 Bindings, state, and scope

- **Binding reassignment**: Allowed by default; distinct from object mutation. Exact keyword syntax specification-stage. **Decided semantics**
- **Constant binding**: Optional explicit form; exact syntax specification-stage. **Specification-stage decision**
- **Module constants**: Frozen module-level constants allowed. **Decided**
- **Mutable module globals**: Prohibited in version 1. **Decided**
- **Long-lived state**: Root-created, narrowly decomposed, explicitly passed, single task owner. **Decided direction**
- **Lexical scope**: Braced lexical blocks; names cannot be used before initialization. **Decided direction**
- **Closures**: Capture lexical bindings; closure reassignment syntax specification-stage. Sendability depends on captures. **Decided direction**

### 6.4 Types and annotations

- **Default**: Dynamic, strong, non-coercing execution. **Decided**
- **Gradual semantics**: Transient checks, not wrappers/proxies. **Decided**
- **Present annotations**: Runtime-enforced in draft and verified modes. **Decided**
- **Concrete record annotation**: Requires concrete runtime type. **Decided**
- **Protocol annotation**: Complete immediate shallow shape/effect check; nested contents checked at typed uses and writes. **Decided**
- **Dynamic mismatch**: Abandonment with boundary/annotation/origin diagnostics. **Decided**
- **Dynamic callable**: Must be narrowed to a typed callable with known `throws` before verified invocation. **Decided**
- **Nullability**: `T? == Option[T]`, `null == None`; uninitialised binding is distinct. **Decided**
- **Generics**: Required at least for collections, variants, Results, tasks, channels, and effect forwarding. Exact system specification-stage. **Decided direction**

### 6.5 Functions, methods, protocols, and contracts

- **Parameters**: Explicit; argument passing follows value category. **Decided direction**
- **Methods**: Explicit `self` working direction. **Decided direction**
- **Protocol contracts**: Automatically inherited by implementations and checked at runtime. **Decided**
- **Protocol preconditions**: Implementations cannot add stronger public preconditions in version 1. **Decided**
- **Implementation postconditions**: May supplement inherited protocol postconditions. **Decided**
- **Contracts**: `requires`/`ensures` in signatures. **Decided**
- **Contract language**: Restricted, total, effect-free subset; reusable non-recursive predicates. **Decided**
- **`old(expr)`**: Entry snapshot for primitive/frozen/safely snapshot-capable results. **Decided**
- **Invariants**: Distinct from method contracts; invariant-relevant fields have controlled mutation. **Decided direction**
- **Exit ordering**: Cleanup before postconditions/invariant checks; invariant failure supersedes exception or cancellation. **Decided**

### 6.6 Error handling and effects

- **Failure classes**: Recoverable exception, cancellation, abandonment, hard termination are distinct. **Decided**
- **Recoverable exceptions**: Declared effects; explicit callsite propagation or handling in verified source. **Decided**
- **Abandonment**: Violated assumption or unavailable safe continuation; not catchable in the failed task. **Decided**
- **Checked alternatives**: Provided when a failure is a legitimate expected branch. **Decided direction**
- **Results**: Core `Result[T,E]` with lightweight provenance and bounded explicit context. **Decided**
- **No mixed failure channels**: A function cannot both throw recoverably and return Result. **Decided**
- **Default fallback**: Broad untyped suppression prohibited; unqualified fallback only for one known concrete error type. **Decided**
- **Effect polymorphism**: Minimal error-set variables, finite unions, and callback forwarding in version 1. **Decided**
- **Error types**: Concrete nominal types; zero-or-one catch category in version 1; closed error enums supported. **Decided**
- **Top-level unhandled exception**: Ordinary cleanup, unsuccessful exit, recoverable-exception diagnostic. **Decided**

### 6.7 Resource management

- **Memory**: Garbage collected. **Decided**
- **Resources**: Scoped resource providers with exactly one yield. **Decided**
- **Resource scope**: Required acquisition form and expression-valued. **Decided semantics; syntax specification-stage**
- **Borrows**: Non-escaping, same-task, may cross await while scope active. **Decided**
- **Normal release**: Runs on return, recoverable exception, cancellation; cannot suppress pending outcome. **Decided**
- **Abandonment release**: Restricted best-effort close/revoke/release/rollback actions only. **Decided**
- **`defer`**: Non-resource cleanup on return/exception/cancellation; not during abandonment. **Decided**
- **Cleanup failures**: Unified aggregate/precedence table. **Decided**
- **Scope-width diagnostics**: Best-effort liveness/data-flow advisories. **Provisional**
- **Resource-owning records**: Deferred; design must not foreclose. **Deferred**

### 6.8 Structured concurrency

- **Lifetime model**: Structured task groups; no ordinary fire-and-forget. **Decided**
- **Operation modes**: Fail-fast, collect-all, race, first-success over one substrate. **Decided**
- **Task handles**: Stable; direct await exposes concrete recoverable error. **Decided**
- **Observed errors**: Caught or explicitly captured errors do not reappear; unhandled/unawaited errors aggregate at group boundary. **Decided**
- **Fail-fast recoverable failure**: Always outward `AggregateException`, even one child. **Decided**
- **Child abandonment**: Dominates ordinary fail-fast/race/first-success and abandons parent after quiescence. **Decided**
- **Collect-all**: Returns `TaskGroupReport[T,E]` including successful values and terminal outcomes. **Decided**
- **Task tree**: Preserved in reports and diagnostics. **Decided**
- **Cancellation**: Cooperative at visible points; cannot be caught or discarded. **Decided**
- **Cleanup masking**: Pending cancellation delayed during cleanup then redelivered. **Decided**
- **Cancellation invariants**: Checked before cancellation leaves public mutable operation. **Decided**
- **Hard termination**: Separate escalation; task-local only for independently isolated workers, otherwise process-level. **Decided direction**

### 6.9 Channels

- **Ordinary channel**: MPMC competing-consumer queue; each message delivered exactly once. **Decided**
- **Broadcast**: Separate abstraction; frozen messages only in version 1. **Decided direction**
- **Capabilities**: Controller plus send and receive ports; ports are frozen and sendable. **Decided semantics; naming specification-stage**
- **Capacities**: Explicit rendezvous, buffered(capacity), unbounded; rendezvous is default. **Decided**
- **Closure**: Permanent and monotonic; no reopening. **Decided**
- **Send/receive cancellation**: Waiting operations are cancellation points; commit atomicity prevents ambiguous delivery. **Decided**
- **Nonblocking operations**: Separate try-send/try-receive outcomes. **Decided direction**
- **Ordering**: Same-task program order; global commit sequence; concurrent-sender order unspecified. **Decided**
- **Mutable messages**: Graph-copied once after reservation and before commit. **Decided**
- **Diagnostics**: Structured closure report and bounded diagnostic-only event history. **Decided direction**

### 6.10 Channel selection

- **Participants**: Channel send/receive, task completion, deadline, closure outcome. **Decided**
- **No arbitrary async branch**: Use a structured child task and select on its handle. **Decided**
- **Primary form**: Static branch-oriented, operation adjacent to handler, expression-valued. **Decided direction**
- **Branch setup**: Pure/precomputed only. **Decided**
- **Commit**: Exactly one atomic winner; losing alternatives have no visible effect. **Decided**
- **Default fairness**: Deterministic rotating fairness per lexical site/task activation. **Decided direction**
- **Priority form**: Explicit source-order priority with starvation diagnostics. **Decided**
- **Randomisation**: Seeded test/stress mode, not normal execution. **Decided**
- **Nonblocking**: Separate `select now`; no ordinary default branch in blocking select. **Decided**
- **Timeout**: Absolute deadline semantic primitive; relative sugar subject to reset diagnostics. **Decided**
- **Guards**: Precomputed frozen booleans read once. **Decided**
- **Task lifetime**: Selecting one task does not cancel losers; use race for that. **Decided**
- **Dynamic selection**: Homogeneous receiver/task helpers only in version 1. **Decided direction**
- **Diagnostics**: Bounded ring buffer of ready sets, winner, fairness cursor, identities and seed. **Decided direction**

### 6.11 Modules and imports

- **Unit**: One file, one module. Directory modules use a language-native mechanism. **Decided; exact mechanism specification-stage**
- **Imports**: Known imports may be inserted visibly from project, standard library, or pinned dependencies. **Decided**
- **New packages**: Explicit manifest/lockfile action. **Decided**
- **Visibility**: Exported and module-private only. Exact export keyword specification-stage. **Decided direction**
- **Runtime value-initialisation cycles**: Rejected with full-cycle diagnostic. **Decided**
- **Type/declaration cycles**: Policy specification-stage. **Open semantic detail**
- **Paths**: Absolute. **Decided**
- **Runtime loading**: Available for REPL and agentic loops. **Decided**

### 6.12 Diagnostics

- **Architecture**: Structured diagnostic objects independent from rendering. **Decided**
- **Display**: Multi-span source, notes, help, task/resource/channel provenance. **Decided direction**
- **Stable codes**: Hierarchical, e.g. `A.TYPE.DYNAMIC_MISMATCH`; JSON exposes outcome/domain/reason separately. **Decided direction**
- **Local values**: Bounded, cycle-safe, side-effect-free, secret-aware, type-aware. **Decided**
- **Result provenance**: Creation span, error type/code, lightweight propagation chain, task lineage, explicitly attached bounded context. **Decided**
- **Concurrent diagnostics**: Lexical task tree plus optional flattened leaves. **Decided**
- **Channel/select diagnostics**: Sequence IDs, endpoint identities, ready sets, fairness state, bounded event ring. **Decided direction**
- **Parser recovery**: Multiple errors, root error prominent, cascade notes. **Decided**
- **Performance budgets**: Judgment-based provisional targets: ~25% geometric-mean default, ~2× verified, deep ceiling `T + min(9T, 2h)`, report target under 5s and default hard render budget ~30s. **Provisional**
- **Modes**: Default, quiet, deep, JSON. Exact flags specification-stage. **Decided direction**

### 6.13 Toolchain and validation

- **CLI**: Run, check, format, REPL, test; draft/verified and diagnostic-mode options. **Decided direction**
- **Formatter**: Mandatory canonical edit normalisation. **Decided**
- **REPL**: First-class; runtime module loading. **Decided**
- **Schedule stress testing**: Seeded random task/select scheduling with seed recorded on failure. **Decided direction**
- **Differential testing**: Python acts as behavioural oracle only on an explicitly declared common domain and observable projection. **Decided**
- **Release**: Verified acceptance required. **Decided**

### 6.14 Core and standard-library boundary

**Language/runtime core**:

- primitives and frozen/mutable collection machinery;
- `Option`, `Result`, error-set variables/unions;
- transient runtime type checks and protocol shape metadata;
- `AggregateException`, `TaskGroupReport`, `TaskGroupFailure`;
- structured task groups, cancellation, task handles;
- channel controller/ports, capacities, closure, selection and fairness;
- contracts, restricted predicates, invariants and `old` snapshots;
- resource providers, scopes, borrows and release registration;
- `defer` and exit unwinding;
- hierarchical diagnostics and bounded capture;
- canonical source-map and auto-import resolver.

**Standard library**:

- file, network, process and database resource providers;
- JSON, HTTP, regex, math, datetime and common data tooling;
- ordinary protocols such as `Comparable`, `Hashable`, `Iterable`;
- standard concrete errors and catch categories;
- higher-level channel fan-in, broadcast, request-response, and selected homogeneous helpers.

There is no ordinary structural `Closeable` protocol that establishes ownership or automatic cleanup.

---

## Part VII — Design Reasoning

This part records why the current design was chosen. The specification writer should use it to resolve edge cases consistently and to select syntax without altering semantics.

---

### 7.1 Syntax

#### 7.1.1 Block delimiters

Curly braces are decided. Indentation-sensitive syntax creates mechanically common formatting failures, makes copied fragments fragile, and requires the formatter and parser to infer block boundaries from whitespace. Braces make scope boundaries explicit to both LLM and reviewer and support deterministic formatting.

Indentation remains mandatory as canonical style but not as syntax. The formatter places braces and indentation consistently. Single-line blocks may be allowed only where the formatter preserves readability.

#### 7.1.2 Statement separation

Newlines separate ordinary statements; semicolons are not mandatory. The specification must define continuation rules for:

- open parentheses, brackets and braces;
- operators at line boundaries;
- chained calls;
- multi-line strings;
- and branch expressions.

The parser should prefer clear diagnostics over aggressive implicit continuation. The formatter determines the canonical form.

#### 7.1.3 Keyword selection

The specification writer evaluates candidate keywords by:

1. the action the keyword signals locally;
2. the syntax an LLM expects to follow it;
3. semantic differences that affect nearby code;
4. whether those differences are visible in surrounding syntax;
5. harmful assumptions a reviewer might transfer;
6. and ordinary human familiarity.

Current working priors include:

| Concept | Working prior | Notes |
|---|---|---|
| Function declaration | `fn` | Strong declaration prior from Rust and several modern languages |
| Task creation | `spawn` | Concurrent work is locally clear; surrounding task-group syntax shows structured lifetime |
| Waiting | `await` | Familiar suspension prior |
| Variant matching | `match` | Familiar exhaustive pattern prior |
| Recoverable propagation | `try` | Signals failure surface; exact grammar differs from Python and must remain visible |
| Export | `pub` or equivalent | Specification-stage comparison required |
| Resource scope | `use` or equivalent | `use` also means import in Rust, so surrounding assignment/block form must disambiguate |
| Binding | unresolved | JavaScript `let` is reassignable; Rust `let` is immutable unless `mut`; neither prior fully determines the decision |
| Mutable record declaration | `mutable record` working form | Semantically explicit; exact compactness open |
| Contract clauses | `requires`, `ensures` | Established Design by Contract terminology |

Illustrative syntax in this document is not automatically final syntax. The specification writer should record each consequential choice and its comparison set.

#### 7.1.4 Type annotations

Parameter annotations use a familiar name-colon-type form. Return annotations follow the parameter list and precede the body. Annotations are optional unless required by an exported interface, checked effect, protocol boundary, or other specification rule.

The specification should keep the dynamic type visually explicit when named, and should make error effects and nullability searchable.

#### 7.1.5 String interpolation

Brace-based interpolation is preferred because it is familiar and compact. The specification must define escaping, format modifiers, evaluation order, and whether interpolation invokes only safe string representation or arbitrary conversion methods. Diagnostic rendering never calls user code.

#### 7.1.6 Lambda syntax

Expression and block lambdas should share one visual family. Parameter and effect annotations must remain possible. A throwing lambda's effect participates in version-1 error-effect forwarding.

---

### 7.2 Execution model

#### 7.2.1 Statements and expressions

The language is expression-oriented where doing so improves composition without obscuring control flow. Blocks, matches, resource scopes, and selection may produce values. Function bodies remain readable as ordinary sequential code.

Expression orientation is not a goal by itself. Constructs whose value would be surprising should remain statements. The formatter must make block-valued expressions visually clear.

#### 7.2.2 Call semantics and argument passing

Argument behaviour follows value category:

- primitives and frozen values are shared because mutation is unobservable;
- mutable values are passed by sharing within one task;
- task/channel boundaries graph-copy mutable values under the sendability rules;
- resource values pass only through scoped borrows;
- runtime capabilities follow explicit capability rules.

Evaluation order is left-to-right unless a construct explicitly defines concurrent evaluation. Function arguments are evaluated before the call. Selection branch setup is restricted so that evaluating alternatives cannot produce hidden effects.

#### 7.2.3 Exit taxonomy

Normal return, recoverable exception, cooperative cancellation, abandonment, hard termination, and catastrophic termination are distinct. The implementation should not encode them as indistinguishable instances of one ordinary exception hierarchy. Each has separate cleanup, task-propagation, and diagnostic rules.

---

### 7.3 Values and data model

#### 7.3.1 Frozen and mutable records

The original mutable-by-default record design was rejected because it increased aliasing and mutation history. The revised model uses:

```text
record User {
    name: Str
    age: Int
}
```

for a transitively frozen value, and:

```text
mutable record Buffer {
    bytes: MutableList[Int]
}
```

for an identity-bearing reference value.

A frozen update returns a new value:

```text
fn renamed(self, newName: Str) -> User {
    return self with { name: newName }
}
```

The exact copy/update syntax is specification-stage work.

**Why type-level mutability**: Per-instance mutability would force a reader to track whether one particular `User` was created mutable, frozen later, or aliased before freezing. Separate declarations keep the property in the type.

**Why transitive freezing**: A record containing a mutable list is not actually safe to share. Rejecting mutable reachable fields gives a simple invariant: every reachable value from a frozen root is frozen.

**Identity**: Mutable records have reference identity inside their owning task. Frozen values do not expose object identity. The specification must define structural equality and hashing, especially for nested collections and variants.

#### 7.3.2 Frozen collections

Frozen collections are persistent in observable behaviour:

```text
let first = [1, 2, 3]
let second = first.appended(4)
```

`first` remains unchanged. The runtime may share internal nodes or use copy-on-write.

A read-only view over mutable storage is insufficient because later mutation would change the supposedly frozen value. Freeze and mutable-copy operations therefore create snapshot isolation even if physical copying is delayed.

Collection families should include at least:

- ordered sequence;
- key-value map;
- set;
- corresponding mutable forms where justified.

Names and exact APIs are specification-stage decisions. Iteration order must be explicit: sequence order is defined; map/set order must either be stable and specified or explicitly unordered with deterministic diagnostic rendering.

#### 7.3.3 Primitive types

- `Int`: arbitrary precision; ordinary integer overflow does not occur.
- `Float`: IEEE-754 binary64. NaN policy remains an important specification-stage semantic decision. The preference is to make accidental invalid numeric states highly visible, but interoperability and numerical workloads may justify IEEE propagation plus diagnostics rather than abandonment.
- `Bool`: no truthiness conversion from numbers, strings, collections, or null.
- `Str`: immutable Unicode with explicitly defined indexing and normalization behaviour.
- `Unit`: result of operations with no meaningful value.

Fixed-width integers may be added for interoperability later. Their overflow behaviour must be explicit.

#### 7.3.4 Option and Result

`Option[T]` and `Result[T,E]` are core types because nullability, error storage, exhaustive matching, task outcomes, and diagnostic provenance depend on them.

`T?` is syntax for `Option[T]`; `null` is `None`. Nested optionality remains possible where semantically meaningful, but domain variants are preferred when states have different meanings.

`Err` stores lightweight provenance rather than arbitrary local snapshots. See Section 7.7.8.

#### 7.3.5 Mutable-state design guidance

The language does not attempt to ban every large state object statically. Instead, diagnostics may warn about:

- mutable records with many unrelated fields;
- mutable state passed through layers that do not use it;
- many mutation sites;
- unclear effective ownership;
- long mutation-to-use spans;
- and state-bag parameters functioning as implicit globals.

These are advisories. A simulation or UI model may legitimately have substantial state; the goal is to make the cost visible, not reject useful programs dogmatically.

---

### 7.4 Names, scopes, modules, and closures

#### 7.4.1 Module system

One file is one module. A directory-module mechanism is language-native rather than Python-specific. Runtime value-initialisation cycles are rejected with a full cycle trace. Type-only/declaration cycles depend on the eventual type-resolution model.

Exports are explicit and module-private is the default. Only two ordinary visibility levels exist.

Known imports may be inserted automatically as visible edits. Name resolution considers:

1. current module and lexical scope;
2. current project;
3. standard library;
4. pinned dependencies.

A new external dependency requires explicit manifest/lockfile modification. The tool may propose candidates but never installs one from an unresolved hallucinated name.

#### 7.4.2 Module state

Frozen module constants are allowed. Ordinary mutable module globals are prohibited in version 1.

Long-lived mutable services are created in a root scope:

```text
fn main() {
    let database = openDatabaseService(config)
    let cache = MutableCache(...)
    runApplication(database, cache)
}
```

The example is illustrative; a resource-owning service would itself need a root resource scope.

A future owner-bound module-state construct could make a dependency locally visible, but this is deferred until real examples justify the added mechanism.

#### 7.4.3 Closures

Closures capture lexical bindings. Reassigning a captured binding should likely require explicit syntax because hidden closure mutation expands the mutable-state horizon. The specification writer should compare Python `nonlocal`, Rust capture modifiers, and explicit capture lists.

A closure is sendable only if every capture is sendable. Mutable captures are rejected rather than silently copied because copying a hidden capture would make the closure's meaning diverge from local expectations. Prefer explicit task arguments.

---

### 7.5 Functions, records, and protocols

#### 7.5.1 Structural protocol conformance

Protocols describe required method signatures and inherited contracts. Conformance is structural: a type need not name the protocol to satisfy it. Go interfaces and TypeScript structural typing are relevant precedents; Swift protocols are not structural because they require explicit conformance declarations.

An optional declaration such as `satisfies Protocol` may be provided to request an earlier declaration-site check and better diagnostics. It does not create nominal subtyping.

#### 7.5.2 Protocol shape checks at dynamic boundaries

When a dynamic value enters a protocol-annotated parameter, the runtime checks the complete immediate protocol shape rather than waiting for method calls one by one. This catches a false central assumption at the boundary.

The shape check includes effect compatibility. A method that may throw errors outside the protocol's declared effect is not compatible merely because its parameter and return shapes match.

Nested return values remain transiently checked when consumed.

#### 7.5.3 Behavioural substitutability through inherited contracts

Structural shape alone cannot establish behaviour. Protocol contracts therefore execute for every conforming method invocation.

```text
protocol Sortable {
    fn sort(self) -> List[Int]
        ensures result.isSorted()
}
```

Every implementation inherits the postcondition. It may add further postconditions.

Implementations cannot add stronger public preconditions in version 1. General logical implication is not required. A narrower operation uses a separate method.

Generated conformance tests may sample values allowed by protocol preconditions, but runtime contracts remain authoritative.

---

### 7.6 Types and annotations

#### 7.6.1 Why dynamic by default remains the preference

The language targets rapid LLM generation and iterative correction. Requiring complete annotations before happy-path execution creates extra correction turns and forces decisions before downstream code has clarified the intended types.

Dynamic default does not mean weak typing. Invalid operations fail rather than coerce silently. Annotations are valuable for:

- exported interfaces;
- protocol requirements;
- checked error effects;
- contracts;
- task boundaries;
- and places where the author wants a stronger local assumption.

The empirical evidence that dynamic languages reduce correction-loop cost is suggestive rather than conclusive. The decision also follows independently from left-to-right generation and progressive refinement.

#### 7.6.2 Why transient semantics

Three principal gradual-typing models were considered.

**Advisory-only annotations** were rejected because typed functions could not rely on their signatures at runtime.

**Guarded/proxy semantics** can preserve stronger boundary guarantees but create wrapper identity, mutable proxy, and higher-order function complexity. This conflicts with the simple identity model and Python interpreter staging.

**Transient semantics** performs shallow checks at boundaries and additional checks when typed operations rely on nested values. It preserves ordinary object identity and is implementable incrementally.

The trade-off is repeated checks and less mathematically pure blame than guarded systems. The design compensates with explicit multi-span source attribution.

#### 7.6.3 Boundary checking rules

For:

```text
fn balance(account: Account) -> Float {
    return account.balance
}
```

entry checks that the value is concretely `Account`. The call does not accept an unrelated structural record.

For:

```text
fn render(writer: Writable) {
    ...
}
```

entry checks all required immediate methods, arities, declared effects, and protocol metadata.

For:

```text
record Account {
    balances: Vector[Int]
}
```

entry need not inspect every integer. Reading `balances` in a `Vector[Int]` context checks the outer vector; consuming an element as `Int` checks that element; writing checks before insertion.

Bulk operations may validate once and carry temporary trusted metadata for that operation. Frozen verified values may carry durable integrity metadata.

#### 7.6.4 Draft and verified interaction

Draft mode:

- permits absent annotations;
- reports missing failure markers without blocking safe happy-path execution;
- performs runtime checks for written annotations and safety boundaries;
- allows code to execute while the verified obligation set remains incomplete.

Verified mode:

- statically validates all resolvable annotations;
- requires explicit error propagation/handling;
- rejects unresolved sendability/resource/effect obligations;
- requires exhaustive matching;
- still performs runtime checks where truly dynamic values enter typed code.

The modes differ in acceptance and proof, not in the meaning of a written annotation.

#### 7.6.5 Dynamic-type diagnostics

A dynamic mismatch diagnostic should make the causal boundary explicit:

```text
A.TYPE.DYNAMIC_MISMATCH

  --> main.lang:48:26
48 | let amount = balance(value)
   |                      ^^^^^ expected Account, received UserRecord

`balance` relies on:
  --> payments.lang:12:12
12 | fn balance(account: Account) -> Float
   |            ^^^^^^^^^^^^^^^^

Value origin:
  --> main.lang:45:13
45 | let value = loadDynamicValue()
   |             ^^^^^^^^^^^^^^^^^^ returned UserRecord
```

The stack trace remains available, but the primary span is the boundary where the typed assumption becomes active. For a nested mismatch discovered later, the typed use site is primary and the original boundary remains secondary.

#### 7.6.6 Dynamic values at task and channel boundaries

Unknown static type is not permission to cross an isolation boundary. The runtime traverses the graph before task start or message commit and:

- shares frozen values;
- copies mutable graphs;
- rejects resources, borrows, unsafe capabilities, and closures with mutable captures.

If inspection fails or encounters unsupported runtime objects, the operation fails before the child begins or message commits. This is a safety check in draft mode and a static-plus-runtime check in verified mode.

---

### 7.7 Error handling and effects

#### 7.7.1 Failure taxonomy

The design follows the central distinction in Duffy's error model while adapting it to structured tasks and dynamic execution.

**Recoverable failure** occurs despite documented preconditions being satisfied and admits a safe program response: missing file, malformed external input, network refusal, validation failure.

**Abandonment** means a programmer-declared assumption failed or safe continuation is unavailable: contract violation, invariant violation, invalid non-null/type assertion, impossible internal state, fatal memory exhaustion.

The classification belongs to each operation's contract. It is not determined merely by whether an implementation can technically catch a runtime exception.

#### 7.7.2 Abandoning and checked forms

An operation may provide two differently contracted forms:

```text
items[index]          // precondition: valid index; violation abandons
items.get(index)      // returns Option[T]
```

The language does not require a checked twin mechanically for every abandonment. It requires the standard library to expose recoverable outcomes whenever callers can legitimately plan for them.

Fatal process memory exhaustion remains nonrecoverable. A quota or bounded pool may expose a recoverable refusal before exhaustion.

#### 7.7.3 Recoverable exception syntax and visibility

Functions declare a finite recoverable error set. Verified call sites visibly propagate or handle it. Draft source may omit the marker while receiving a diagnostic; if failure occurs, the exception still propagates.

Catches may name concrete types or categories. Broad catch-all handling should be unavailable or visually exceptional and warned, because it suppresses future errors the author did not anticipate.

A typed fallback names the handled condition:

```text
try loadConfig(path)
else on FileNotFound => Config.defaults()
```

An unqualified fallback is accepted only for one statically known concrete error type.

#### 7.7.4 Exceptions versus Result

Use exceptions when failure changes control flow immediately. Use `Result` when failure is part of the returned data model.

```text
fn readConfig(path: Str) -> Config throws IOError, ParseError
```

versus:

```text
fn validateRows(rows: List[Row])
    -> List[Result[ValidRow, ValidationError]]
```

A function cannot expose both channels. This keeps every call site's failure model singular.

Conversions are explicit. Illustrative examples may use `capture`, `propagate`, or `try ... else catch`, but the specification writer selects the final surface form.

#### 7.7.5 Minimal effect polymorphism

Higher-order functions need to forward callback errors:

```text
fn map[T, U, E](
    values: List[T],
    transform: fn(T) -> U throws E
) -> List[U] throws E
```

Without this, throwing callbacks would either be prohibited, erased to an unconstrained top error, or require Result boilerplate. All are contrary to familiar higher-order code.

Version 1 supports nominal error-set variables and finite union:

```text
fn compose[A, B, C, E1, E2](
    first: fn(A) -> B throws E1,
    second: fn(B) -> C throws E2
) -> fn(A) -> C throws E1 | E2
```

The implementation may initially use conservative widening in complex inference cases, but exported signatures and explicit annotations must preserve the semantic model.

This is not a general effect system. Cancellation, abandonment, mutation, I/O, and resource ownership are not all encoded as arbitrary user-extensible effects in version 1.

#### 7.7.6 Dynamic callables

A `Dyn` callable has no known error set. Verified code must narrow it:

```text
let callback:
    fn(Input) -> Output throws IOError =
        checkedFunction(dynamicValue)
```

The narrowing performs function shape/effect validation. Calling an unconstrained dynamic callable in verified code would destroy local failure visibility and is rejected.

#### 7.7.7 Error types and categories

Every recoverable error has a concrete nominal type with fields useful for handling and diagnosis.

An error may name one catch category:

```text
error FileNotFound category IO {
    path: Str
}
```

Categories are membership labels, not inheritance. They contribute no fields or implementation.

Version 1 allows zero or one category. Runtime representation should use a collection-capable membership field internally so later multiple membership is not foreclosed.

Closed error enums are preferable for domains whose complete set is intentionally owned by one API.

Nominality does not automatically make catching exhaustive. Exhaustiveness is possible only when a finite declared throws set or closed enum is known.

#### 7.7.8 Result provenance

Each `Err` stores lightweight data:

- concrete error type;
- stable hierarchical code;
- creation source span;
- propagation source chain;
- task lineage;
- explicitly attached bounded context.

```text
return Err(error)
    .context("path", path)
    .context("row", rowNumber)
```

The runtime does not snapshot arbitrary locals for every Result. If an Err becomes unhandled, stored provenance is combined with the remaining live stack and bounded diagnostic capture.

#### 7.7.9 Top-level failure

An unhandled recoverable exception escaping the entry point:

1. performs ordinary exception cleanup;
2. emits a recoverable-error diagnostic;
3. exits with failure status;
4. does not become abandonment merely because nobody handled it.

This distinction matters for logs, testing, and supervising external processes.

---

### 7.8 Contracts and invariants

#### 7.8.1 Purpose

Contracts encode simple, executable assumptions and consequences close to the function signature. Their central use is not automatic proof of sophisticated abstract properties. They make assumptions visible and cause immediate abandonment when those assumptions are false.

Examples include:

```text
requires amount > 0
ensures result.length == old(input.length)
ensures result == expectedTransform(input)
```

The last form is appropriate only where `expectedTransform` is expressible in the restricted predicate language and remains simpler than the implementation being checked.

#### 7.8.2 Restricted contract language

Version 1 permits:

- primitive arithmetic and comparisons;
- Boolean operations;
- frozen field reads;
- structural equality of frozen values;
- collection length and membership;
- total safe collection operations;
- pattern matching on closed variants;
- bounded `all` and `any`.

It prohibits:

- mutation;
- I/O;
- resources;
- task operations;
- cancellation;
- throwing;
- randomness/time;
- unsafe indexing;
- unbounded allocation;
- arbitrary recursion;
- and general calls.

This gives predictable termination and evaluation cost. The exact bound policy for collection quantifiers belongs to the specification and diagnostics budget.

Reusable predicates are non-recursive declarations in the same subset.

#### 7.8.3 `old(expr)`

`old(expr)` evaluates at entry and stores the result needed by a postcondition. The legality depends on the result, not necessarily the mutability of every object referenced while computing it.

```text
old(account.balance)
```

is valid if `balance` is a primitive. Capturing `old(account)` is invalid unless `Account` defines a safe immutable snapshot.

The runtime should avoid implicit arbitrary deep copy because it is expensive and obscures contract cost.

#### 7.8.4 Method conditions and record invariants

`requires`/`ensures` describe one operation. An invariant describes the externally valid states of a mutable type.

A method may temporarily violate an invariant internally. The invariant must hold at public boundaries and at every visible cancellation point from which the method can unwind.

Invariant-relevant fields require controlled mutation. The design does not yet commit to `private` as the only mechanism; restricted setters, module access, or another simple field-control system may be selected.

#### 7.8.5 Protocol contract inheritance

Protocol contracts execute for every conforming method. Implementations do not prove or restate them.

Implementation precondition strengthening is prohibited syntactically in version 1. If the protocol has `requires x > 0`, an implementation cannot add any public `requires` clause to that method. This avoids logical implication checking.

Implementation postconditions may be added and run alongside inherited postconditions.

#### 7.8.6 Exit ordering

Normal return:

1. compute and save return value;
2. run normal resource release and permitted `defer` callbacks;
3. check postconditions and invariants against final visible state;
4. return saved value.

Recoverable exception:

1. preserve exception;
2. run normal release and `defer`;
3. check invariants;
4. propagate if valid;
5. otherwise abandon and record the pending exception as context.

Cancellation:

1. observe cancellation at a visible point;
2. run permitted cleanup under masking;
3. check invariants;
4. redeliver cancellation if valid;
5. otherwise abandon and record that cancellation was pending.

Abandonment does not run arbitrary contract recovery logic. Restricted resource release may occur; no postcondition is checked because no normal result exists.

---

### 7.9 Resource management

#### 7.9.1 Why structural RAII was rejected

In a shared-reference model, “close when the binding leaves scope” does not identify which alias owns release. Final-reference cleanup makes lifetime timing invisible, interacts poorly with cycles, and cannot naturally await asynchronous release. General affine ownership would solve ownership but require long-span move-state tracking contrary to the locality objective.

The adopted approach makes resource lifetime a distinct lexical construct rather than trying to infer ownership from ordinary references.

#### 7.9.2 Resource-provider semantics

Illustrative syntax:

```text
resource fn openFile(path: Str) yields File {
    ...
}

use file = try openFile(path) {
    process(file)
}
```

Exact ordering of `try`, `use`, and declaration syntax remains specification-stage work.

A provider establishes exactly one lifetime. Acquisition may fail before yield. After yield, the caller body runs while nested provider scopes remain active.

A user-defined provider may compose resources:

```text
resource fn openConfiguredFile(config: Config) yields File {
    use file = try openFile(config.path) {
        try configure(file, config)
        yield file
    }
}
```

This is scoped delegation, not returning an ordinary File value.

#### 7.9.3 Normal release versus abandonment-safe release

A generator-like “everything after yield runs on all exits” rule is rejected. It would allow arbitrary state mutation after an invariant has failed.

Normal release may run on return, exception, or cancellation and can select rollback/ordinary-close behaviour based on that exit class. It cannot suppress the pending outcome.

Abandonment invokes only pre-registered release primitives designed to retract or relinquish effects. Examples:

- close file descriptor;
- release socket or lease;
- roll back uncommitted transaction;
- revoke temporary credential;
- release an owned lock.

It cannot:

- commit transaction;
- flush pending business records;
- publish message;
- write a normal log through arbitrary application code;
- notify observers;
- call user callbacks.

The runtime should reserve minimal diagnostic/release capacity where practical. Actual catastrophic failure may still prevent release.

#### 7.9.4 Borrowing

A borrowed resource is a temporary permission to operate on the owner's resource.

```text
fn parseFile(file: borrow File) -> ParsedData {
    ...
}
```

The borrow may cross nested helpers and sequential awaits inside the same task. It cannot be retained after the call chain or transferred to another task.

The checker tracks lexical escape rather than general affine move history. Draft mode may perform runtime escape checks where static proof is incomplete.

#### 7.9.5 Expression-valued scopes

```text
let report = use file = try openFile(path) {
    analyse(file)
}
```

The saved body result is returned only after release succeeds. If normal release fails after a successful body, the release exception is outward. If both body and release throw, they aggregate.

The formatter should use line breaks and indentation that make the lifetime boundary obvious to reviewers.

#### 7.9.6 `defer`

`defer` handles cleanup that is not ownership release:

- restoring temporary local state;
- recording ordinary completion/failure telemetry;
- unregistering a non-resource observer;
- performing simple notification on non-abandoning exits.

It runs on return, recoverable exception, and cooperative cancellation. It does not run during abandonment.

The specification must define ordering, likely last-in-first-out within a scope, and asynchronous `defer` behaviour in async functions. Awaiting deferred cleanup occurs under cancellation masking.

#### 7.9.7 Resource-scope diagnostics

The toolchain may combine liveness, use-definition analysis, effect information, and bounded slicing to warn when a resource remains open across:

- unrelated statements;
- long computation;
- avoidable awaits;
- closure creation;
- unknown calls;
- or substantial time after last use.

It may suggest a narrower scope but does not automatically rewrite architecture. Analysis is best-effort and more precise in verified code.

#### 7.9.8 Cleanup aggregation

`AggregateException` entries preserve original and cleanup source spans, order, resource identity, and pending cancellation state. Cleanup aggregation is a general mechanism, not a special task-only exception.

---

### 7.10 Structured concurrency

#### 7.10.1 Why structured task lifetimes

Unstructured spawning breaks function abstraction: a function may return while work it created still reads state, fails later, or keeps resources alive. Structured task groups make child lifetime a property of visible lexical structure.

The task-group substrate is responsible for:

- child registration;
- cancellation propagation;
- quiescence;
- failure collection;
- task-tree diagnostics;
- and enforcing sendability at creation/result boundaries.

Channels provide communication, not lifetime ownership. This separation is deliberate: structured scopes answer *how long does the task live?*; channels answer *how do tasks exchange values?*

#### 7.10.2 Async/await and explicit suspension

Only `async fn` may suspend. `await` is visible. Ordinary cancellation is delivered at:

- `await`;
- explicit cancellation checks;
- documented cancellable standard-library operations such as blocking channel send/receive/select.

CPU-bound loops use an explicit check between chunks. Verified analysis reports regions where no reachable cancellation point is identifiable; it does not prove termination.

#### 7.10.3 General task-group outcome rules

Across all modes:

1. Child task identity and lexical nesting are stable.
2. Before a structured operation returns or throws, all children quiesce unless hard/catastrophic termination occurs.
3. A child abandonment is never converted into an ordinary catchable exception.
4. Recoverable exceptions and cancellations observed before quiescence remain in the report even when abandonment has higher outward precedence.
5. Group-induced cancellation is an outcome but not an independent failure.
6. Diagnostic ordering uses stable task paths rather than wall-clock error-arrival order.

#### 7.10.4 Fail-fast

The first observed child failure requests sibling cancellation. The group waits for all children to finish permitted cleanup.

- All succeed: return normally.
- One or more recoverable exceptions and no abandonment: throw `AggregateException`, even for one child.
- Any abandonment: parent abandons with `TaskGroupFailure` diagnostic.
- External cancellation only: propagate cancellation after quiescence.
- External cancellation plus failure: preserve both; process the group failure and retain pending cancellation for redelivery.

No millisecond “simultaneous” window exists. Every failure occurring before quiescence is retained. Which failures happen before cancellation reaches siblings may depend on scheduling; user logic must not rely on first-failure identity.

#### 7.10.5 Collect-all

Collect-all is explicit supervision:

```text
let report = parallel.outcomes(tasks)
```

It allows every child to finish and returns a `TaskGroupReport[T,E]` containing:

- successful values;
- recoverable exceptions;
- abandonment reports;
- cancellations;
- nested reports.

A child abandonment remains terminal for the child. The parent may log, retry a separate isolated unit, or decide to abandon a larger operation. It cannot resume the failed child.

Parent external cancellation still cancels children and propagates unless a future explicit shielding construct is designed.

#### 7.10.6 Race

Race selects the first terminal child outcome, then cancels unfinished children and waits for quiescence.

- Winning success returns its value unless any child abandons during quiescence.
- Winning recoverable failure produces `AggregateException`, including other recoverable failures before quiescence.
- Winning cancellation propagates cancellation.
- Any abandonment causes parent abandonment and retains all observed outcomes.

Race is the task-lifetime construct for “winner cancels losers.” Ordinary `select` is not.

#### 7.10.7 First-success

First-success tolerates recoverable failures until one child succeeds.

- First success becomes candidate result, unfinished children are cancelled, group quiesces.
- Any abandonment causes parent abandonment, retaining earlier recoverable failures.
- If all children fail recoverably, throw `AggregateException`.
- External cancellation remains pending and is preserved.

This mode is appropriate for redundant providers where a recoverable failure from one source is expected but abandonment indicates a programming or runtime integrity failure.

#### 7.10.8 TaskGroupReport and TaskGroupFailure

The general data structure carries successful values:

```text
record TaskGroupReport[T, E] {
    root: TaskGroupNode[T, E]
}

enum TaskOutcome[T, E] {
    Succeeded(taskPath: TaskPath, value: T)
    ThrewException(taskPath: TaskPath, exception: E)
    Abandoned(taskPath: TaskPath, report: AbandonmentReport)
    Cancelled(taskPath: TaskPath, reason: CancellationReason)
    NestedGroup(taskPath: TaskPath, report: TaskGroupReport[T, E])
}
```

This syntax is illustrative.

`TaskGroupFailure` is a diagnostic projection when abandonment is outward. It can include successful sibling summaries where diagnostically useful but is not the ordinary collect-all return type.

#### 7.10.9 Stable task handles and observation

Spawn returns a stable handle. Awaiting it inside its group exposes the concrete error:

```text
let value = try await task
```

A caught error is observed:

```text
try await task
catch FileNotFound {
    ...
}
```

Explicit conversion to Result is also observation. An observed error does not reappear at group exit unless rethrown.

Plain awaiting for a value is not handling. If it throws, no assignment occurs; the exception unwinds the group body and appears once in the boundary aggregate after quiescence.

Unawaited child failure also appears at the boundary. Abandonment always propagates according to group rules.

#### 7.10.10 Task-boundary copying

Task arguments are evaluated before child start. The runtime then:

- shares frozen values;
- graph-copies mutable values;
- rejects resources/borrows/unsafe handles;
- validates dynamic graphs.

Graph copying preserves internal cycles and aliases. No user-defined copy hooks run in version 1 because they could create side effects or inconsistent isolation. Large-copy advisories should include estimated size, root argument/capture, and suggested alternatives such as freezing or passing a smaller projection.

#### 7.10.11 Cancellation and cleanup

Cancellation cannot be caught by ordinary exception handling or silently suppressed. A mask may delay delivery while cleanup or invariant restoration completes.

If cleanup itself waits indefinitely, the runtime reports a stuck-cleanup diagnostic. There is no universal language-level timeout because safe cleanup duration is domain-specific. The user or host may escalate to hard termination.

A second explicit interrupt or hard-termination command may terminate an independently isolated worker. An arbitrary in-process task cannot always be killed without corrupting interpreter invariants; escalation may terminate the process.

---

### 7.11 Channels

#### 7.11.1 Role of channels

Channels are the primary mechanism for ongoing typed communication after task creation. They are not the task-lifetime model and are not the only boundary-crossing mechanism: task arguments and results also cross boundaries.

The adopted ordinary channel is a multiple-producer, multiple-consumer competing-consumer queue. Every message is delivered once to one receiver.

This is distinct from broadcast, where every subscriber receives a copy. Keeping them separate prevents ambiguous delivery expectations.

#### 7.11.2 Endpoint capabilities

A channel conceptually exposes:

```text
ChannelController[T]
SendPort[T]
ReceivePort[T]
```

Names are illustrative.

The controller establishes and closes the lifetime. Send and receive ports are frozen runtime capabilities. Passing them to several tasks conceptually duplicates capability; no explicit `.clone()` is required.

This resolves the previous contradiction where channels were both the communication mechanism and rejected at task boundaries. Ports are sendable; the internal runtime object is not exposed.

Receive-port multiplicity implements competing consumers. The specification may add specialised single-consumer channels later, but the general ordinary form remains MPMC.

#### 7.11.3 Capacity forms

A channel supports:

```text
channel[T].rendezvous()
channel[T].buffered(capacity)
channel[T].unbounded()
```

Capacity is the number of messages that may wait simultaneously, not the number transmitted over the lifetime.

**Rendezvous** is default. A send commits only when matched with a receiver. It requires no capacity guess, makes synchronisation explicit, and provides strongest backpressure.

**Buffered** permits temporary producer lead. Capacity may be computed from topology/configuration. Correctness should not normally depend on one exact capacity; diagnostics warn where changing capacity appears to change liveness.

**Unbounded** is easier for some pipelines but risks memory growth and hides backpressure. It is explicit and monitored. Advisories use queue occupancy and production/consumption trends; static proof is not required.

#### 7.11.4 Closure and endpoint loss

Closure is terminal. Reopening would make stream lifetime and message fate difficult to reason about and could turn closure state into an accidental communication channel.

Distinguish:

- one port holder disappearing;
- all senders disappearing;
- all receivers disappearing;
- controller/global closure.

A send fails if globally closed or no receiver remains. A receive drains committed buffered messages, then reports closure when no future send is possible.

A receiver that temporarily does not want input simply stops receiving. On bounded/rendezvous channels this creates backpressure.

#### 7.11.5 Closed-channel outcomes and diagnostics

For MPMC communication, “the other party” may be a set rather than one endpoint. Diagnostics include:

```text
ChannelClosed {
    channelId
    operation
    localPortId
    channelCreatedAt
    reason: NoReceivers | NoSenders | ControllerClosed
    messageType
    attemptedAt
}
```

Request-response messages can include target service and request IDs for more precise reports.

A bounded runtime event ring may record attempted communication after closure. Program code cannot inspect it.

#### 7.11.6 Blocking, nonblocking, and cancellation

A blocking send or receive is cancellable only when it waits. An unbounded send that commits immediately does not suspend.

Nonblocking operations return explicit outcomes such as `WouldBlock` or `ChannelClosed`.

Commit semantics are atomic:

- before send commit: cancellation sends nothing;
- after send commit: message exists and cancellation arrives afterward;
- before receive commit: no message consumed;
- after receive commit: value delivered, then cancellation.

This prevents “maybe delivered” ambiguity inside the language runtime. External network protocols may still require their own idempotency rules.

#### 7.11.7 Ordering and fairness

Same-task sends commit in program order. Across concurrent tasks, source code defines no relative order. The channel records one global commit sequence.

Receivers observe commit order, but multiple receivers compete: which receiver obtains message N is scheduler/channel-fairness dependent.

Endpoint waiter queues are FIFO provisionally. A cancelled waiter loses its position; re-registration joins the back. This prevents a rapidly polling task from repeatedly overtaking existing waiters.

#### 7.11.8 Message copying

Frozen messages share. Mutable messages copy once into channel-owned storage.

For bounded/rendezvous send:

1. validate sendability and estimate cost;
2. reserve buffer capacity or receiver match;
3. copy privately;
4. atomically commit;
5. redeliver pending cancellation afterward.

A cancelled pre-commit copy is discarded. Copy hooks are not user-extensible in version 1.

Broadcast is frozen-only in version 1 because a mutable broadcast would require independent copies per subscriber and more complex failure semantics.

#### 7.11.9 Higher-level communication patterns

The standard library may build:

- fan-in/fan-out;
- request-response with reply ports and correlation IDs;
- broadcast notifications;
- latest-value/watch channels;
- worker pools;
- receive-until-all-closed loops.

These remain separate abstractions when delivery semantics differ. The core channel should not accumulate modes that make one operation's delivery meaning unclear.

---

### 7.12 Channel selection

#### 7.12.1 Problem

A task sometimes needs to wait until one of several operations can commit:

- receive on one of several ports;
- send when one destination becomes available;
- react to one task completion;
- reach a deadline.

Naive sequential awaits impose accidental priority. Polling is non-atomic and timing-sensitive. Selecting arbitrary async expressions creates cancellation-safety and side-effect problems.

#### 7.12.2 Closed selectable family

Version 1 permits only operations the runtime can register and cancel without visible losing effects:

- channel receive;
- channel send;
- task completion observation;
- deadline;
- closure as receive outcome.

An arbitrary async API participates by running in a child task and exposing its handle. This composes with async/await while keeping selectable operation semantics narrow.

#### 7.12.3 Branch-oriented syntax

Illustrative form:

```text
let outcome = select {
    receive request from requests => {
        handleRequest(request)
    }

    send response to replies => {
        Sent
    }

    task worker completed as result => {
        handleTask(result)
    }

    at deadline => {
        TimedOut
    }
}
```

Operation and handler are adjacent. Heterogeneous result types remain branch-local. Boilerplate is accepted for reviewability.

Branch operands are endpoint/handle/deadline references and precomputed values. Go-style evaluation of effectful send expressions for losing branches is explicitly rejected.

#### 7.12.4 Atomic registration and commitment

The runtime registers all enabled alternatives, arbitrates, atomically commits one, and unregisters losers.

A losing receive consumes nothing. A losing send sends nothing. A losing task-completion observation does not cancel or alter the task. A deadline that loses has no effect.

No user-visible readiness token exists. Readiness-only two-phase selection was rejected because it creates time-of-check/time-of-use races and extra state.

#### 7.12.5 Deterministic rotating fairness

Permanent source-order priority is reproducible but can silently starve later branches. Fresh random selection reduces starvation but harms reproducibility and makes unrelated rewrites difficult to compare.

The default compromise is a per-site fairness cursor:

1. first invocation scans source order;
2. later invocation starts after previous winner;
3. wraps around;
4. chooses first ready enabled branch;
5. updates cursor.

The cursor belongs to one lexical site in one task/function activation. Recursive or concurrent activations are independent.

For N static enabled branches, a continuously ready branch is chosen within N successful selections. This guarantee applies to branch arbitration, not to external operations that cease being ready.

The cursor is historical state, but it is small, bounded, and exposed in diagnostics.

#### 7.12.6 Explicit priority

Some protocols intentionally prioritise shutdown/control work. An explicit priority form scans source order every time.

It must be visually distinct and searchable. Verified diagnostics warn about likely starvation in loops. Numeric priorities are deferred because they would create a more complex hidden scheduling policy.

#### 7.12.7 Randomised testing

Normal runs use deterministic rotation. Test/stress mode may randomise task scheduling, select ties, and competing receiver choice using a recorded seed.

```text
lang test --schedule=random --seed=8734291
```

The goal is to explore legal interleavings, not to define ordinary semantics. Replay remains best-effort when external timing changes.

#### 7.12.8 Nonblocking selection

Blocking select has no `default` branch. A default makes busy loops and timing-dependent polling too easy.

A distinct form atomically checks without waiting:

```text
select now {
    receive value from first => ...
    receive value from second => ...
    none ready => ...
}
```

Verified mode warns when this repeats without any suspension/cancellation point.

#### 7.12.9 Deadlines

Absolute deadline is semantic primitive:

```text
let deadline = time.now() + 5.seconds

select {
    receive reply from replies => ...
    at deadline => ...
}
```

Relative `after` syntax may be sugar that computes one deadline on entry. In a surrounding loop, each re-entry computes a new deadline; the checker warns where this may postpone timeout indefinitely.

A lexical `within deadline` operation may apply to one coherent structured operation. It should not become a catch-all wrapper for unrelated work.

#### 7.12.10 Conditional alternatives

Arbitrary guards could mutate state, be reevaluated at unclear times, or create reactive hidden dependencies.

Version 1 uses a precomputed frozen local Boolean read once on entry:

```text
let canSend = pending is Some

select {
    when canSend:
        send pending.value to output => ...

    receive value from input => ...
}
```

Disabled branches are not registered. The event diagnostic records guard state.

#### 7.12.11 Closed channels

Closure is an explicit receive outcome. Ordinary selection does not silently remove a closed branch. Silent removal would mutate the active branch set invisibly and make one-shot and looped selection differ.

The checker warns when a closed branch in a loop does not exit, remove the endpoint, return, or otherwise stop repeated immediate selection.

A standard fan-in helper may explicitly maintain an active receiver set and remove closed ports.

#### 7.12.12 Task completion selection

Selecting one completed task does not cancel other tasks. It only determines which event the current task handles.

Use structured race when winner selection should cancel losers. This preserves one mechanism per concern: select for event response; race for task lifetime competition.

#### 7.12.13 Dynamic alternatives

Fully dynamic heterogeneous selection weakens typing and separates operation from handler. Static branches remain primary.

Dynamic homogeneous helpers cover important generic cases:

```text
selectReceive(receivers: List[ReceivePort[T]])
selectTask(tasks: List[Task[T,E]])
```

Outcomes identify the selected endpoint/handle and carry typed value/error/closure data. Dynamic heterogeneous lists are deferred.

#### 7.12.14 Selection diagnostics

Each task maintains a bounded ring buffer of recent selection events:

- source site;
- invocation number;
- enabled/disabled branches;
- ready branches;
- previous winner/cursor;
- selected branch;
- task/channel IDs;
- channel sequence values;
- deadline state;
- random seed in stress mode.

The ring obeys the global diagnostic memory budget and is unavailable to program code.

---

### 7.13 Diagnostics

#### 7.13.1 Philosophy

Diagnostics are part of the language interface. They are designed for both human review and machine consumption. The runtime should preserve enough structured context to identify the violated assumption, causal path, task/resource/channel ownership, and safe representations of relevant values.

Diagnostic richness remains bounded by time, memory, privacy, and output budgets. Truncation must be explicit rather than silently discarding context.

#### 7.13.2 Hierarchical classification

The previous overlapping `E/W/A/C/T` prefixes are replaced by one broad outcome plus a domain and leaf reason.

Examples:

```text
A.CONTRACT.PRECONDITION_FAILED
A.TYPE.DYNAMIC_MISMATCH
S.TYPE.STATIC_MISMATCH
R.IO.FILE_NOT_FOUND
R.CHANNEL.NO_RECEIVERS
W.RESOURCE.SCOPE_TOO_WIDE
```

Suggested broad classes:

- `A`: abandonment;
- `R`: recoverable runtime failure;
- `S`: static/checking error;
- `W`: warning/advisory.

Machine-readable diagnostics expose fields separately:

```text
outcome: abandonment
domain: type
reason: dynamic_mismatch
stable_code: A.TYPE.DYNAMIC_MISMATCH
```

Tools never need to parse the display code. Exact punctuation is specification/tooling-stage.

#### 7.13.3 Diagnostic anatomy

A diagnostic object may include:

- stable code and severity/outcome;
- primary source span;
- related spans;
- typed expectation and actual runtime shape;
- task path and parent group;
- resource scope/acquisition/release site;
- channel and endpoint IDs;
- message sequence and selection event;
- causal chain;
- bounded local-value representations;
- notes and suggested visible edits;
- truncation/redaction metadata.

The pretty-printer remains separate from producers. JSON preserves the structure.

#### 7.13.4 Bounded local values and privacy

Safe representation:

- never invokes user code;
- detects cycles;
- limits depth, item count, string length, per-value size and total size;
- summarises large tables/arrays with shape, schema, head/tail or statistical summaries;
- redacts fields marked sensitive and heuristically recognised credentials;
- reports that redaction/truncation occurred.

A program need not be security-critical to contain passwords, tokens, private data, or proprietary datasets that a user may paste into a cloud LLM.

#### 7.13.5 Provisional performance budgets

These are engineering targets based on judgment and comparison with lightweight tracing, sanitisation and race-detection tools. They are not normative language promises.

**Default substrate**: source spans, lightweight propagation, task lineage, bounded context. Target no more than about 25% geometric-mean slowdown on representative workloads; an ordinary workload exceeding 2× requires explicit justification.

**Verified execution**: target around 2× baseline where additional runtime checking is required.

**Deep diagnostics**: provisional maximum acceptable ceiling:

```text
Tdeep <= Tbaseline + min(9 * Tbaseline, 2 hours)
```

This gives multiplicative tolerance for short runs and an additive ceiling for long runs. It is a ceiling, not a target.

**Failure rendering**: target under five seconds for ordinary failures; default hard rendering budget about thirty seconds, after which a safely truncated report is emitted. Extended reporting is explicit.

All figures should be measured against representative data-science, service, interpreter, automation and simulation workloads and revised as evidence accumulates.

#### 7.13.6 Concurrent, resource, and selection traces

Task failures are displayed as a lexical tree (“stack cactus”) and include task paths. Resource diagnostics show acquisition and owning scope. Channel diagnostics show endpoint identities and sequence. Selection diagnostics show ready branches and fairness state.

The canonical machine form remains nested. Human views may flatten leaf failures or summarise repetitive cancellations.

#### 7.13.7 Multi-error recovery

The parser/checker should continue after recoverable static errors, mark likely root causes, and identify likely cascade diagnostics. LLM correction benefits from seeing several independent errors at once, but cascades must not overwhelm the root.

Fix suggestions are visible patches, never hidden semantic changes.

---

### 7.14 Toolchain

#### 7.14.1 Provider-neutral interface

The language works through ordinary files, CLI commands, JSON diagnostics, deterministic formatting, and optionally LSP/IDE integration. No feature requires access to a provider's hidden reasoning trace or proprietary memory.

#### 7.14.2 Commands and modes

Working command family:

```text
lang run
lang check
lang format
lang repl
lang test
```

Working options include draft/verified, quiet/deep/JSON, and seeded scheduling stress. Exact names are specification/tooling-stage choices.

The project manifest records the default acceptance mode and pinned dependencies.

#### 7.14.3 Formatter and source edits

The formatter is idempotent and authoritative. Import insertion and formatter output are normal source edits suitable for diff review. The toolchain should be able to return patches rather than silently mutate files where the host workflow prefers review-first operation.

#### 7.14.4 REPL and runtime loading

The REPL is first-class because exploratory data work and agent correction loops benefit from immediate execution. Runtime module loading is supported while preserving module identity and diagnostics. Reload semantics must be explicit to avoid retaining incompatible mutable definitions invisibly.

#### 7.14.5 Schedule stress testing

Normal execution uses deterministic policies where specified. Test mode may deliberately perturb scheduling:

```text
lang test --schedule=random --seed=8734291
```

Failure reports record the seed and recent scheduling/selection decisions. This detects accidental ordering assumptions while preserving reproducibility of the attempted schedule as far as external timing permits.

---

### 7.15 Core and standard-library boundary

The core contains mechanisms that define language semantics or require privileged runtime cooperation:

- primitive operations;
- frozen/mutable collection identity and snapshot machinery;
- Option/Result and error effects;
- transient type checks and protocol metadata;
- contracts, predicates, invariants and old snapshots;
- resource scopes, borrows and registered release;
- defer and exit unwinding;
- structured task groups, handles, reports, cancellation;
- channels, endpoints, capacity, closure, copying, selection and fairness;
- hierarchical diagnostic objects, source maps and bounded capture;
- canonical import/name index.

The standard library builds domain APIs and higher-level patterns:

- file/network/process/database resource providers;
- JSON, HTTP, regex, math, datetime, data frames and statistics as scope permits;
- standard concrete errors and categories;
- ordinary structural protocols;
- worker pools, broadcast, fan-in, request-response, receive-until-closed and homogeneous selection helpers.

The boundary should remain small enough to implement coherently but not force semantic-critical behaviour into ordinary library code that cannot enforce it.

---

### 7.16 LLM-native design and evidence

#### 7.16.1 Operational model of coding agents

Agents can search, navigate, edit and execute. Those capabilities do not eliminate locality costs: every operation consumes context, tokens, latency and creates another point where the agent can retrieve the wrong definition, patch the wrong location or lose rationale after compaction.

The language therefore favours:

- explicit local dependencies;
- stable canonical formatting;
- precise diagnostics;
- small semantic mechanism sets;
- and machine-readable tool output.

It does not assume an LLM literally cannot edit earlier code.

#### 7.16.2 Empirical error model

Evidence suggests LLMs are comparatively good at sequential familiar patterns, boilerplate and targeted fixes from precise errors. They remain vulnerable to:

- missing edge cases;
- semantic drift across long spans;
- invented names/dependencies;
- inconsistent assumptions about types;
- incomplete error handling;
- resource-lifetime mistakes;
- and structural changes requiring coordinated edits.

Language features can eliminate or diagnose some of these classes but cannot replace model capability or testing.

LlmFix found three categories directly repairable by simple rule-based post-processing in its benchmark setting. Other classes generally required contextual or semantic reasoning; this does not imply language design cannot reduce their incidence or improve diagnosis.

#### 7.16.3 Evidence calibration

For major empirical claims, the document records:

- precise claim;
- claim confidence;
- evidential basis;
- main uncertainty;
- decision confidence;
- and why the decision remains attractive if the estimated effect is smaller.

A production-language design essay, a controlled benchmark, a single informal experiment and a mature-language precedent provide different kinds of evidence. Confidence is not assigned mechanically by source category.

The Vera experiment is evidence that a frontier model can learn a novel language from a reference and that language structure may matter. It is a proof of concept, not broad validation. Its existence also requires narrowing the novelty claim: no mature widely adopted general-purpose language pursues this complete combination, rather than no language having ever targeted LLM generation.

#### 7.16.4 Python differential behavioural oracle

Python supports bootstrapping because frontier agents generate it well and because semantically matched reference implementations can serve as output oracles.

For a task such as “read a binary tree from this CSV format, invert it and emit this representation,” define:

1. valid shared input domain;
2. observable return/output/file effects;
3. canonicalisation rules;
4. intentional language differences;
5. time/resource limits.

Then require the target program to complete and match canonical observations for every finite conformance input on which the Python reference completes within the declared shared domain.

For fuzzing, any tolerance is declared in advance. A target failure where Python succeeds is ordinarily a translation/implementation failure, not ignored because comparison occurs only on jointly successful cases.

Python is not authority for target-specific truthiness, concurrency, resource, error, module or numeric semantics. Direct specification conformance tests decide those.

#### 7.16.5 Example-library bootstrapping

The example library should be generated and validated progressively:

1. choose a task and shared-domain contract;
2. implement or obtain a Python reference;
3. generate target-language implementation from the reference/specification;
4. run finite and generated tests;
5. compare canonical observations;
6. retain only verified examples with metadata about features used and specification version.

Examples should cover failure paths and interactions, not only happy-path algorithms.

---

## Part VIII — Feature Interactions

This part records consequences that arise only when two or more features are combined. Each subsection states the interaction, the adopted rule, and examples or risks the specification must cover.

---

### 8.1 Dynamic typing × protocols × contracts

A dynamic value entering a protocol-annotated function is shape-checked immediately. The protocol's inherited runtime contracts then apply to every invocation.

This prevents two delayed failures:

- discovering a missing protocol method only after earlier code ran under a false assumption;
- accepting a method with an incompatible recoverable error effect.

Nested returned values are transiently checked when consumed. Protocol postconditions test behaviour at runtime rather than requiring theorem proving.

Required examples:

- dynamic value missing one required method;
- method with extra throwing effect;
- method shape valid but postcondition fails;
- frozen verified implementation avoiding repeated shape checks.

### 8.2 Dynamic typing × tasks and channels

Task isolation is not optional in draft mode. A dynamic value must be inspected before task start or message commit.

The operation has only three outcomes:

- transitively frozen: share;
- mutable but copyable: graph-copy;
- non-sendable capability/resource/closure: reject.

No child may start and then discover that its argument graph was unsafe to isolate. No channel may report success before copying commits.

Required examples:

- cyclic mutable graph;
- graph containing a resource two levels deep;
- dynamic closure with mutable capture;
- copy cancelled before message commit.

### 8.3 Error effects × higher-order functions

Minimal error-effect forwarding makes ordinary collection and callback APIs usable without erasing failure visibility.

The specification must define:

- inference of an effect variable from a callback;
- union normalisation and ordering for diagnostics;
- explicit annotations where inference is ambiguous;
- effect compatibility in protocol method shape checks;
- and how a dynamic callback is narrowed.

A function returning Result may accept a throwing callback only if it explicitly captures the callback exception internally and itself does not declare throws.

### 8.4 Exceptions × Results × channels

A Result sent through a channel is ordinary failure data. A channel send itself may fail recoverably because the channel is closed. These are separate layers:

```text
try sender.send(Result[Value, ValidationError])
```

The message's `Err` is not thrown. The send's `ChannelClosed` may be.

The specification and diagnostics must keep:

- message payload error provenance;
- channel operation failure;
- and task-group failure

distinct rather than flattening them into one “error.”

### 8.5 Resources × async suspension

A resource borrow may cross await in the same task while the owning scope remains active. This is legal but may hold an external resource longer than necessary.

The checker/runtime should:

- reject sending or spawning with the borrow;
- preserve resource ownership across suspension;
- warn on wide scopes or long waits;
- and ensure cancellation invokes normal release under masking.

An async helper that stores the borrow for later is invalid even if called from the same task.

### 8.6 Resources × abandonment

When body state is declared invalid, arbitrary provider continuation and defer callbacks do not run. Registered release may only retract/relinquish effects.

A transaction example must distinguish:

- normal return: commit may be part of explicit body or normal release if contractually defined;
- recoverable exception/cancellation: normal rollback/close;
- abandonment: abandonment-safe rollback/revoke only;
- hard termination: no guarantee.

A release failure during abandonment remains secondary.

### 8.7 Resources × expression-valued blocks × contracts

For:

```text
let report = use file = try openFile(path) {
    analyse(file)
}
```

ordering is:

1. evaluate body value;
2. save value;
3. release file;
4. evaluate enclosing function postconditions/invariants when that function exits;
5. bind/use result.

A postcondition may use a frozen value captured before release but cannot operate on the released resource or perform I/O.

### 8.8 Mutable records × invariants × cancellation

A public mutable operation may temporarily violate an invariant internally, but every cancellation point is a potential exit.

Therefore code such as:

```text
self.balance -= amount
await remoteConfirmation()
self.pending = false
```

is invalid or diagnostically dangerous if the record invariant is broken between mutation and await.

The implementation should encourage:

- compute before mutation;
- mutate after await;
- restore invariant before suspension;
- or keep intermediate state in local non-public values.

If cancellation finds invalid state after cleanup, abandonment supersedes cancellation.

### 8.9 Protocol contracts × mutable implementations

A mutable implementation may satisfy a frozen-looking protocol only if its observable method contracts hold and task-boundary rules prevent unsafe sharing.

Structural protocol conformance does not imply sendability. Sendability is a separate property of the concrete value.

A protocol method's inherited precondition applies to all implementations. Implementations cannot add public preconditions, but may use private helper assertions whose violation indicates an implementation bug.

### 8.10 Task handles × group aggregation

Awaiting a handle gives local access to a concrete exception. The structured boundary aggregates only unhandled child failures.

Required specification cases:

- awaited and caught child exception;
- awaited and explicitly captured Result;
- awaited but uncaught exception;
- unawaited failed task;
- two tasks fail while one is handled;
- child abandonment after an earlier exception was handled.

No failure is displayed twice merely because it passed through an await and group boundary.

### 8.11 External cancellation × group failure

External cancellation and child failure are independent events.

If both occur:

- group quiescence and failure reporting still complete;
- external cancellation remains pending;
- cancellation is redelivered at the next point after failure handling/reporting;
- diagnostics state that both were present.

A catch of recoverable group failure cannot silently clear external cancellation.

### 8.12 Channels × graph copying × backpressure

Mutable message copy occurs only after capacity or receiver reservation. Otherwise a sender could repeatedly copy a large graph while a bounded channel remains full.

Copy size can itself be expensive. Diagnostics should identify:

- root message expression;
- estimated graph size;
- repeated sends of similar mutable graphs;
- opportunity to freeze or send a smaller projection.

A copy failure before commit sends nothing. A failure after commit is not allowed by the core copying mechanism; commit occurs only after a complete private copy exists.

### 8.13 Channel closure × selection loops

A closed receive is immediately selectable. In a loop it can win repeatedly.

The language does not silently remove it because hidden mutation of alternatives harms reviewability. Instead:

- closure is an explicit outcome;
- the checker warns when handling does not alter eligibility or exit;
- higher-level receive-until-closed helpers remove ports explicitly.

### 8.14 Selection × fairness × diagnostics

Deterministic rotation avoids permanent source priority but introduces one historical cursor.

The diagnostic ring must record enough state to explain a choice, while remaining bounded. A tight loop overwrites old events rather than growing memory indefinitely.

The fairness guarantee applies only to branches continuously ready at each arbitration. It does not promise fairness for a branch whose external condition flickers or whose endpoint waiter loses readiness.

Priority selection is explicitly different and subject to starvation warnings.

### 8.15 Selection × task lifetimes

Selecting task completion does not cancel other tasks. If the selected branch returns from the task-group body, ordinary structured-scope exit then applies the group's mode and may cancel/quiesce children according to that scope.

To avoid confusion, examples should distinguish:

```text
select { task ... }       // choose event to respond to
parallel.race(tasks)      // first terminal result cancels losers
parallel.firstSuccess(...)// first success cancels losers
```

### 8.16 Relative timeout × loops

`after duration` computes an absolute deadline each time the select is entered. In a loop, unrelated ready events may repeatedly reset it.

Verified diagnostics should flag likely accidental reset and suggest:

```text
let deadline = time.now() + duration
while condition {
    select { ... at deadline ... }
}
```

This makes the end-to-end time budget explicit.

### 8.17 Select guards × mutable state

A guard is a precomputed frozen Boolean, not a live expression. It represents the branch set at select entry.

If state changes while waiting, the guard does not update. The surrounding code must re-enter select. This prevents hidden reactive dependencies but means state-machine code should structure one iteration around one snapshot.

### 8.18 Modules × mutable state × tasks

Because ordinary mutable module globals are prohibited, task isolation cannot be bypassed through global lookup. Root-owned services may internally run an owning task and expose send ports to clients.

A future module-state feature would need the same ownership and explicit dependency rules; it cannot become shared-memory global state.

### 8.19 Auto-import × reproducibility

Automatic import insertion is limited to already known dependencies. It cannot silently add a package whose current registry resolution might change over time.

The source edit, manifest and lockfile form the reproducible state. Diagnostics distinguish:

- known missing import with automatic patch;
- ambiguous known import requiring choice;
- unknown name with optional package suggestions;
- and explicit dependency addition.

### 8.20 Diagnostics × privacy × LLM workflows

Diagnostics may be pasted into cloud LLMs. Bounded local capture therefore includes redaction even for low-stakes programs.

The renderer should avoid showing full secrets by default, but retain enough structural data to diagnose failures. Deep mode does not disable secret protection unless the user takes an explicit high-friction action.

### 8.21 Python differential testing × intended semantic differences

The common-domain declaration prevents Python implementation details from becoming hidden semantics.

Examples should explicitly exclude or adapt:

- truthiness;
- integer overflow;
- exception hierarchy;
- resource release timing;
- concurrency scheduling;
- module loading;
- nullability.

A target program failing on an input where the matched Python reference succeeds is a mismatch unless the input was declared outside the common domain beforehand.

---

## Part IX — Decision Record

### 9.1 Accepted semantic decisions

| Area | Decision | Status |
|---|---|---|
| Object model | Frozen records + explicit mutable records + closed variants + structural protocols; no class inheritance | Decided |
| Frozen values | Transitively frozen; structural equality; no observable identity | Decided |
| Mutable values | Identity-bearing within one owner task | Decided |
| Collections | Frozen functional update semantics and distinct mutable forms | Decided |
| Bindings | Reassignable by default; separate from object mutation | Decided semantics |
| Module state | Frozen constants allowed; ordinary mutable globals prohibited in v1 | Decided |
| Gradual typing | Transient runtime checks | Decided |
| Annotation semantics | Written annotations enforced in draft and verified execution | Decided |
| Coercion | No automatic cross-type coercion | Decided |
| Concrete vs structural | Concrete record annotation is nominal; protocol annotation is structural | Decided |
| Dynamic mismatch | Abandonment with boundary-oriented diagnostics | Decided |
| Nullability | `T? == Option[T]`, `null == None`, uninitialised separate | Decided |
| Failure model | Recoverable exceptions, cancellation, abandonment, hard termination distinct | Decided |
| Exception/Result split | Cannot both throw and return Result; conversions explicit | Decided |
| Default handling | No broad untyped fallback; one-known-concrete-error exception | Decided |
| Effect polymorphism | Minimal error-set variables/unions/forwarding in v1 | Decided |
| Errors | Concrete nominal types; zero-or-one catch category in v1 | Decided |
| Contracts | Executable runtime predicates, not general theorem proving | Decided |
| Contract language | Restricted total subset and non-recursive predicates | Decided |
| Protocol contracts | Inherited; implementations cannot add public preconditions | Decided |
| Invariants | Controlled mutation; checked after cleanup on return/exception/cancellation | Decided direction |
| Memory | Garbage collected | Decided |
| Resources | Scoped provider model, exactly one yield | Decided |
| Resource borrow | Non-escaping, same-task; may cross same-task await | Decided |
| Abandonment cleanup | Restricted release/revoke/rollback only | Decided |
| `defer` | Non-resource cleanup; no abandonment execution | Decided |
| Cleanup failure | General AggregateException/precedence table | Decided |
| Task lifetime | Structured task groups | Decided |
| Task modes | Fail-fast, collect-all, race, first-success | Decided |
| Task report | Result-bearing `TaskGroupReport`; diagnostic `TaskGroupFailure` | Decided |
| Direct await | Concrete child exception; handled errors marked observed | Decided |
| Fail-fast aggregate | AggregateException even for one child recoverable failure | Decided |
| Child abandonment | Dominates fail-fast/race/first-success after quiescence | Decided |
| Cancellation | Cooperative, visible, non-catchable/non-discardable | Decided |
| Channels | MPMC competing-consumer ordinary channel | Decided |
| Broadcast | Separate abstraction, frozen-only in v1 | Decided direction |
| Channel capabilities | Controller + send/receive ports | Decided semantics |
| Channel capacity | Explicit rendezvous/default, buffered, unbounded | Decided |
| Channel closure | Permanent and monotonic | Decided |
| Channel ordering | Same-task order; global commit sequence; cross-task order unspecified | Decided |
| Message isolation | Frozen share; mutable graph-copy once before commit | Decided |
| Select participants | Send, receive, task completion, deadline, closure outcome | Decided |
| Select safety | Atomic one-winner commit; losers have no effect | Decided |
| Select default fairness | Deterministic rotating cursor | Decided direction |
| Select priority | Explicit source-order form | Decided |
| Select nonblocking | Separate `select now`; no blocking default branch | Decided |
| Select guards | Precomputed frozen booleans | Decided |
| Dynamic selection | Homogeneous helpers only in v1 | Decided direction |
| Source | One canonical persisted representation | Decided |
| Imports | Visible insertion from known pinned dependencies only | Decided |
| Diagnostics | Hierarchical codes and structured JSON fields | Decided direction |
| Diagnostic capture | Bounded, cycle-safe, side-effect-free, secret-aware | Decided |
| Python validation | Differential behavioural oracle on declared common domain | Decided |
| Release acceptance | Verified build required | Decided |

### 9.2 Provisional engineering decisions

| Topic | Current direction | Why provisional |
|---|---|---|
| Select fairness implementation | Per-site deterministic rotating cursor | Needs implementation/liveness testing, especially nested/dynamic selects |
| Endpoint waiter fairness | FIFO queues | May need refinement for select registration and throughput |
| Rendezvous default | Default ordinary channel construction | Validate LLM ergonomics and deadlock frequency |
| Broadcast frozen-only | No mutable broadcast in v1 | Could be relaxed if copy semantics remain clear |
| Dynamic type integrity metadata | Verified frozen values may skip repeated checks | Runtime representation and invalidation details open |
| Resource-scope width analysis | Liveness/use-def/slicing warnings | Precision and false-positive rate need testing |
| State-horizon diagnostics | Warn on large state bags and long spans | Heuristic; needs corpus validation |
| NaN policy | Preference toward visibility/abandonment or strong diagnostics | Numerical workload compatibility unresolved |
| Diagnostic performance budgets | 25%/~2×/deep ceiling | Judgment-based; must be benchmarked |
| Selection ring-buffer size | Bounded always-on history | Workload-sensitive implementation parameter |
| Optional explicit protocol conformance | Declaration for diagnostics while structural semantics remain | Need syntax/usability evaluation |
| Closure reassignment marker | Explicit marker likely | Compare LLM generation and reviewability |

### 9.3 Specification-stage choices

These are not unresolved semantic architecture. The specification writer must choose, justify and record:

1. Binding and constant keywords.
2. Frozen record update/copy syntax.
3. Frozen and mutable collection names/APIs.
4. Dynamic type spelling.
5. Resource-provider, yield, use-scope and borrow syntax.
6. Exception-to-Result conversion and Err propagation syntax.
7. Error-effect variable and union notation.
8. Error category declaration and catch syntax.
9. Restricted predicate syntax.
10. Invariant-relevant field access-control syntax.
11. Channel controller/port names and construction syntax.
12. Send/receive/nonblocking outcome syntax.
13. Select, priority select, select-now, deadline and guard syntax.
14. Dynamic homogeneous selection helper names.
15. Four task-group operation syntax.
16. Explicit cancellation-check syntax.
17. Directory module mechanism.
18. Type-only/declaration-cycle policy.
19. Export keyword.
20. Closure reassignment/capture syntax.
21. Package manifest and lockfile format.
22. Test framework and schedule-stress flag syntax.
23. Hierarchical diagnostic display punctuation.
24. Result context-attachment syntax.
25. NaN behaviour, after dedicated analysis.

### 9.4 Deferred features

- Restricted resource-owning records/containers.
- Multiple error-category membership.
- General module-state facility with explicit owner/effect declaration.
- General algebraic effects or user-defined handlers.
- Dynamic heterogeneous selection lists.
- Mutable-value broadcast with per-subscriber copying.
- Numeric branch priorities.
- General pure function effect beyond restricted predicates.
- User-defined graph-copy hooks.
- Fixed-width integer family.
- Reflection and metaprogramming.
- Operator overloading beyond a narrow core.
- FFI/Python interoperability design.
- Strong deterministic replay across external I/O.

### 9.5 Rejected alternatives

**Class inheritance**: Cross-cutting field/method dependencies and behavioural hierarchy errors outweigh familiarity. Composition, records and protocols remain.

**Structural resource cleanup / `Closeable` RAII**: Shared references do not identify ownership. Replaced by explicit provider scopes.

**General move/affine semantics in version 1**: Requires tracking historical move state, branch-dependent consumption and closure captures. The resource model obtains the needed ownership property without making all values affine.

**Final-reference cleanup**: Lifetime timing is hidden; cycles and async release are problematic.

**Advisory-only annotations**: Typed code could not rely on signatures.

**Guarded/proxy gradual typing in version 1**: Identity and mutable/higher-order wrapper complexity too high.

**Automatic coercion**: Hides violated assumptions and creates difficult type-dependent semantics.

**Unchecked recoverable exceptions**: Failure surfaces become invisible. Draft mode may omit markers temporarily, but verified source requires them.

**Java-style manually propagated checked exceptions without effect forwarding**: Excessive inside-out boilerplate and easy suppression. Minimal effect polymorphism is adopted instead.

**Go-style error-value handling at every call**: Interrupts happy path. Result remains available for stored failure data; exceptions plus visible propagation serve immediate failure.

**Functions both throwing and returning Result**: Two simultaneous failure channels make call-site reasoning ambiguous.

**Recoverable abandonment / `try_recover`**: Continuing inside a failed task after an invariant/assumption failure is unsafe.

**Broad untyped default/catch**: Silently suppresses errors the author did not anticipate.

**Structural error matching**: Overlapping structural classifications make catch behaviour non-local and hard to evolve.

**Theorem-proving protocol contract compatibility**: Contradicts executable-contract scope and implementation constraints. Contracts are inherited at runtime.

**General purity inference for contracts in version 1**: Too many subtle effects and edge cases. Restricted predicates provide most value.

**Ordinary mutable module globals**: Expand hidden state horizon and bypass task isolation.

**Shared mutable task state with locks**: Requires global race/deadlock reasoning.

**Channels as the task-lifetime model**: Channels are adopted for communication, but do not own child lifetimes or replace structured task groups.

**One universal channel delivery mode**: Competing-consumer, broadcast and latest-value semantics are distinct and should not be conflated.

**Implicit unbounded channel default**: Hides memory growth and lack of backpressure.

**Reopenable channels**: Makes stream lifetime and message fate ambiguous.

**Arbitrary async expressions in select**: Losing operations may have partial effects and require manual cancellation-safety knowledge.

**Readiness-only two-phase select**: Adds reservation tokens, races and extra state.

**Permanent source-order select as default**: Silent starvation and branch-reordering sensitivity.

**Fresh random select as normal default**: Weak reproducibility and difficult intermediate comparison. Randomisation remains a test mode.

**Persistent round-robin scheduler as an opaque global policy**: Excess historical/scheduler state. Fairness is localised to each select site and endpoint queue.

**Blocking select with ordinary default branch**: Encourages busy loops and timing-sensitive polling. Separate `select now` is explicit.

**Reactive arbitrary branch guards**: Evaluation timing and hidden state dependencies are difficult to reason about. Guards are frozen entry snapshots.

**Silent removal of closed branches**: Hidden mutation of alternative set. Higher-level helpers perform explicit removal.

**Fully dynamic heterogeneous selection in v1**: Type erasure and detached dispatch harm locality.

**Dual LLM/human source representations**: Creates an audit gap. One canonical representation remains.

**Silent dependency installation**: Makes builds non-reproducible and turns hallucinations into supply-chain changes.

### 9.6 Experimental validation priorities

1. Compare deterministic rotating selection with source priority and seeded random selection on generated concurrency tasks: starvation, reproducibility, LLM correction turns, reviewer accuracy.
2. Test rendezvous default versus small explicit buffers: deadlock frequency, code complexity, throughput expectations, diagnostic usefulness.
3. Benchmark transient checks on mutable collections and protocol-heavy code.
4. Measure graph-copy frequency/size in representative data and service programs.
5. Evaluate resource-scope-width and mutable-state-horizon diagnostics for false positives.
6. Test restricted contract predicates for expressiveness across data validation, algorithms, services and interpreters.
7. Test minimal effect-polymorphism inference on higher-order library APIs.
8. Benchmark default/verified/deep diagnostic overhead and ring-buffer memory.
9. Compare LLM generation accuracy for alternative binding/resource/channel/select syntaxes during specification drafting.
10. Test Python differential-validation pipeline on intentionally different semantic domains to ensure exclusions are explicit rather than post hoc.

---

## Part X — Source Record

This section records the external evidence and precedents that materially informed decisions. It is not a bibliography of every language mentioned. Claims remain scoped to what the source supports.

---

### 10.1 LLM coding and language-design evidence

#### LLMFix (arXiv:2409.00676)

**Supported claim**: In its benchmark setting, three error categories were directly repairable using simple predictable rule-based post-processing, including indentation and missing imports.

**Not supported**: That all other LLM error categories are beyond influence by programming-language design.

**Use here**: Supports brace syntax, import diagnostics/visible insertion, and the distinction between mechanical repairs and semantic reasoning.

**Confidence**: High for the narrow taxonomy result; moderate for generalisation to frontier models and broader tasks.

#### SonarQube analysis of LLM-generated code (arXiv:2508.14727)

**Supported claim**: Functionally passing generated code can still contain systematic maintainability, error-handling and resource-management issues.

**Not supported**: That scoped resource providers are uniquely optimal.

**Use here**: Motivation for structural resource handling, verified diagnostics and quality checks beyond tests.

**Confidence**: Moderate-high for the broad quality gap; mechanism-specific conclusions remain design judgments.

#### Informal Claude Code language-cost experiment

**Supported claim**: In one practical task/model setup, dynamically typed languages required fewer correction turns and lower agent cost than several statically typed languages.

**Limitations**: One task family, one model/setup, training-data confounding and informal methodology.

**Use here**: One input into dynamic-default/draft-mode design, not decisive proof.

**Claim confidence**: Moderate. **Decision confidence**: High because progressive annotation has independent left-to-right generation benefits.

#### Vera zero-training-data experiment

**Supported claim**: A frontier model can learn and use a novel language from a reference document, and language constraints may influence code-generation quality.

**Limitations**: Small benchmark, informal/single-run character, model variance, uncertain representativeness.

**Use here**: Proof of concept for in-context language learning and contract-oriented design.

**Correction to novelty claim**: Vera and similar experiments mean this document must not claim no language has ever targeted LLM generation. The narrower claim is that no mature widely adopted general-purpose language pursues this complete combination.

#### SimPy / DualCode (arXiv:2404.16333)

**Supported claim**: Alternative grammars can reduce token count; brace-delimited forms can be more token-efficient than indentation-heavy forms.

**Not supported**: That separate LLM-facing and human-facing source forms are desirable.

**Use here**: Secondary support for braces; DualCode itself remains rejected because of review/audit divergence.

#### Broader LLM error analyses

**Supported themes**: Misinterpretation, missing edge cases, invented names, type inconsistency, incomplete generation and downstream symptom/root-cause distance recur across studies.

**Use here**: Motivation for exhaustive variants, local failure markers, structured diagnostics, canonical name resolution and comparative locality.

---

### 10.2 Error handling and contracts

#### Joe Duffy, “The Error Model”

**Supported concepts**:

- abandonment for programming bugs/violated assumptions;
- recoverable checked failure for expected conditions;
- visible propagation markers;
- contracts at interfaces;
- the importance of error-effect composition for higher-order functions.

**Adaptations here**:

- structured task isolation and group failure trees;
- Result as stored failure data;
- restricted abandonment-safe resource release;
- draft/verified development modes.

**Confidence**: High as production language-design evidence, while recognising that this language has different implementation and use-case constraints.

#### Duffy, concurrency and exceptions

**Supported concepts**: Concurrent failure may contain several independent stacks; aggregation must preserve individual causes and task identity.

**Use here**: `AggregateException`, task-tree reports, quiescence before outward outcome.

#### Design by Contract literature (Meyer and successors)

**Supported concepts**: Preconditions, postconditions, invariants, entry snapshots and behavioural-subtyping obligations.

**Adaptations here**: Executable restricted predicates rather than proof; protocol contract inheritance rather than general implication checking; cleanup-aware exit ordering.

#### Liskov and Wing, behavioural subtyping

**Supported concept**: Implementations must not require more or promise less than their abstraction contract.

**Use here**: Prohibiting implementation-added protocol preconditions in version 1 and inheriting protocol postconditions.

---

### 10.3 Gradual typing

#### Siek and Taha, gradual typing

**Supported concept**: Typed and dynamic regions require an explicit operational account, not merely optional annotations.

#### Transient/first-order gradual typing work, including Reticulated Python

**Supported concepts**:

- runtime checks at typed uses and boundaries;
- avoiding wrapper/proxy identity changes;
- compatibility with open-world dynamic values.

**Trade-offs recognised**: Repeated checks and different blame properties from guarded systems.

**Use here**: Version-1 transient semantics, boundary diagnostics, runtime annotation enforcement in both modes.

---

### 10.4 Structured concurrency and cancellation

#### Nathaniel J. Smith, structured concurrency/nurseries

**Supported concept**: Structured child lifetimes restore function abstraction and make error propagation/resource cleanup compositional.

#### Python `asyncio.TaskGroup`

**Supported precedents**:

- child failure triggers sibling cancellation and group quiescence;
- exception groups preserve several failures;
- external cancellation must not be silently lost when combined with internal failure.

**Not copied wholesale**: Python's exact exception/cancellation hierarchy and scheduling semantics.

#### Kotlin coroutines and Swift structured concurrency

**Supported precedents**: Scope-owned tasks, cooperative cancellation, task groups/supervision, explicit suspension.

#### Trio

**Supported precedent**: Nursery failure handling and cancellation scopes; useful model for cleanup masking and quiescence.

---

### 10.5 Channels and selection

#### Go channels and `select`

**Supported precedents**:

- send/receive as symmetric selectable communications;
- atomic one-branch commitment;
- same-sender FIFO ordering;
- explicit default/nonblocking patterns;
- random choice among simultaneously ready cases.

**Not adopted**:

- random tie-breaking in normal execution;
- effectful evaluation of all branch operands;
- channels as the task-lifetime model.

#### Tokio `select!`

**Supported lessons**:

- selecting tasks, timers, channels and async operations through one surface can compose well;
- losing arbitrary futures creates cancellation-safety obligations;
- biased/unbiased ordering and fairness are consequential.

**Use here**: Reason for restricting selectable operations to runtime-safe forms and routing arbitrary async work through task handles.

#### Kotlin `select`

**Supported lessons**:

- controlled selectable operation family;
- task/channel/timeout integration;
- explicit biased and unbiased alternatives;
- prompt cancellation while suspended.

**Use here**: Closest precedent for a closed selectable family, though builder syntax is not preferred.

#### Clojure core.async `alts!`

**Supported lessons**:

- dynamic operation sets are useful;
- priority/nonblocking options exist;
- detached tagged outcomes and side-effectful operation construction reduce locality.

**Use here**: Dynamic homogeneous helper APIs rather than fully heterogeneous dynamic selection.

#### Erlang selective receive

**Supported lessons**:

- colocated pattern/handler logic is expressive;
- retained unmatched messages introduce mailbox-history state and possible indefinite accumulation.

**Use here**: Pattern matching within receive outcomes, but not one implicit mailbox as the primary model.

#### Rust Crossbeam channels

**Supported lessons**:

- dynamic selection and biased/unbiased forms;
- readiness/commit separation can be low-level and misuse-prone.

**Use here**: Runtime may use reservation machinery internally, while user semantics atomically commit one operation.

#### Critical essays on Go channels

These are treated as arguments identifying composability, nondeterminism and backpressure concerns, not as empirical proof that channels fail generally. The adopted synthesis is:

> Structured task groups own lifetime; channels own communication.

---

### 10.6 Language and toolchain precedents

#### Go

Relevant precedents: structural interfaces, canonical formatter, import hygiene, simple module/package concepts, `defer`, channel communication. Each is evaluated independently; Go semantics are not inherited wholesale.

#### Rust

Relevant precedents: `fn`, explicit effects through Result-like types, Send/Sync conceptual separation, rich compiler diagnostics. General ownership/move semantics are rejected for version 1.

#### Python

Relevant precedents: implementation substrate, dynamic semantics, context-manager composition, async/await familiarity and reference implementations. Python is not semantic authority.

#### Crafting Interpreters

Relevant precedent: staged tree-walking interpreter, explicit scanner/parser/evaluator phases and conformance tests. Implementation details belong in the later Implementation Notes document.

#### Rust and Elm diagnostics

Relevant precedents: multi-span structured error reports, stable codes, educational explanation, actionable suggestions. This language retains multi-error recovery rather than Elm's single-error presentation because agent correction benefits from several independent errors.

---

### 10.7 Diagnostic and instrumentation overhead precedents

**Java Flight Recorder and comparable lightweight tracing**: Demonstrate that always-on structured recording can target low-single-digit overhead when metadata is compact and rendering is deferred.

**AddressSanitizer**: Commonly cited around a roughly twofold slowdown, illustrating the cost range of substantial memory-safety instrumentation.

**ThreadSanitizer and Go race detection**: Can impose several-fold to order-of-magnitude time and memory overhead, illustrating why heavy verification belongs in explicit modes and why long-running workloads need an additive ceiling rather than an unrestricted multiplier.

**Use here**: These tools do not prove the chosen budgets. They establish that instrumentation costs vary by tier and support separating lightweight default metadata, verified runtime checking and explicit deep diagnostics. The numerical targets remain provisional engineering judgments to be validated on representative workloads.

---

## Closing status

Version 3 consolidates the architectural review of Version 2. It is intended to be sufficiently coherent for specification drafting, subject to the specification-stage decisions and provisional experiments recorded in Part IX.

The specification writer should preserve the semantic commitments, make the listed surface decisions, and return any newly discovered semantic conflict to the designer rather than resolving it accidentally through grammar or implementation convenience.

---

*End of Design Document Version 3*

*Based on the original design notes, Version 2 architectural review, subsequent subsystem decisions, and external-language research through July 2026.*
