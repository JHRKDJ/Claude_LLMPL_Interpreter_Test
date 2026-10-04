"""Source files and spans.

A Span is a half-open character range [start, end) inside one SourceFile.
Line/column numbers are 1-based and counted in Unicode code points.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass


class SourceFile:
    __slots__ = ("path", "text", "_line_starts", "module_name")

    def __init__(self, path: str, text: str, module_name: str | None = None):
        self.path = path
        self.text = text
        self.module_name = module_name
        starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                starts.append(i + 1)
        self._line_starts = starts

    def line_col(self, offset: int) -> tuple[int, int]:
        offset = max(0, min(offset, len(self.text)))
        line_index = bisect.bisect_right(self._line_starts, offset) - 1
        return line_index + 1, offset - self._line_starts[line_index] + 1

    def line_text(self, line: int) -> str:
        if line < 1 or line > len(self._line_starts):
            return ""
        start = self._line_starts[line - 1]
        end = self._line_starts[line] - 1 if line < len(self._line_starts) else len(self.text)
        return self.text[start:end]

    @property
    def line_count(self) -> int:
        return len(self._line_starts)

    def __repr__(self) -> str:
        return f"SourceFile({self.path!r})"


@dataclass(frozen=True, slots=True)
class Span:
    file: SourceFile
    start: int
    end: int

    @property
    def start_line_col(self) -> tuple[int, int]:
        return self.file.line_col(self.start)

    @property
    def end_line_col(self) -> tuple[int, int]:
        return self.file.line_col(self.end)

    @property
    def text(self) -> str:
        return self.file.text[self.start:self.end]

    def to(self, other: "Span | None") -> "Span":
        """Span covering self through other (same file)."""
        if other is None or other.file is not self.file:
            return self
        return Span(self.file, min(self.start, other.start), max(self.end, other.end))

    def describe(self) -> str:
        line, col = self.start_line_col
        return f"{self.file.path}:{line}:{col}"

    def to_json(self) -> dict:
        sl, sc = self.start_line_col
        el, ec = self.end_line_col
        return {
            "file": self.file.path,
            "start": {"line": sl, "column": sc, "offset": self.start},
            "end": {"line": el, "column": ec, "offset": self.end},
        }

    def __repr__(self) -> str:
        return f"Span({self.describe()}+{self.end - self.start})"


def synthetic_span(label: str = "<builtin>") -> Span:
    f = SourceFile(label, "")
    return Span(f, 0, 0)
