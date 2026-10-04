"""`lang repl` — interactive session with runtime module loading (V3 7.14.4, SPEC-024).

Session model
- The session owns a *workspace module* (`__repl__`): the accumulated imports and
  declarations entered so far. Entering a declaration rebuilds the workspace program
  (load, static check in the session mode, link); declarations that fail the check
  are rejected and the workspace is unchanged.
- Statements and expressions run in a persistent top-level environment, inside an
  async root task (so `await`, `parallel`, `select` work). A non-Unit expression
  value is printed.
- Runtime module loading: `:load path.lang` imports a project module into the
  workspace under its module name; module identity is the module name.
- Reload is explicit (V3 7.14.4 "retaining incompatible mutable definitions
  invisibly" is avoided): redefining a declaration, `:reload` and `:reset` discard
  all session bindings, and the REPL lists the bindings it discarded. Pure
  additions keep them.
- Errors never end the session: a static error rejects the entry, a runtime failure
  prints its diagnostic and keeps the bindings made before the failure.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Optional

from ..diagnostics.render_text import render
from ..syntax import ast as A
from ..syntax.parser import parse_text

HELP = """commands:
  :help                 this help
  :decls                show the workspace declarations
  :load <path.lang>     import a module file into the session (by its module name)
  :reload [module]      re-read loaded modules from disk (discards session bindings)
  :reset                clear declarations and bindings
  :mode draft|verified  acceptance mode for new entries
  :quit                 leave
