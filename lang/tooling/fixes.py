"""Apply visible fix patches (V3 2.4, 5.16.2, 7.13.7): only unambiguous known-import
insertions are applied automatically; everything else stays a suggestion."""
from __future__ import annotations

import difflib
from pathlib import Path


def apply_import_fixes(diags, write: bool = True, stream=None) -> int:
    edits_by_file: dict[str, list] = {}
    for d in diags:
        if d.stable_code != "S.NAME.UNRESOLVED" or len(d.fixes) != 1:
            continue
        for e in d.fixes[0].edits:
            edits_by_file.setdefault(e.span.file.path, []).append(e)
    count = 0
    for path, edits in edits_by_file.items():
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        seen = set()
        new = text
        for e in sorted(edits, key=lambda e: e.span.start, reverse=True):
            if e.replacement in seen:
                continue
            seen.add(e.replacement)
            new = new[:e.span.start] + e.replacement + new[e.span.end:]
            count += 1
        if write:
            p.write_text(new, encoding="utf-8")
        elif stream is not None:
            stream.writelines(difflib.unified_diff(text.splitlines(True), new.splitlines(True), path, path))
    return count
