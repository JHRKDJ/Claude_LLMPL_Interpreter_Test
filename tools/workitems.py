#!/usr/bin/env python3
"""Work-item queue helper.

WORK_ITEMS.json is the durable store. Usage:
  python tools/workitems.py summary            # counts by state and prefix
  python tools/workitems.py list [STATE]       # list items (optionally by state)
  python tools/workitems.py set ID STATE [note]
  python tools/workitems.py add ID "title" [deps...]
"""
import json
import sys
from collections import Counter
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "WORK_ITEMS.json"
STATES = ["TODO", "IN_PROGRESS", "BLOCKED", "IMPLEMENTED", "VERIFYING", "DONE"]


def load():
    return json.loads(PATH.read_text())


def save(data):
    PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def main(argv):
    data = load()
    items = data["items"]
    cmd = argv[1] if len(argv) > 1 else "summary"
    if cmd == "summary":
        c = Counter(i["state"] for i in items)
        print(f"Work items: {c.get('DONE', 0)}/{len(items)} DONE")
        print("  " + ", ".join(f"{s}={c.get(s, 0)}" for s in STATES))
        pref = Counter()
        done = Counter()
        for i in items:
            p = i["id"].rsplit("-", 1)[0]
            pref[p] += 1
            if i["state"] == "DONE":
                done[p] += 1
        for p in sorted(pref):
            print(f"  {p:22s} {done[p]:3d}/{pref[p]:3d}")
    elif cmd == "list":
        want = argv[2] if len(argv) > 2 else None
        for i in items:
            if want is None or i["state"] == want:
                print(f"{i['id']:24s} {i['state']:12s} {i['title']}")
    elif cmd == "set":
        ident, state = argv[2], argv[3]
        assert state in STATES, state
        for i in items:
            if i["id"] == ident:
                i["state"] = state
                if len(argv) > 4:
                    i.setdefault("notes", []).append(" ".join(argv[4:]))
                break
        else:
            sys.exit(f"unknown id {ident}")
        save(data)
    elif cmd == "add":
        ident, title = argv[2], argv[3]
        if any(i["id"] == ident for i in items):
            sys.exit(f"duplicate id {ident}")
        items.append({"id": ident, "title": title, "state": "TODO", "deps": argv[4:]})
        save(data)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
