#!/usr/bin/env python3
"""Generates s28_large.json: a deterministic layered DAG (test data, not source)."""
import json
import random
import sys


def generate(n_layers=20, width=25, seed=28):
    rng = random.Random(seed)
    jobs, layers = [], []
    for L in range(n_layers):
        layer = []
        for k in range(width):
            jid = f"L{L:02d}_{k:02d}"
            deps = sorted(rng.sample(layers[-1], min(len(layers[-1]), rng.randint(1, 3)))) if layers else []
            r = rng.random()
            if L > 0 and r < 0.15:
                job = {"id": jid, "kind": "reduce", "deps": deps, "config": {"op": "sum"}}
            elif r < 0.25:
                script = rng.choice([["ok"], ["retryable", "ok"], ["permanent"]]) if rng.random() < 0.2 else ["ok"]
                job = {"id": jid, "kind": "external", "deps": deps,
                       "config": {"latencyMs": rng.randint(1, 15), "script": script, "value": rng.randint(0, 9)},
                       "retry": {"maxAttempts": 2, "backoffMs": 1}}
            else:
                job = {"id": jid, "kind": "compute", "deps": deps,
                       "config": {"op": rng.choice(["fib", "sumTo"]), "n": rng.randint(0, 30), "costMs": rng.randint(0, 12)}}
            if rng.random() < 0.1:
                job["group"] = "narrow"
            jobs.append(job)
            layer.append(jid)
        layers.append(layer)
    return {"workflow": "large", "maxConcurrency": 16, "groups": {"narrow": 2}, "onFailure": "continue", "jobs": jobs}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "s28_large.json"
    open(out, "w").write(json.dumps(generate(), indent=1) + "\n")
