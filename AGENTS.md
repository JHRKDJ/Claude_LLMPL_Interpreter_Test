# AGENTS.md — runbook for a fresh agent

**Project:** experimental reference implementation (Python 3.11 interpreter + checker +
toolchain) of the V3 LLM-native language, plus the LocalFlow application written in
it. The goal statement is `RUN0_GOAL.md` (instructions, not background).

**Authority**
- `design/LLM_NATIVE_DESIGN_V3.md` — V3, authoritative for semantics. Read it fully.
- `DECISIONS.md` — spec-stage choices/ambiguity resolutions (subordinate to V3).
- `docs/semantics/*.md` — implementation contracts (subordinate to V3).
- `docs/LANGUAGE_GUIDE.md` — user-facing reference for writing programs.
- `examples/localflow/PROGRAM_SPEC.md` — LocalFlow application spec (independent of V3).

**Run**
```
pip install pytest                 # only test dependency
python -m pytest -q                # whole suite
python -m pytest tests/conformance -q
bin/lang run path/to/main.lang     # or: python -m lang run ...
bin/lang check --mode=verified file.lang --json
bin/lang format --check file.lang
bin/lang test path/ --schedule=random --seed=42
python -m pytest examples/localflow -q   # LocalFlow black-box suite
```

**Progress tracking:** `PROGRESS.md` (state + next actions), `TODO.md` (authoritative
remaining work), `WORK_ITEMS.json` (stable IDs; `python tools/workitems.py summary`),
`FEATURE_MATRIX.md` (V3 feature coverage), `BUG_LEDGER.md` (defects + regressions).

**After context compaction:** reread this file, `PROGRESS.md`, `TODO.md`, run
`python tools/workitems.py summary`, skim `FEATURE_MATRIX.md` and `BUG_LEDGER.md`,
`git log --oneline | head -30`, then reread the V3 sections for the current subsystem.

**Rules:** every interpreter bug gets a failing regression test first
(`tests/regressions/`), then a ledger entry, then the fix. Never weaken tests. Commit
granular, documented changes on the working branch.