Enter declarations, statements or expressions; open braces continue onto the next line."""


class ReplSession:
    def __init__(self, mode: str = "draft", clock: str = "real", root: Optional[Path] = None,
                 stdout=None, stderr=None):
        self.mode = mode
        self.clock = clock
        self.root = Path(root or Path.cwd())
        self.out = stdout or sys.stdout
        self.err = stderr or sys.stderr
        self.imports: list[str] = []
        self.decls: dict[str, str] = {}  # name -> source text, in definition order
        self.loaded: list[str] = []  # module names loaded with :load
        self.interp = None
        self.program = None
        self.bindings: dict[str, object] = {}
        self.counter = 0

    # ------------------------------------------------------------ workspace
    def workspace_text(self, imports=None, decls=None) -> str:
        imports = self.imports if imports is None else imports
        decls = self.decls if decls is None else decls
        return "\n".join(imports) + "\n\n" + "\n\n".join(decls.values()) + "\n"

    def build(self, imports, decls):
        """Load + check + link a candidate workspace; returns (interp, program, diags)."""
        from ..modules.loader import load_program
        from ..runtime.interp import Interpreter, RunOptions
        from .driver import check_program
        prog = load_program(self.root / "__repl__.lang", text=self.workspace_text(imports, decls))
        co = check_program(prog, self.mode)
        errors = [d for d in co.diagnostics if d.severity == "error"]
        if errors:
            return None, None, errors
        opts = RunOptions(mode=self.mode, clock=self.clock, stdout=self.out, stderr=self.err)
        return Interpreter(co.program, opts), co.program, [d for d in co.diagnostics if d.severity != "error"]

    def ensure_built(self) -> bool:
        if self.interp is not None:
            return True
        interp, prog, diags = self.build(self.imports, self.decls)
        if interp is None:
            self.report(diags)
            return False
        self.interp, self.program = interp, prog
        return True

    # ------------------------------------------------------------ entries
    def report(self, diags) -> None:
        for d in diags:
            self.err.write(render(d, "default") + "\n")

    def discard_bindings(self, why: str) -> None:
        if self.bindings:
            names = ", ".join(sorted(self.bindings))
            self.out.write(f"note: {why}; discarded session bindings: {names}\n")
        self.bindings.clear()

    def execute(self, text: str) -> bool:
        """Process one complete entry. Returns False only for `:quit`."""
        s = text.strip()
        if not s:
            return True
        if s.startswith(":"):
            return self.command(s)
        res = parse_text(text, "<repl>", allow_toplevel_statements=True)
        if not res.ok:
            self.report([d for d in res.diagnostics if d.severity == "error"])
            return True
        mod = res.module
        new_imports = list(self.imports)
        for imp in mod.imports:
            line = imp.span.text
            if line not in new_imports:
                new_imports.append(line)
        new_decls = dict(self.decls)
        redefined = []
        for d in mod.decls:
            if d.name in new_decls:
                redefined.append(d.name)
            new_decls[d.name] = d.span.text
        if mod.imports or mod.decls:
            interp, prog, diags = self.build(new_imports, new_decls)
            if interp is None:
                self.report(diags)
                return True
            self.report(diags)
            self.imports, self.decls = new_imports, new_decls
            self.interp, self.program = interp, prog
            if redefined:
                self.discard_bindings("redefined " + ", ".join(f"`{n}`" for n in redefined))
            for d in mod.decls:
                self.out.write(f"defined {d.name}\n")
        if res.statements:
            if self.check_statements(text, res.statements):
                self.run_statements(res.statements)
        return True

    def check_statements(self, text: str, stmts) -> bool:
        """Static check of an entry's statements: they are checked as the body of a
        synthetic async function whose parameters are the session bindings (Dyn)."""
        from ..modules.loader import load_program
        from .driver import check_program
        body = "\n".join(text[st.span.start:st.span.end] for st in stmts)
        params = ", ".join(sorted(self.bindings))
        src = self.workspace_text() + f"\nasync fn __repl_entry__({params}) {{\n{body}\n}}\n"
        prog = load_program(self.root / "__repl__.lang", text=src)
        co = check_program(prog, self.mode)
        start = len(self.workspace_text())
        mine = [d for d in co.diagnostics if d.primary is not None and d.primary.span is not None
                and d.primary.span.start >= start]
        errors = [d for d in mine if d.severity == "error"]
        if errors:
            self.report(errors)
            return False
        return True

    def run_statements(self, stmts) -> None:
        if not self.ensure_built():
            return
        from ..runtime.interp.core import Env, Frame
        from ..runtime.values import UNIT
        from ..runtime.capture import Budget, safe_repr
        interp = self.interp
        mrt = interp.entry_module()
        bindings = self.bindings
        last = stmts[-1] if isinstance(stmts[-1], A.ExprStmt) else None

        def body():
            interp.init_consts()
            env = Env(mrt.env, kind="fn")
            env.vars.update(bindings)
            fr = Frame("<repl>", None, stmts[0].span, env, True)
            interp.sched.current.frames.append(fr)
            try:
                # one entry is one block: its `defer`s run at the end of the entry
                return interp.exec_block(A.Block(span=stmts[0].span, stmts=list(stmts)), env, scope=False)
            finally:
                bindings.update(env.vars)  # keep bindings made before a failure
                interp.sched.current.frames.pop()
        from ..runtime.scheduler import Scheduler
        interp.sched = Scheduler(interp.options.clock, interp.options.schedule, interp.options.seed)
        interp.sched.on_deadlock = interp.handle_deadlock
        interp.hard_termination = None
        res = interp.run_root(body, "repl")
        for w in res.warnings:
            self.report([w])
        interp.runtime_warnings = []
        if res.outcome == "ok":
            if last is not None and res.value is not UNIT:
                self.out.write(safe_repr(res.value, Budget(2000)) + "\n")
        else:
            self.report(res.diagnostics)

    # ------------------------------------------------------------ commands
    def command(self, s: str) -> bool:
        parts = s.split()
        cmd, args = parts[0], parts[1:]
        if cmd in (":quit", ":q", ":exit"):
            return False
        if cmd == ":help":
            self.out.write(HELP + "\n")
        elif cmd == ":decls":
            self.out.write(self.workspace_text().strip() + "\n")
        elif cmd == ":reset":
            self.imports, self.decls, self.loaded = [], {}, []
            self.interp = None
            self.discard_bindings("session reset")
        elif cmd == ":mode":
            if args and args[0] in ("draft", "verified"):
                self.mode = args[0]
                self.interp = None
                self.out.write(f"mode: {self.mode}\n")
            else:
                self.err.write("usage: :mode draft|verified\n")
        elif cmd == ":load":
            if not args:
                self.err.write("usage: :load path.lang\n")
                return True
            from ..modules.loader import module_name_for
            p = Path(args[0])
            if not p.is_absolute():
                p = self.root / p
            if not p.exists():
                self.err.write(f"no such file: {p}\n")
                return True
            name = module_name_for(p, self.root)
            line = f"import {name}"
            new_imports = self.imports + ([line] if line not in self.imports else [])
            interp, prog, diags = self.build(new_imports, self.decls)
            if interp is None:
                self.report(diags)
                return True
            self.imports, self.interp, self.program = new_imports, interp, prog
            if name not in self.loaded:
                self.loaded.append(name)
            self.out.write(f"loaded module {name} (use it as `{name.split('.')[-1]}`)\n")
        elif cmd == ":reload":
            targets = args or self.loaded
            interp, prog, diags = self.build(self.imports, self.decls)
            if interp is None:
                self.report(diags)
                self.out.write("reload failed; the previous definitions remain active\n")
                return True
            self.interp, self.program = interp, prog
            self.discard_bindings("reloaded " + (", ".join(targets) if targets else "workspace"))
            self.out.write("reloaded " + (", ".join(targets) if targets else "workspace") + "\n")
        else:
            self.err.write(f"unknown command {cmd} (try :help)\n")
        return True


def needs_more(buf: str) -> bool:
    depth = 0
    in_str = False
    esc = False
    for ch in buf:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
    return depth > 0 or buf.rstrip().endswith(("=", "+", "-", "*", "/", "&&", "||", ",", "=>"))


def repl_main(args) -> int:
    mode = getattr(args, "mode", None) or "draft"
    clock = getattr(args, "clock", None) or "real"
    sess = ReplSession(mode=mode, clock=clock)
    interactive = sys.stdin.isatty()
    if interactive:
        sys.stdout.write(f"lang repl ({mode} mode) — :help for commands, :quit to leave\n")
    buf = ""
    while True:
        try:
            if interactive:
                line = input("... " if buf else ">>> ")
            else:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.rstrip("\n")
        except EOFError:
            break
        except KeyboardInterrupt:
            buf = ""
            sys.stdout.write("\n")
            continue
        buf = buf + "\n" + line if buf else line
        if needs_more(buf):
            continue
        entry, buf = buf, ""
        if not sess.execute(entry):
            break
    if buf.strip():
        sess.execute(buf)
    return 0
