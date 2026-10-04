#!/usr/bin/env python3
"""LocalFlow reference model (oracle) — a direct discrete-event simulation of
PROGRAM_SPEC.md. It shares no code or architecture with the LocalFlow implementation
written in the new language; it exists only to compute expected externally visible
results (report.json, produced files, stdout, exit status).

Usage: python localflow_ref.py WORKFLOW.json OUTDIR
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

INF = math.inf
KINDS = ("compute", "external", "transform", "map", "reduce", "check", "subworkflow")
ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
STATUSES = ("SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED", "SKIPPED", "NOT_RUN")
FINAL = set(STATUSES)
RETRYABLE = {"retryable", "timeout"}


class DefectStop(Exception):
    """compute/assert mismatch: the program stops with exit 3 and no report."""


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


# ----------------------------------------------------------------------------- validation
def err(code, job=None, workflow=None, message="", jobs=None):
    e = {"code": code, "job": job, "workflow": workflow, "message": message}
    if jobs is not None:
        e["jobs"] = jobs
    return e


def validate(wf, sub_name=None, top=True, has_cancel=False):
    errors = []
    W = sub_name

    def bad(msg, job=None):
        errors.append(err("malformed", job, W, msg))

    if not isinstance(wf, dict):
        bad("workflow must be an object")
        return errors
    if not isinstance(wf.get("workflow"), str) or not wf.get("workflow"):
        bad("workflow id must be a non-empty string")
    jobs = wf.get("jobs")
    if not isinstance(jobs, list):
        bad("jobs must be an array")
        jobs = []
    mc = wf.get("maxConcurrency", 4)
    if not is_int(mc) or mc < 1:
        bad("maxConcurrency must be an integer >= 1")
    groups = wf.get("groups", {})
    if not isinstance(groups, dict) or any(not is_int(v) or v < 1 for v in groups.values()):
        bad("groups must map names to integers >= 1")
        groups = {}
    if wf.get("onFailure", "continue") not in ("continue", "failFast"):
        bad("onFailure must be continue or failFast")
    if "cancelAfterMs" in wf:
        if not top:
            bad("sub-workflows cannot have cancelAfterMs")
        elif not is_int(wf["cancelAfterMs"]) or wf["cancelAfterMs"] < 0:
            bad("cancelAfterMs must be an integer >= 0")
    subs = wf.get("workflows", {})
    if not top and "workflows" in wf:
        bad("sub-workflows cannot define workflows")
    if not isinstance(subs, dict) or any(not isinstance(v, dict) for v in subs.values()):
        bad("workflows must map names to workflow objects")
        subs = {}
    cancel_present = top and is_int(wf.get("cancelAfterMs"))

    seen = set()
    ids = [j.get("id") for j in jobs if isinstance(j, dict)]
    all_ids = {i for i in ids if isinstance(i, str)}
    by_id = {}
    for j in jobs:
        if not isinstance(j, dict):
            bad("job must be an object")
            continue
        jid = j.get("id")
        if not isinstance(jid, str) or not ID_RE.match(jid):
            bad("job id must match [A-Za-z0-9_.-]+")
            jid_ok = None
        else:
            jid_ok = jid
        if jid_ok is not None:
            if jid_ok in seen:
                errors.append(err("duplicate-id", jid_ok, W, "duplicate job id"))
            seen.add(jid_ok)
            by_id.setdefault(jid_ok, j)
        kind = j.get("kind")
        if kind not in KINDS:
            bad("unknown kind", jid_ok)
        if kind == "subworkflow" and not top:
            bad("sub-workflows cannot contain subworkflow jobs", jid_ok)
        deps = j.get("deps", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            bad("deps must be an array of distinct job ids", jid_ok)
            deps = []
        for d in deps:
            if d not in all_ids:
                errors.append(err("missing-dependency", jid_ok, W, f"unknown dependency {d}"))
        if "when" in j:
            w = j["when"]
            ok = isinstance(w, dict) and isinstance(w.get("job"), str) and isinstance(w.get("equals"), bool)
            if not ok or w["job"] not in deps:
                bad("when must name a dependency and a boolean", jid_ok)
            else:
                target = next((x for x in jobs if isinstance(x, dict) and x.get("id") == w["job"]), None)
                if target is None or target.get("kind") != "check":
                    bad("when must name a check job", jid_ok)
        if "group" in j and (not isinstance(j["group"], str) or j["group"] not in groups):
            bad("unknown group", jid_ok)
        r = j.get("retry", {})
        if not isinstance(r, dict) or not is_int(r.get("maxAttempts", 1)) or r.get("maxAttempts", 1) < 1 \
                or not is_int(r.get("backoffMs", 0)) or r.get("backoffMs", 0) < 0 \
                or not is_int(r.get("multiplier", 1)) or r.get("multiplier", 1) < 1:
            bad("invalid retry policy", jid_ok)
        if "timeoutMs" in j and (not is_int(j["timeoutMs"]) or j["timeoutMs"] < 1):
            bad("timeoutMs must be an integer >= 1", jid_ok)
        cfg = j.get("config", {})
        if not isinstance(cfg, dict):
            bad("config must be an object", jid_ok)
            continue
        msg = check_config(kind, cfg, deps, subs if top else {})
        if msg == "missing-workflow":
            errors.append(err("missing-workflow", jid_ok, W, "unknown sub-workflow"))
        elif msg:
            bad(msg, jid_ok)
        if kind == "external" and "timeoutMs" not in j and not (has_cancel or cancel_present):
            steps = []
            if isinstance(cfg.get("script", ["ok"]), list):
                steps += cfg.get("script", ["ok"])
            for m in cfg.get("mirrors", []) if isinstance(cfg.get("mirrors", []), list) else []:
                if isinstance(m, dict) and isinstance(m.get("script", ["ok"]), list):
                    steps += m.get("script", ["ok"])
            if "hang" in steps:
                bad("a hang step needs timeoutMs or cancelAfterMs", jid_ok)
    # cycles
    graph = {}
    for j in jobs:
        if isinstance(j, dict) and isinstance(j.get("id"), str) and j["id"] not in graph:
            deps = j.get("deps", [])
            graph[j["id"]] = [d for d in deps if isinstance(d, str) and d in all_ids] if isinstance(deps, list) else []
    on_cycle = cycle_nodes(graph)
    if on_cycle:
        order = [j.get("id") for j in jobs if isinstance(j, dict)]
        listed = []
        for i in order:
            if i in on_cycle and i not in listed:
                listed.append(i)
        errors.append(err("cycle", None, W, "dependency cycle", jobs=listed))
    if top:
        for name, sw in subs.items():
            errors.extend(validate(sw, name, top=False))
    return errors


def check_config(kind, c, deps, subs):
    def nat(k, default=None, minimum=0):
        v = c.get(k, default)
        return is_int(v) and v >= minimum

    if kind == "compute":
        op = c.get("op")
        if op in ("fib", "sumTo", "primeCount"):
            if not nat("n"):
                return "compute needs n >= 0"
        elif op == "assert":
            if not is_int(c.get("value")) or not is_int(c.get("expect")):
                return "assert needs integer value and expect"
        else:
            return "unknown compute op"
        if not nat("costMs", 0):
            return "costMs must be >= 0"
    elif kind == "external":
        def ext_ok(m):
            s = m.get("script", ["ok"])
            return (is_int(m.get("latencyMs", 10)) and m.get("latencyMs", 10) >= 0 and isinstance(s, list) and s
                    and all(x in ("ok", "retryable", "permanent", "hang") for x in s))
        if not ext_ok(c):
            return "invalid external config"
        if "mirrors" in c:
            ms = c["mirrors"]
            if not isinstance(ms, list) or not ms or not all(isinstance(m, dict) and ext_ok(m) for m in ms):
                return "invalid mirrors"
    elif kind == "transform":
        if not isinstance(c.get("input"), str) or not isinstance(c.get("output"), str) or not c.get("output"):
            return "transform needs input and output"
        if c.get("op") not in ("upper", "number", "csvSum"):
            return "unknown transform op"
        if not nat("latencyMs", 0):
            return "latencyMs must be >= 0"
        for b in ("failAfterWrite", "failCleanup"):
            if not isinstance(c.get(b, False), bool):
                return f"{b} must be a boolean"
    elif kind == "map":
        has_items, has_from = "items" in c, "from" in c
        if has_items == has_from:
            return "map needs exactly one of items or from"
        if has_items and (not isinstance(c["items"], list) or not all(is_int(x) for x in c["items"])):
            return "items must be integers"
        if has_from and c["from"] not in deps:
            return "from must be a dependency"
        if c.get("op") not in ("square", "inc"):
            return "unknown map op"
        if not isinstance(c.get("failOn", []), list) or not all(is_int(x) for x in c.get("failOn", [])):
            return "failOn must be integers"
        if not nat("itemLatencyMs", 0) or not nat("parallelism", 4, 1):
            return "invalid map timing"
        if not isinstance(c.get("allowPartial", False), bool):
            return "allowPartial must be a boolean"
    elif kind == "reduce":
        if c.get("op") not in ("sum", "max", "concat", "count"):
            return "unknown reduce op"
    elif kind == "check":
        if c.get("input") not in deps or c.get("op") not in ("gt", "lt", "eq") or not is_int(c.get("value")):
            return "check needs a dependency input, op and integer value"
    elif kind == "subworkflow":
        if not isinstance(c.get("workflow"), str):
            return "subworkflow needs workflow"
        if c["workflow"] not in subs:
            return "missing-workflow"
    return None


def cycle_nodes(graph):
    index, low, stack, on, out, counter = {}, {}, [], set(), set(), [0]

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, []):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or v in graph.get(v, []):
                out.update(comp)

    sys.setrecursionlimit(10000)
    for v in graph:
        if v not in index:
            strong(v)
    return out


# ----------------------------------------------------------------------------- job outcomes
@dataclass
class Outcome:
    """What one started job does, decided at start time from its inputs."""
    end: float
    attempts_at: list  # attempt start times (attempt k counted when started)
    ok: bool = False
    output: object = None
    cls: str | None = None
    details: list = field(default_factory=list)
    effects: list = field(default_factory=list)  # (time, callable) file effects
    subrun: object = None
    sub_cancel_at: float | None = None
    partial_output: object = None


def attempts_loop(job, start, attempt_fn):
    """Generic retry/timeout loop. attempt_fn(k, t0) -> (end_time, kind, payload)
    with kind in ok / retryable / permanent / <class>; end_time may be INF."""
    r = job.get("retry", {})
    max_att, backoff, mult = r.get("maxAttempts", 1), r.get("backoffMs", 0), r.get("multiplier", 1)
    timeout = job.get("timeoutMs")
    t = start
    starts = []
    for k in range(1, max_att + 1):
        starts.append(t)
        end, kind, payload = attempt_fn(k, t)
        if timeout is not None and end - t >= timeout:
            end, kind, payload = t + timeout, "timeout", ("timeout", t + timeout)
        if kind == "ok":
            return end, starts, True, payload, None
        if kind in RETRYABLE and k < max_att:
            t = end + backoff * mult ** (k - 1)
            continue
        cls = {"retryable": "retries-exhausted"}.get(kind, kind)
        return end, starts, False, payload, cls
    raise AssertionError("unreachable")


def external_attempt(cfg):
    def one(m, k, t0):
        script = m.get("script", ["ok"])
        step = script[min(k, len(script)) - 1]
        lat = m.get("latencyMs", 10)
        if step == "hang":
            return INF, "hang", None
        return t0 + lat, step, m.get("value")

    def attempt(k, t0):
        mirrors = cfg.get("mirrors")
        if not mirrors:
            end, step, val = one(cfg, k, t0)
            if step == "hang":
                return INF, "hang", None
            return end, step, val
        results = [one(m, k, t0) for m in mirrors]
        oks = [(e, i, v) for i, (e, s, v) in enumerate(results) if s == "ok"]
        if oks:
            e, i, v = min(oks)
            return e, "ok", v
        end = max(e for e, s, v in results)
        if end == INF:
            return INF, "hang", None
        kind = "permanent" if all(s == "permanent" for e, s, v in results) else "retryable"
        return end, kind, None
    return attempt


def transform_text(op, text):
    if op == "upper":
        return text.upper(), None
    if op == "number":
        lines = text.split("\n")
        if lines and lines[-1] == "":
            body, trail = lines[:-1], "\n"
        else:
            body, trail = lines, ""
        return "\n".join(f"{i + 1}: {ln}" for i, ln in enumerate(body)) + trail, None
    # csvSum
    rows = [ln for ln in text.split("\n") if ln != ""]
    if not rows:
        return None, "bad-input"
    header = rows[0].split(",")
    sums = [0] * len(header)
    for row in rows[1:]:
        cells = row.split(",")
        if len(cells) != len(header):
            return None, "bad-input"
        for i, c in enumerate(cells):
            if not re.fullmatch(r"-?[0-9]+", c.strip()):
                return None, "bad-input"
            sums[i] += int(c.strip())
    out = "column,sum\n" + "".join(f"{h},{s}\n" for h, s in zip(header, sums))
    return out, None


def plan_job(job, start, outputs, statuses, ctx):
    kind = job["kind"]
    cfg = job.get("config", {})
    if kind == "compute":
        op = cfg["op"]
        if op == "assert" and cfg["value"] != cfg["expect"]:
            cost = cfg.get("costMs", 0)
            return Outcome(end=start + cost, attempts_at=[start], cls="__defect__")

        def attempt(k, t0):
            n = cfg.get("n", 0)
            if op == "fib":
                a, b = 0, 1
                for _ in range(n):
                    a, b = b, a + b
                v = a
            elif op == "sumTo":
                v = n * (n + 1) // 2
            elif op == "primeCount":
                v = sum(1 for x in range(2, n + 1) if all(x % d for d in range(2, int(x ** 0.5) + 1)))
            else:
                v = cfg["value"]
            return t0 + cfg.get("costMs", 0), "ok", v
        end, starts, ok, val, cls = attempts_loop(job, start, attempt)
        return Outcome(end, starts, ok, val if ok else None, cls)
    if kind == "external":
        end, starts, ok, val, cls = attempts_loop(job, start, external_attempt(cfg))
        return Outcome(end, starts, ok, val if ok else None, cls)
    if kind == "transform":
        return plan_transform(job, start, ctx)
    if kind == "map":
        return plan_map(job, start, outputs)
    if kind == "reduce":
        return plan_reduce(job, start, outputs, statuses)
    if kind == "check":
        v = outputs.get(cfg["input"])
        if not is_int(v):
            return Outcome(start, [start], False, None, "bad-input")
        res = {"gt": v > cfg["value"], "lt": v < cfg["value"], "eq": v == cfg["value"]}[cfg["op"]]
        return Outcome(start, [start], True, res)
    if kind == "subworkflow":
        return plan_sub(job, start, ctx)
    raise AssertionError(kind)


def plan_transform(job, start, ctx):
    cfg = job["config"]
    src = Path(ctx["base"]) / cfg["input"]
    lat = cfg.get("latencyMs", 0)
    details_box = {}

    def attempt(k, t0):
        try:
            text = src.read_text(encoding="utf-8")
        except OSError:
            return t0, "io", None
        out, problem = transform_text(cfg["op"], text)
        if problem:
            return t0, problem, None
        if cfg.get("failAfterWrite"):
            return t0 + lat, "transform", None
        if cfg.get("failCleanup"):
            return t0 + lat, "cleanup", out
        return t0 + lat, "ok", out
    end, starts, ok, val, cls = attempts_loop(job, start, attempt)
    o = Outcome(end, starts, ok, None, cls)
    if cls in ("io", "bad-input", "transform") and cfg.get("failCleanup"):
        o.details = ["cleanup"]
    if ok:
        o.output = {"file": cfg["output"], "bytes": len(val)}
        o.effects.append((end, ("write", ctx["outdir"], cfg["output"], val)))
    return o


def plan_map(job, start, outputs):
    cfg = job["config"]
    items = cfg["items"] if "items" in cfg else outputs.get(cfg["from"])
    if not isinstance(items, list) or not all(is_int(x) for x in items):
        return Outcome(start, [start], False, None, "bad-input")
    par, lat = cfg.get("parallelism", 4), cfg.get("itemLatencyMs", 0)
    batches = math.ceil(len(items) / par) if items else 0
    fail_on = set(cfg.get("failOn", []))
    results, failed = [], []
    for i, x in enumerate(items):
        if x in fail_on:
            results.append(None)
            failed.append(i)
        else:
            results.append(x * x if cfg["op"] == "square" else x + 1)
    out = {"results": results, "failed": failed}

    def attempt(k, t0):
        if failed and not cfg.get("allowPartial", False):
            return t0 + batches * lat, "partial", out
        return t0 + batches * lat, "ok", out
    end, starts, ok, val, cls = attempts_loop(job, start, attempt)
    o = Outcome(end, starts, ok, val if ok else None, cls)
    if cls == "partial":
        o.partial_output = out
    return o


def plan_reduce(job, start, outputs, statuses):
    cfg = job["config"]
    ins = [outputs[d] for d in job.get("deps", []) if statuses[d] == "SUCCEEDED"]
    op = cfg["op"]

    def fail():
        return Outcome(start, [start], False, None, "bad-input")
    if op == "count":
        return Outcome(start, [start], True, len(ins))
    if op == "concat":
        if not all(isinstance(x, list) for x in ins):
            return fail()
        return Outcome(start, [start], True, [y for x in ins for y in x])
    flat = []
    for x in ins:
        if is_int(x):
            flat.append(x)
        elif isinstance(x, list) and all(is_int(y) for y in x):
            flat.extend(x)
        else:
            return fail()
    if op == "sum":
        return Outcome(start, [start], True, sum(flat))
    if not flat:
        return fail()
    return Outcome(start, [start], True, max(flat))


def plan_sub(job, start, ctx):
    cfg = job["config"]
    sub = ctx["workflows"][cfg["workflow"]]
    outdir = os.path.join(ctx["outdir"], job["id"])
    timeout = job.get("timeoutMs")
    r = job.get("retry", {})
    max_att, backoff, mult = r.get("maxAttempts", 1), r.get("backoffMs", 0), r.get("multiplier", 1)
    t = start
    starts = []
    for k in range(1, max_att + 1):
        starts.append(t)
        run = Run(sub, ctx["base"], outdir, ctx["workflows"], cancel_at=timeout, nested=True)
        run.simulate()
        if run.cancelled:
            end, kind = t + timeout, "timeout"
        else:
            end = t + run.T
            kind = "ok" if run.status() == "SUCCEEDED" else "subworkflow"
        if kind == "timeout" and k < max_att:
            t = end + backoff * mult ** (k - 1)
            continue
        o = Outcome(end, starts, kind == "ok", None, None if kind == "ok" else kind)
        o.subrun = run
        if kind == "ok":
            o.output = {jid: run.out[jid] for jid in run.order if run.st[jid] == "SUCCEEDED"}
        return o
    raise AssertionError


# ----------------------------------------------------------------------------- simulation
class Run:
    def __init__(self, wf, base, outdir, workflows, cancel_at=None, nested=False):
        self.wf = wf
        self.base = base
        self.outdir = outdir
        self.workflows = workflows
        self.jobs = {j["id"]: j for j in wf["jobs"]}
        self.order = [j["id"] for j in wf["jobs"]]
        self.cancel_at = cancel_at if nested else wf.get("cancelAfterMs")
        self.limit = wf.get("maxConcurrency", 4)
        self.groups = wf.get("groups", {})
        self.fail_fast = wf.get("onFailure", "continue") == "failFast"
        self.st = {j: "PENDING" for j in self.order}
        self.start = {j: None for j in self.order}
        self.end = {j: None for j in self.order}
        self.out = {j: None for j in self.order}
        self.plan = {}
        self.extra = {j: {} for j in self.order}
        self.cancelled = False
        self.T = 0

    def ctx(self):
        return {"base": self.base, "outdir": self.outdir, "workflows": self.workflows}

    def running(self):
        return [j for j in self.order if self.st[j] == "RUNNING"]

    def simulate(self):
        T = 0
        while True:
            self.T = T
            # 1. record completions at T
            newly_failed = False
            for j in self.running():
                p = self.plan[j]
                if p.end == T:
                    self.finish(j, p)
                    newly_failed |= self.st[j] == "FAILED"
            if all(self.st[j] in FINAL for j in self.order):
                return
            if self.cancel_at is not None and T >= self.cancel_at:
                self.cancelled = True
                self.abort(T)
                return
            if self.fail_fast and newly_failed:
                self.abort(T)
                return
            # 2. resolve
            changed = True
            while changed:
                changed = False
                for j in self.order:
                    if self.st[j] != "PENDING":
                        continue
                    deps = self.jobs[j].get("deps", [])
                    if not all(self.st[d] in FINAL for d in deps):
                        continue
                    bad = [d for d in deps if self.st[d] in ("FAILED", "BLOCKED", "CANCELLED", "NOT_RUN")]
                    if bad:
                        self.st[j], self.end[j] = "BLOCKED", T
                        roots = set()
                        for d in bad:
                            roots |= {d} if self.st[d] in ("FAILED", "CANCELLED") else set(self.extra[d].get("rootCause") or [])
                        self.extra[j] = {"blockedBy": bad[0], "rootCause": [x for x in self.order if x in roots]}
                        changed = True
                    elif any(self.st[d] == "SKIPPED" for d in deps):
                        self.st[j], self.end[j] = "SKIPPED", T
                        self.extra[j] = {"skipReason": "upstream-skipped"}
                        changed = True
                    elif "when" in self.jobs[j] and self.out[self.jobs[j]["when"]["job"]] != self.jobs[j]["when"]["equals"]:
                        self.st[j], self.end[j] = "SKIPPED", T
                        self.extra[j] = {"skipReason": "condition"}
                        changed = True
                    elif self.st[j] == "PENDING":
                        self.st[j] = "READY"
                        changed = True
            # 3. start
            started_zero = False
            for j in self.order:
                if self.st[j] != "READY":
                    continue
                run = self.running()
                if len(run) >= self.limit:
                    continue
                g = self.jobs[j].get("group")
                if g is not None and sum(1 for r in run if self.jobs[r].get("group") == g) >= self.groups[g]:
                    continue
                self.st[j] = "RUNNING"
                self.start[j] = T
                p = plan_job(self.jobs[j], T, self.out, self.st, self.ctx())
                if p.cls == "__defect__":
                    if p.end == T:
                        raise DefectStop(j)
                    p.cls = "__defect_pending__"
                self.plan[j] = p
                started_zero |= p.end == T
            if all(self.st[j] in FINAL for j in self.order):
                return
            if started_zero:
                continue
            nxt = min([self.plan[j].end for j in self.running()] + [INF])
            if self.cancel_at is not None:
                nxt = min(nxt, max(self.cancel_at, T))
            if nxt == INF:
                raise AssertionError("simulation stalled")
            if nxt == T:
                continue
            T = nxt

    def finish(self, j, p):
        if p.cls == "__defect_pending__":
            raise DefectStop(j)
        self.end[j] = p.end
        self.extra[j]["attempts"] = len(p.attempts_at)
        if p.subrun is not None:
            self.extra[j]["subreport"] = p.subrun.report()
        if p.ok:
            self.st[j] = "SUCCEEDED"
            self.out[j] = p.output
            for _, eff in p.effects:
                apply_effect(eff)
        else:
            self.st[j] = "FAILED"
            self.extra[j]["error"] = {"class": p.cls, "details": list(p.details)}
            if p.partial_output is not None:
                self.extra[j]["partial"] = p.partial_output

    def abort(self, T):
        for j in self.order:
            if self.st[j] == "RUNNING":
                p = self.plan[j]
                self.st[j], self.end[j] = "CANCELLED", T
                self.extra[j]["attempts"] = sum(1 for a in p.attempts_at if a <= T)
                self.extra[j]["error"] = {"class": "cancelled", "details": []}
                if p.subrun is not None or self.jobs[j]["kind"] == "subworkflow":
                    sub = Run(self.workflows[self.jobs[j]["config"]["workflow"]], self.base,
                              os.path.join(self.outdir, j), self.workflows,
                              cancel_at=T - max(a for a in p.attempts_at if a <= T), nested=True)
                    sub.simulate()
                    self.extra[j]["subreport"] = sub.report()
            elif self.st[j] not in FINAL:
                self.st[j], self.end[j] = "NOT_RUN", T
        self.T = T

    def status(self):
        if self.cancelled:
            return "CANCELLED"
        if all(self.st[j] in ("SUCCEEDED", "SKIPPED") for j in self.order):
            return "SUCCEEDED"
        return "FAILED"

    def report(self):
        jobs = []
        for j in self.order:
            st = self.st[j]
            e = self.extra[j]
            err_ = None
            if "error" in e:
                err_ = {"class": e["error"]["class"], "message": "", "details": e["error"]["details"]}
            out = self.out[j] if st == "SUCCEEDED" else e.get("partial")
            jobs.append({
                "id": j, "kind": self.jobs[j]["kind"], "status": st, "attempts": e.get("attempts", 0),
                "start": self.start[j], "end": self.end[j], "output": out, "error": err_,
                "blockedBy": e.get("blockedBy"), "rootCause": e.get("rootCause"),
                "skipReason": e.get("skipReason"), "subreport": e.get("subreport"),
            })
        summary = {s: sum(1 for j in self.order if self.st[j] == s) for s in STATUSES}
        return {"workflow": self.wf["workflow"], "status": self.status(), "durationMs": self.T,
                "cancelled": self.cancelled, "errors": [], "summary": summary, "jobs": jobs}


def apply_effect(eff):
    kind, outdir, name, text = eff
    p = Path(outdir) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def invalid_report(wf, errors):
    jobs = []
    if isinstance(wf, dict) and isinstance(wf.get("jobs"), list):
        for j in wf["jobs"]:
            if isinstance(j, dict) and isinstance(j.get("id"), str) and ID_RE.match(j["id"]):
                jobs.append({"id": j["id"], "kind": j.get("kind") if j.get("kind") in KINDS else None,
                             "status": "NOT_RUN", "attempts": 0, "start": None, "end": None, "output": None,
                             "error": None, "blockedBy": None, "rootCause": None, "skipReason": None,
                             "subreport": None})
    name = wf.get("workflow") if isinstance(wf, dict) and isinstance(wf.get("workflow"), str) else None
    summary = {s: 0 for s in STATUSES}
    summary["NOT_RUN"] = len(jobs)
    return {"workflow": name, "status": "INVALID", "durationMs": 0, "cancelled": False, "errors": errors,
            "summary": summary, "jobs": jobs}


def main(argv):
    wf_path, outdir = Path(argv[1]), Path(argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        wf = json.loads(wf_path.read_text(encoding="utf-8"))
        errors = validate(wf)
    except json.JSONDecodeError:
        wf, errors = None, [err("malformed", None, None, "invalid JSON")]
    if errors:
        rep = invalid_report(wf, errors)
        (outdir / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for e in errors:
            print(f"error {e['code']} {e['job'] if e['job'] is not None else '-'}")
        print(f"workflow {rep['workflow'] if rep['workflow'] is not None else '-'} INVALID")
        return 10
    run = Run(wf, str(wf_path.parent), str(outdir), wf.get("workflows", {}))
    try:
        run.simulate()
    except DefectStop:
        return 3
    rep = run.report()
    (outdir / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for j in rep["jobs"]:
        print(f"{j['id']} {j['status']}")
    print(f"workflow {rep['workflow']} {rep['status']}")
    return {"SUCCEEDED": 0, "FAILED": 11, "CANCELLED": 12}[rep["status"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
