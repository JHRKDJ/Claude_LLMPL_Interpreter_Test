"""Seeded random program generator for formatter/parser property tests.

Produces syntactically valid programs with random (often redundant) parentheses,
random spacing and line breaks in continuation positions, and comments, so the
formatter's canonicalisation and comment handling are exercised."""
from __future__ import annotations

import random

BIN = ["+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">=", "&&", "||"]
PREC = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, "<=": 4, ">": 4, ">=": 4,
        "+": 7, "-": 7, "*": 8, "/": 8, "%": 8}
NAMES = ["a", "b", "count", "xs", "total", "item", "v"]


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.depth = 0

    def sp(self) -> str:
        return self.r.choice([" ", " ", " ", "  "])

    def name(self) -> str:
        return self.r.choice(NAMES)

    def atom(self) -> str:
        k = self.r.randrange(8)
        if k == 0:
            return str(self.r.randrange(0, 1000))
        if k == 1:
            return self.r.choice(["1.5", "0.25", "1_000", "3e2"])
        if k == 2:
            return '"' + self.r.choice(["hi", "a b", "{a}", "x\\n", ""]) + '"'
        if k == 3:
            return self.r.choice(["true", "false", "null", "()"])
        return self.name()

    def expr(self, prec: int = 0) -> str:
        self.depth += 1
        try:
            if self.depth > 4:
                return self.atom()
            k = self.r.randrange(14)
            if k <= 3:
                op = self.r.choice(BIN)
                p = PREC[op]
                left = self.expr(p + 1)
                right = self.expr(p + 1)
                s = f"{left}{self.sp()}{op}{self.r.choice([' ', chr(10) + '    '])}{right}"
                return f"({s})" if p < prec or self.r.random() < 0.15 else s
            if k == 4:
                inner = self.expr(9)
                op = self.r.choice(["-", "!"])
                if op == "-" and inner.startswith("-"):
                    inner = f"({inner})"
                return f"{op}{inner}"
            if k == 5:
                args = ", ".join(self.expr() for _ in range(self.r.randrange(0, 4)))
                return f"{self.name()}({args})"
            if k == 6:
                return f"{self.atom_postfix()}.{self.r.choice(['length', 'first()', 'get(0)', 'map(fn(x) => x)'])}"
            if k == 7:
                return f"{self.name()}[{self.expr()}]"
            if k == 8:
                return "[" + ", ".join(self.expr() for _ in range(self.r.randrange(0, 4))) + "]"
            if k == 9:
                return f"if {self.expr()} {{ {self.expr()} }} else {{ {self.expr()} }}"
            if k == 10:
                arms = "\n".join(f"        {self.r.choice(['1', '2', 'Some(q)', 'None', '_'])} => {self.expr()}"
                                 for _ in range(self.r.randrange(1, 4)))
                return f"match {self.name()} {{\n{arms}\n        _ => 0\n    }}"
            if k == 11:
                lam = f"fn(x: Int) => {self.expr()}"  # the `=>` body extends rightwards
                return f"({lam})" if prec > 0 else lam
            if k == 12:
                s = f"{self.atom()}..{self.atom()}"
                return f"({s})" if prec > 6 else s
            return f"({self.expr()}, {self.expr()})"
        finally:
            self.depth -= 1

    def atom_postfix(self) -> str:
        a = self.atom()
        return a if a[0].isalpha() and a not in ("true", "false", "null") else f"({a})"

    def comment(self) -> str:
        return self.r.choice(["// note", "/* inline */", "// TODO: check"])

    def stmt(self, ind: str) -> str:
        k = self.r.randrange(9)
        c = f"  {self.comment()}" if self.r.random() < 0.1 else ""
        if k == 0:
            return f"{ind}let {self.name()}{self.r.choice(['', ': Int'])} = {self.expr()}{c}"
        if k == 1:
            return f"{ind}{self.name()} {self.r.choice(['=', '+=', '-='])} {self.expr()}{c}"
        if k == 2:
            return f"{ind}if {self.expr()} {{\n{self.body(ind + '    ')}\n{ind}}}"
        if k == 3:
            return f"{ind}while {self.expr()} {{\n{self.body(ind + '    ')}\n{ind}}}"
        if k == 4:
            return f"{ind}for {self.name()} in {self.expr()} {{\n{self.body(ind + '    ')}\n{ind}}}"
        if k == 5:
            return f"{ind}return {self.expr()}{c}"
        if k == 6:
            return f"{ind}{self.comment()}"
        if k == 7:
            return ""
        return f"{ind}print({self.expr()}){c}"

    def body(self, ind: str) -> str:
        if len(ind) > 16:
            return f"{ind}print(1)"
        return "\n".join(self.stmt(ind) for _ in range(self.r.randrange(1, 4)))

    def program(self) -> str:
        decls = []
        for i in range(self.r.randrange(1, 4)):
            params = ", ".join(f"{n}: Int" for n in self.r.sample(NAMES, self.r.randrange(0, 3)))
            decls.append(f"fn f{i}({params}) {{\n{self.body('    ')}\n}}")
        if self.r.random() < 0.5:
            decls.insert(0, "record P { x: Int, y: Int }")
        if self.r.random() < 0.3:
            decls.insert(0, "// file header comment")
        return "\n\n".join(decls) + "\n"
