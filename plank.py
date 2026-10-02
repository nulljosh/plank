#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["llvmlite>=0.44"]
# ///
"""Plank: a small compiled language. Lexer, parser, codegen, one file.

    plank run hello.pk a b  compile and run, passing a and b to args()
    plank build hello.pk    native binary next to the source; --static for one you can copy to another Linux box
    plank emit hello.pk     print the LLVM IR
    plank test [dir]        run every .pk in dir (default tests/); each must print ok
    plank repl              type Plank a line at a time and see what it does
    plank fmt [--check] [files]   lay out .pk files the house way; --check only reports
"""
import os, platform, re, subprocess, sys, tempfile
from dataclasses import dataclass, field

from llvmlite import binding, ir

VERSION = "3.0.0"
TRIPLE = binding.get_default_triple()
if sys.platform == "darwin":  # the default triple names a darwin the linker has not heard of
    TRIPLE = f"{platform.machine()}-apple-macosx{platform.mac_ver()[0]}"


class PlankError(Exception):
    def __init__(self, line, msg):
        super().__init__(msg)
        self.line = line
        self.file = None


STRIDE = 1_000_000  # lines in the k-th source file are numbered from k * STRIDE, so one int says file and line


def locate(line, files):
    if line // STRIDE >= 900:
        return "<built-in " + ("Json" if line // STRIDE == 900 else "Set") + ">", line % STRIDE
    return files[min(line // STRIDE, len(files) - 1)], line % STRIDE


# ---------------------------------------------------------------- lexer
KEYWORDS = {"fn", "extern", "import", "try", "catch", "throw", "struct", "enum", "match", "nil", "let", "var", "if", "else", "while", "for", "in", "return",
            "break", "continue", "true", "false", "and", "or", "not"}
TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t\r]+) | (?P<comment>\#[^\n]*) | (?P<nl>\n) |
    (?P<float>\d+\.\d+(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+) | (?P<int>\d+) |
    (?P<name>[A-Za-z_]\w*) |
    (?P<op>\+=|-=|\*=|/=|%=|->|=>|\.\.|==|!=|<=|>=|\?\?|\?\.|[-+*/%<>=(){}\[\]:,.?!])
""", re.X)


@dataclass
class Tok:
    kind: str
    val: object
    line: int


ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "0": "\0"}


def close_paren(src, i, line):
    """Index just past the ) that closes an interpolation opened before i."""
    depth = 1
    while depth:
        if i >= len(src):
            raise PlankError(line, "\\( in a string needs a closing )")
        if src[i] == '"':
            i = string_end(src, i, line)
            continue
        depth += {"(": 1, ")": -1}.get(src[i], 0)
        i += 1
    return i


def string_end(src, i, line):
    """Index just past the closing quote of the string that opens at i."""
    i += 1
    while i < len(src) and src[i] != '"':
        if src[i] == "\\" and src[i + 1:i + 2] == "(":
            i = close_paren(src, i + 2, line)
        else:
            i += 2 if src[i] == "\\" else 1
    if i >= len(src):
        raise PlankError(line, "this string never ends, add a closing \"")
    return i + 1


def unescape(body, line):
    """Decode escapes. A string with \\(expr) in it comes back as a list of
    text and (source, line) pieces for the parser to stitch together."""
    parts, out, i = [], [], 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            i += 1
            if body[i] == "(":
                j = close_paren(body, i + 1, line)
                parts += ["".join(out), (body[i + 1:j - 1], line)]
                out, i = [], j
                continue
            if body[i] not in ESCAPES:
                raise PlankError(line, f"unknown escape \\{body[i]}")
            c = ESCAPES[body[i]]
        out.append(c)
        i += 1
    parts.append("".join(out))
    return parts[0] if len(parts) == 1 else parts


def lex(src, line=1, comments=None):
    toks, pos, depth = [], 0, 0
    while pos < len(src):
        if src[pos] == '"':
            end = string_end(src, pos, line)
            toks.append(Tok("str", unescape(src[pos + 1:end - 1], line), line))
            line += src.count("\n", pos, end)
            pos = end
            continue
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise PlankError(line, f"unexpected character {src[pos]!r}")
        kind, text = m.lastgroup, m.group()
        pos = m.end()
        if kind == "comment" and comments is not None:
            comments.append((line, text))
        if kind in ("ws", "comment"):
            continue
        if kind == "nl":
            if depth == 0:
                toks.append(Tok("nl", None, line))
            line += 1
        elif kind == "int":
            toks.append(Tok("int", int(text), line))
        elif kind == "float" and toks and toks[-1].kind == "." and "e" not in text.lower():
            a, b = text.split(".")  # t.0.1 is two tuple parts, not a float
            toks += [Tok("int", int(a), line), Tok(".", ".", line), Tok("int", int(b), line)]
        elif kind == "float":
            toks.append(Tok("float", float(text), line))
            toks[-1].text = text  # so plank fmt can print 1.5e3 the way it was written
        elif kind == "name":
            toks.append(Tok(text if text in KEYWORDS else "name", text, line))
        else:
            depth += (text in "([") - (text in ")]")
            toks.append(Tok(text, text, line))
    toks.append(Tok("nl", None, line))
    toks.append(Tok("eof", None, line))
    return toks


# ---------------------------------------------------------------- ast
@dataclass
class Node:
    line: int

@dataclass
class Num(Node): val: object; ty: str
@dataclass
class Str(Node): val: str
@dataclass
class Interp(Node): parts: list
@dataclass
class Bool(Node): val: bool
@dataclass
class Name(Node): name: str
@dataclass
class Unary(Node): op: str; expr: Node
@dataclass
class Unwrap(Node): expr: Node
@dataclass
class Nil(Node): pass
@dataclass
class Lambda(Node): params: list; ret: str; body: list   # ret None: worked out from the => expression
@dataclass
class CallValue(Node): target: Node; args: list
@dataclass
class IfLet(Node): name: str; expr: Node; then: list; other: list
@dataclass
class IfExpr(Node): cond: Node; then: Node; other: Node
@dataclass
class IfLetExpr(Node): name: str; expr: Node; then: Node; other: Node
@dataclass
class Binary(Node): op: str; left: Node; right: Node
@dataclass
class Call(Node): name: str; args: list; labels: list
@dataclass
class Let(Node): name: str; ty: str; expr: Node; mutable: bool
@dataclass
class LetTuple(Node): names: list; expr: Node; mutable: bool
@dataclass
class Tuple(Node): items: list
@dataclass
class Assign(Node): target: Node; expr: Node
@dataclass
class If(Node): cond: Node; then: list; other: list
@dataclass
class While(Node): cond: Node; body: list
@dataclass
class For(Node): name: str; start: Node; stop: Node; body: list
@dataclass
class ForIn(Node): name: str; items: Node; body: list; second: str = None
@dataclass
class WhileLet(Node): name: str; expr: Node; body: list
@dataclass
class List(Node): items: list
@dataclass
class Dict(Node): keys: list; vals: list
@dataclass
class Index(Node): target: Node; index: Node
@dataclass
class Slice(Node): target: Node; start: Node; stop: Node   # either end may be None
@dataclass
class Method(Node): target: Node; name: str; args: list; labels: list
@dataclass
class Field(Node): target: Node; name: str
@dataclass
class Return(Node): expr: Node
@dataclass
class Break(Node): pass
@dataclass
class Try(Node): body: list; name: str; handler: list
@dataclass
class Throw(Node): expr: Node
@dataclass
class Continue(Node): pass
@dataclass
class ExprStmt(Node): expr: Node
@dataclass
class Given(Node): val: object; ty: str   # an already-computed value, so match evaluates its subject once
@dataclass
class Fn(Node): name: str; params: list; ret: str; body: list; defaults: dict; tparams: list = None; extern: bool = False
@dataclass
class OptChain(Node): target: Node; name: str; args: list; labels: list   # args None for a field
@dataclass
class Import(Node): path: str; alias: str = None
@dataclass
class Struct(Node): name: str; fields: list; defaults: dict; methods: list; tparams: list = None
@dataclass
class Enum(Node): name: str; cases: list; methods: list
@dataclass
class Match(Node): subject: Node; arms: list; other: list


class Block(list):
    """A list of statements that remembers the line of its closing brace, so the formatter keeps comments inside."""
    end = 0


# ---------------------------------------------------------------- parser
PREC = {"or": 1, "and": 2, "in": 4, "??": 4.5, "==": 4, "!=": 4, "<": 4, ">": 4, "<=": 4, ">=": 4,
        "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}
TYPES = {"int", "float", "bool", "str"}


class Parser:
    def __init__(self, toks):
        self.toks, self.i = toks, 0
        self.aliases = set()  # import "x.pk" as x: x.Name is a type from there

    @property
    def tok(self):
        return self.toks[self.i]

    def at(self, *kinds):
        return self.tok.kind in kinds

    def next(self):
        t = self.tok
        self.i += 1
        return t

    def expect(self, kind):
        if not self.at(kind):
            got = self.tok.kind if self.tok.val is None else repr(self.tok.val)
            raise PlankError(self.tok.line, f"expected {kind!r}, got {got}")
        return self.next()

    def skip_nl(self):
        while self.at("nl"):
            self.next()

    def program(self):
        items = []
        self.skip_nl()
        while not self.at("eof"):
            if self.at("import"):
                line = self.next().line
                path = self.expect("str").val
                if not isinstance(path, str):
                    raise PlankError(line, "an import path is plain text, no \\( )")
                alias = None
                if self.at("name") and self.tok.val == "as":
                    self.next()
                    alias = self.expect("name").val
                    self.aliases.add(alias)
                items.append(Import(line, path, alias))
            elif self.at("extern"):
                self.next()
                f = self.fn(extern=True)
                items.append(f)
            else:
                items.append(self.struct() if self.at("struct") else self.enum() if self.at("enum") else self.fn())
            self.skip_nl()
        return items

    def type_name(self):
        name = self.expect("name")
        if not name.val[0].isupper():
            raise PlankError(name.line, f"type names start with a capital letter: {name.val.capitalize()}")
        return name.val

    def enum(self):
        line = self.expect("enum").line
        name = self.type_name()
        self.expect("{")
        cases, methods, case_lines = [], [], []
        self.skip_nl()
        while not self.at("}"):
            if self.at("fn"):
                methods.append(self.fn())
            else:
                case_tok = self.expect("name")
                case = case_tok.val
                case_lines.append(case_tok.line)
                fields = []
                if self.at("("):
                    self.next()
                    while not self.at(")"):
                        fname = self.expect("name").val
                        self.expect(":")
                        fields.append((fname, self.type()))
                        if not self.at(")"):
                            self.expect(",")
                    self.expect(")")
                cases.append((case, fields))
                if self.at(","):
                    self.next()
            self.skip_nl()
        end = self.expect("}").line
        en = Enum(line, name, cases, methods)
        en.end, en.case_lines = end, case_lines
        return en

    def match(self):
        line = self.expect("match").line
        subject = self.expr()
        self.expect("{")
        arms, other, arm_lines, else_line = [], None, [], 0
        self.skip_nl()
        while not self.at("}"):
            if self.at("else"):
                else_line = self.next().line
                other = self.block()
            else:
                arm_lines.append(self.tok.line)
                pats = [self.pattern()]
                while self.at(","):
                    self.next()
                    pats.append(self.pattern())
                arms.append((pats, self.block()))
            self.skip_nl()
        end = self.expect("}").line
        m = Match(line, subject, arms, other)
        m.end, m.arm_lines, m.else_line = end, arm_lines, else_line
        return m

    def match_expr(self, line):
        """match as a value: each arm is one expression. Built as a closure that returns from a match statement."""
        subject = self.expr()
        self.expect("{")
        arms, other, arm_lines, else_line = [], None, [], 0
        self.skip_nl()
        while not self.at("}"):
            if self.at("else"):
                else_line = self.next().line
                other = [Return(else_line, self.braced_expr())]
            else:
                arm_lines.append(self.tok.line)
                pats = [self.pattern()]
                while self.at(","):
                    self.next()
                    pats.append(self.pattern())
                arms.append((pats, [Return(line, self.braced_expr())]))
            self.skip_nl()
        end = self.expect("}").line
        m = Match(line, subject, arms, other)
        m.end, m.arm_lines, m.else_line = end, arm_lines, else_line
        return CallValue(line, Lambda(line, [], None, [m]), [])

    def pattern(self):
        """.case, .case(a, b) or a constant like 3 or "hi"."""
        if not self.at("."):
            return self.expr()
        self.next()
        case = self.expect("name").val
        names = []
        if self.at("("):
            self.next()
            while not self.at(")"):
                names.append(self.expect("name").val)
                if not self.at(")"):
                    self.expect(",")
            self.expect(")")
        return (case, names)

    def struct(self):
        line = self.expect("struct").line
        name = self.type_name()
        tparams = self.type_params()
        self.expect("{")
        fields, defaults, methods = [], {}, []
        self.skip_nl()
        while not self.at("}"):
            if self.at("fn"):
                methods.append(self.fn())
            else:
                fname = self.expect("name").val
                self.expect(":")
                fields.append((fname, self.type()))
                if self.at("="):
                    self.next()
                    defaults[fname] = self.expr()
                if self.at(","):
                    self.next()
            self.skip_nl()
        end = self.expect("}").line
        st = Struct(line, name, fields, defaults, methods, tparams)
        st.end = end
        return st

    def fn(self, extern=False):
        line = self.expect("fn").line
        name = self.expect("name").val
        tparams = self.type_params()
        self.expect("(")
        params, defaults = [], {}
        while not self.at(")"):
            pname = self.expect("name").val
            self.expect(":")
            params.append((pname, self.type()))
            if self.at("="):
                self.next()
                defaults[pname] = self.expr()
            if not self.at(")"):
                self.expect(",")
        self.expect(")")
        ret = "void"
        if self.at("->"):
            self.next()
            ret = self.type()
        if extern:  # a C function: a signature and no body
            if tparams or defaults:
                raise PlankError(line, "an extern fn takes no type parameters or defaults")
            return Fn(line, name, params, ret, [], {}, [], True)
        return Fn(line, name, params, ret, self.block(), defaults, tparams)

    def type_params(self):
        """<T, U> after a name, or nothing."""
        out = []
        if self.at("<"):
            self.next()
            while not self.at(">"):
                out.append(self.type_name())
                if not self.at(">"):
                    self.expect(",")
            self.expect(">")
        return out

    def type_args(self):
        """<int, [str]> after a type name: the full name, like Stack<int>."""
        self.expect("<")
        args = []
        while not self.at(">"):
            args.append(self.type())
            if not self.at(">"):
                self.expect(",")
        self.expect(">")
        return ", ".join(args)

    def type(self):
        if self.at("("):
            line = self.next().line
            parts = [self.type()]
            while self.at(","):
                self.next()
                parts.append(self.type())
            self.expect(")")
            if len(parts) < 2:
                raise PlankError(line, "a tuple type has at least two parts: (int, str)")
            return self.optional(f"({', '.join(parts)})")
        if self.at("fn"):
            self.next()
            self.expect("(")
            params = []
            while not self.at(")"):
                params.append(self.type())
                if not self.at(")"):
                    self.expect(",")
            self.expect(")")
            ret = "void"
            if self.at("->"):
                self.next()
                ret = self.type()
            return self.optional(f"fn({', '.join(params)}) -> {ret}")
        if self.at("["):
            self.next()
            inner = self.type()
            if self.at(":"):
                self.next()
                inner = f"{inner}: {self.type()}"
            self.expect("]")
            return self.optional(f"[{inner}]")
        t = self.expect("name")
        if t.val in self.aliases and self.at("."):  # money.Ledger
            self.next()
            inner = self.expect("name")
            if not inner.val[0].isupper():
                raise PlankError(inner.line, f"type names start with a capital letter: {t.val}.{inner.val.capitalize()}")
            return self.optional(f"{t.val}.{inner.val}" + (f"<{self.type_args()}>" if self.at("<") else ""))
        if t.val not in TYPES and not t.val[0].isupper():  # capitalized names are structs, checked in codegen
            raise PlankError(t.line, f"unknown type {t.val!r}")
        name = t.val
        if name[0].isupper() and self.at("<"):
            name = f"{name}<{self.type_args()}>"
        return self.optional(name)

    def optional(self, ty):
        while self.at("?", "??"):
            ty += self.next().kind
        return ty

    def block(self):
        self.expect("{")
        stmts = Block()
        self.skip_nl()
        while not self.at("}"):
            stmts.append(self.stmt())
            if not self.at("}"):
                self.expect("nl")
            self.skip_nl()
        stmts.end = self.expect("}").line
        return stmts

    def stmt(self):
        t = self.tok
        if self.at("let", "var"):
            self.next()
            if self.at("("):  # let (q, r) = divmod(7, 2)
                self.next()
                names = [self.expect("name").val]
                while self.at(","):
                    self.next()
                    names.append(self.expect("name").val)
                self.expect(")")
                self.expect("=")
                return LetTuple(t.line, names, self.expr(), t.kind == "var")
            name = self.expect("name").val
            ty = None
            if self.at(":"):
                self.next()
                ty = self.type()
            self.expect("=")
            return Let(t.line, name, ty, self.expr(), t.kind == "var")
        if self.at("if"):
            return self.if_()
        if self.at("match"):
            return self.match()
        if self.at("while"):
            self.next()
            if self.at("let"):
                self.next()
                name = self.expect("name").val
                self.expect("=")
                opt = self.expr()
                return WhileLet(t.line, name, opt, self.block())
            cond = self.expr()
            return While(t.line, cond, self.block())
        if self.at("for"):
            self.next()
            name = self.expect("name").val
            second = None
            if self.at(","):  # for i, x in xs / for k, v in d
                self.next()
                second = self.expect("name").val
            self.expect("in")
            start = self.expr()
            if not self.at(".."):
                return ForIn(t.line, name, start, self.block(), second)
            if second:
                raise PlankError(t.line, "a range gives one number at a time: for i in 0..n")
            self.next()
            stop = self.expr()
            return For(t.line, name, start, stop, self.block())
        if self.at("return"):
            self.next()
            return Return(t.line, None if self.at("nl", "}") else self.expr())
        if self.at("try"):
            self.next()
            body = self.block()
            self.skip_nl()
            self.expect("catch")
            name = self.expect("name").val
            return Try(t.line, body, name, self.block())
        if self.at("throw"):
            self.next()
            return Throw(t.line, self.expr())
        if self.at("break"):
            self.next()
            return Break(t.line)
        if self.at("continue"):
            self.next()
            return Continue(t.line)
        e = self.expr()
        if self.at("=", "+=", "-=", "*=", "/=", "%="):
            if not isinstance(e, (Name, Index, Field)):
                raise PlankError(t.line, "only a variable, xs[i] or p.x can go left of =")
            op = self.next().kind
            val = self.expr()
            # ponytail: xs[f()] += 1 evaluates f() twice; a temp slot if that ever matters
            return Assign(t.line, e, val if op == "=" else Binary(t.line, op[0], e, val))
        return ExprStmt(t.line, e)

    def if_(self):
        line = self.expect("if").line
        if self.at("let"):
            self.next()
            name = self.expect("name").val
            self.expect("=")
            cond = self.expr()
            then = self.block()
            return IfLet(line, name, cond, then, self.else_())
        cond = self.expr()
        then = self.block()
        return If(line, cond, then, self.else_())

    def if_expr(self, line):
        """if c { a } else { b } used as a value: each branch is one expression. if let works here too."""
        if self.at("let"):
            self.next()
            name = self.expect("name").val
            self.expect("=")
            opt = self.expr()
            then = self.braced_expr()
            self.skip_nl()
            if not self.at("else"):
                raise PlankError(line, "an if used as a value needs an else, so it always has one")
            self.next()
            other = self.if_expr(self.next().line) if self.at("if") else self.braced_expr()
            return IfLetExpr(line, name, opt, then, other)
        cond = self.expr()
        then = self.braced_expr()
        self.skip_nl()
        if not self.at("else"):
            raise PlankError(line, "an if used as a value needs an else, so it always has one")
        self.next()
        if self.at("if"):
            other = self.if_expr(self.next().line)
        else:
            other = self.braced_expr()
        return IfExpr(line, cond, then, other)

    def braced_expr(self):
        self.expect("{")
        self.skip_nl()
        e = self.expr()
        self.skip_nl()
        self.expect("}")
        return e

    def else_(self):
        other = []
        mark = self.i
        self.skip_nl()
        if not self.at("else"):
            self.i = mark
        else:
            start = self.next().line
            other = [self.if_()] if self.at("if") else self.block()
            if isinstance(other, Block):
                other.start = start  # the else line, so the formatter measures blank lines from it
        return other

    def expr(self, prec=0):
        left = self.unary()
        while self.tok.kind in PREC and PREC[self.tok.kind] > prec:
            op = self.next()
            left = Binary(op.line, op.val, left, self.expr(PREC[op.val]))
        return left

    def unary(self):
        t = self.tok
        if self.at("-"):
            self.next()
            return Unary(t.line, "-", self.unary())
        if self.at("not"):
            self.next()
            return Unary(t.line, "not", self.expr(3))
        return self.primary()

    def primary(self):
        e = self.atom()
        while self.at("[", ".", "!", "(", "?."):
            line = self.next().line
            if self.toks[self.i - 1].kind == "?.":  # p?.next?.val: nil if any link is nil
                name = self.expect("name").val
                if self.at("("):
                    self.next()
                    e = OptChain(line, e, name, *self.call_args())
                else:
                    e = OptChain(line, e, name, None, None)
                continue
            if self.toks[self.i - 1].kind == "(":
                e = CallValue(line, e, self.args(")"))
                continue
            if self.toks[self.i - 1].kind == "!":
                e = Unwrap(line, e)
                continue
            if self.toks[self.i - 1].kind == "[":
                start = None if self.at("..") else self.expr()
                if self.at(".."):
                    self.next()
                    stop = None if self.at("]") else self.expr()
                    e = Slice(line, e, start, stop)
                else:
                    e = Index(line, e, start)
                self.expect("]")
                continue
            tok = self.next()
            if tok.kind == "int":  # t.0, a tuple part
                name = f"_{tok.val}"
            elif tok.kind == "name":
                name = tok.val
            else:
                raise PlankError(tok.line, "expected a field or method name after .")
            if self.at("("):
                self.next()
                e = Method(line, e, name, *self.call_args())
                e.end = self.toks[self.i - 1].line
            else:
                e = Field(line, e, name)
        return e

    def lambda_(self, line):
        """fn(x: int) -> int { ... }, or fn(x) => x * 2 with the types worked out from where it goes."""
        self.expect("(")
        params = []
        while not self.at(")"):
            name = self.expect("name").val
            ty = None
            if self.at(":"):
                self.next()
                ty = self.type()
            params.append((name, ty))
            if not self.at(")"):
                self.expect(",")
        self.expect(")")
        if self.at("=>"):
            arrow = self.next()
            return Lambda(line, params, None, [Return(arrow.line, self.expr())])
        ret = None  # with no ->, the body says what it returns
        if self.at("->"):
            self.next()
            ret = self.type()
        return Lambda(line, params, ret, self.block())

    def call_args(self):
        """Arguments up to ), each optionally labeled: f(1, by: 2)."""
        args, labels, opened = [], [], self.toks[self.i - 1].line
        while not self.at(")"):
            label = None
            if self.at("name") and self.toks[self.i + 1].kind == ":":
                label = self.next().val
                self.next()
            elif any(labels):
                raise PlankError(self.tok.line, "once one argument has a label, the rest need one too")
            args.append(self.expr())
            labels.append(label)
            self.sep(")", opened)
        self.expect(")")
        return args, labels

    def args(self, close):
        out, opened = [], self.toks[self.i - 1].line
        while not self.at(close):
            out.append(self.expr())
            self.sep(close, opened)
        self.expect(close)
        return out

    def sep(self, close, opened):
        """After an item in (...) or [...]: a comma, the closer, or a clear error."""
        if self.at(","):
            self.next()
        elif not self.at(close):
            if self.at("}", "eof", "nl"):
                raise PlankError(self.tok.line, f"missing {close} for the {'(' if close == ')' else '['} opened on line {opened}")
            got = self.tok.kind if self.tok.val is None else repr(self.tok.val)
            raise PlankError(self.tok.line, f"expected , or {close} here, got {got}")

    def atom(self):
        t = self.next()
        if t.kind == "int":
            return Num(t.line, t.val, "int")
        if t.kind == "float":
            n = Num(t.line, t.val, "float")
            n.text = getattr(t, "text", None)
            return n
        if t.kind == "str":
            if isinstance(t.val, str):
                return Str(t.line, t.val)
            return Interp(t.line, [Str(t.line, p) if isinstance(p, str) else interp_expr(*p) for p in t.val])
        if t.kind == "nil":
            return Nil(t.line)
        if t.kind == "fn":
            return self.lambda_(t.line)
        if t.kind in ("true", "false"):
            return Bool(t.line, t.kind == "true")
        if t.kind == "(":
            e = self.expr()
            if self.at(","):  # (a, b): a tuple
                items = [e]
                while self.at(","):
                    self.next()
                    items.append(self.expr())
                self.expect(")")
                return Tuple(t.line, items)
            self.expect(")")
            return e
        if t.kind == "if":
            return self.if_expr(t.line)
        if t.kind == "match":
            return self.match_expr(t.line)
        if t.kind == "[":
            if self.at(":"):
                self.next()
                self.expect("]")
                return Dict(t.line, [], [])
            if self.at("]"):
                self.next()
                return List(t.line, [])
            first = self.expr()
            if not self.at(":"):
                if not self.at("]"):
                    self.expect(",")
                node = List(t.line, [first] + self.args("]"))
                node.end = self.toks[self.i - 1].line  # where the ] was, for the formatter
                return node
            keys, vals = [first], []
            while True:
                self.expect(":")
                vals.append(self.expr())
                if self.at("]"):
                    break
                self.expect(",")
                if self.at("]"):
                    break
                keys.append(self.expr())
            end = self.expect("]").line
            node = Dict(t.line, keys, vals)
            node.end = end
            return node
        if t.kind == "name":
            name = t.val
            if name[0].isupper() and self.at("<"):  # Stack<int>(...), as long as a ( follows the >
                mark = self.i
                try:
                    args = self.type_args()
                    if not self.at("("):
                        raise PlankError(t.line, "")
                    name = f"{name}<{args}>"
                except PlankError:
                    self.i = mark
            if self.at("("):
                self.next()
                node = Call(t.line, name, *self.call_args())
                node.end = self.toks[self.i - 1].line
                return node
            return Name(t.line, t.val)
        if t.kind in ("nl", "eof"):
            raise PlankError(t.line, "this line ends in the middle of an expression")
        got = t.kind if t.val is None else repr(t.val)
        raise PlankError(t.line, f"unexpected {got}")


def interp_expr(src, line):
    p = Parser([Tok(t.kind, t.val, line) for t in lex(src)])
    e = p.expr()
    if not p.at("nl"):
        raise PlankError(line, f"cannot read \\({src}) as one expression")
    return e


# ---------------------------------------------------------------- formatter
def span_end(node):
    """The last source line a node touches, closing braces included."""
    def ends(v):
        if isinstance(v, Block):
            yield v.end
        if isinstance(v, (list, tuple)):
            for x in v:
                yield from ends(x)
    end = getattr(node, "end", 0)
    for n in walk(node):
        end = max(end, n.line, getattr(n, "end", 0))
        for f in n.__dataclass_fields__:
            end = max([end] + list(ends(getattr(n, f))))
    return end


def quote(text):
    out = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t").replace("\0", "\\0")
    return '"' + out + '"'


class Fmt:
    """Source back out of the AST, laid out like the examples. Comments and single blank lines survive by line number."""
    UNARY = 7

    def __init__(self, comments):
        self.comments = sorted(comments)
        self.lines = []

    def program(self, items):
        prev = 0
        for it in items:
            if prev:
                self.lines.append("")
            prev = self.leading(it.line, 0, prev, gap=False)
            self.item(it, 0)
            prev = span_end(it)
        self.leading(10 ** 9, 0, prev)
        return "\n".join(self.lines).rstrip("\n") + "\n"

    # -- comments and blank lines
    def leading(self, line, indent, prev, gap=True):
        """Emit every comment that sits before line; keep one blank line where the source had any. Returns the new prev."""
        while self.comments and self.comments[0][0] < line:
            l, text = self.comments.pop(0)
            if gap and prev and l - prev > 1:
                self.lines.append("")
            self.lines.append(" " * indent + text)
            prev = l
        if gap and prev and line - prev > 1 and line < 10 ** 9:
            self.lines.append("")
        return prev

    def trail(self, line):
        if self.comments and self.comments[0][0] == line:
            return "  " + self.comments.pop(0)[1]
        return ""

    def emit(self, indent, text, line):
        self.lines.append(" " * indent + text + self.trail(line))

    # -- declarations
    def item(self, it, indent):
        if isinstance(it, Import):
            return self.emit(indent, f'import {quote(it.path)}' + (f" as {it.alias}" if it.alias else ""), it.line)
        if isinstance(it, Fn):
            return self.fn(it, indent)
        head = f"{'struct' if isinstance(it, Struct) else 'enum'} {it.name}{self.tparams(it.tparams if isinstance(it, Struct) else None)} {{"
        self.emit(indent, head, it.line)
        prev = it.line
        if isinstance(it, Struct):
            for name, ty in it.fields:
                default = f" = {self.expr(it.defaults[name], indent + 2)}" if name in it.defaults else ""
                self.lines.append(" " * (indent + 2) + f"{name}: {ty}{default}")
        else:
            row, row_line = [], None
            for (case, fields), cl in zip(it.cases, getattr(it, "case_lines", [0] * len(it.cases))):
                inner = ", ".join(f"{n}: {t}" for n, t in fields)
                text = case + (f"({inner})" if fields else "")
                if row and cl != row_line:  # cases that shared a line in the source stay together
                    self.lines.append(" " * (indent + 2) + ", ".join(row))
                    row = []
                row.append(text)
                row_line = cl
            if row:
                self.lines.append(" " * (indent + 2) + ", ".join(row))
        for m in it.methods:
            if m.line - prev <= 1:  # always one blank line before a method, never two
                self.lines.append("")
            prev = self.leading(m.line, indent + 2, prev)
            self.fn(m, indent + 2)
            prev = span_end(m)
        self.leading(it.end, indent + 2, prev, gap=False)
        self.lines.append(" " * indent + "}")

    def tparams(self, tparams):
        return f"<{', '.join(tparams)}>" if tparams else ""

    def params(self, f, indent):
        out = []
        for name, ty in f.params:
            defaults = getattr(f, "defaults", {})  # lambdas have none
            default = f" = {self.expr(defaults[name], indent)}" if name in defaults else ""
            out.append(f"{name}: {ty}{default}" if ty else name)
        return ", ".join(out)

    def fn(self, f, indent):
        ret = f" -> {f.ret}" if f.ret and f.ret != "void" else ""
        if f.extern:
            return self.emit(indent, f"extern fn {f.name}({self.params(f, indent)}){ret}", f.line)
        self.emit(indent, f"fn {f.name}{self.tparams(f.tparams)}({self.params(f, indent)}){ret} {{", f.line)
        self.block(f.body, indent + 2, f.line)
        self.lines.append(" " * indent + "}")

    # -- statements
    def block(self, stmts, indent, opened):
        prev = opened
        for st in stmts:
            prev = self.leading(st.line, indent, prev)
            self.stmt(st, indent)
            prev = span_end(st)
        self.leading(getattr(stmts, "end", 0) or prev, indent, prev, gap=False)

    def inline_block(self, stmts, line):
        """`{ stmt }` on one line, when the source had it that way and it is one simple statement."""
        if not stmts:
            return "{ }"
        if len(stmts) == 1 and stmts[0].line == line and span_end(stmts[0]) == line and not isinstance(stmts[0], (If, IfLet, While, WhileLet, For, ForIn, Try, Match)):
            keep = self.lines
            self.lines = []
            self.stmt(stmts[0], 0)
            text, self.lines = self.lines[0], keep
            return "{ " + text + " }"
        return None

    def body(self, stmts, indent, head, line, tail=""):
        one = self.inline_block(stmts, line)
        if one is not None:
            self.emit(indent, head + " " + one + tail, line)
            return True
        self.emit(indent, head + " {", line)
        self.block(stmts, indent + 2, line)
        self.lines.append(" " * indent + "}" + tail)
        return False

    def stmt(self, s, indent):
        e = lambda x: self.expr(x, indent)
        if isinstance(s, LetTuple):
            return self.emit(indent, f"{'var' if s.mutable else 'let'} ({', '.join(s.names)}) = {e(s.expr)}", s.line)
        if isinstance(s, Let):
            ty = f": {s.ty}" if s.ty else ""
            return self.emit(indent, f"{'var' if s.mutable else 'let'} {s.name}{ty} = {e(s.expr)}", s.line)
        if isinstance(s, Assign):
            if isinstance(s.expr, Binary) and s.expr.left is s.target and s.expr.op in "+-*/%":
                return self.emit(indent, f"{e(s.target)} {s.expr.op}= {e(s.expr.right)}", s.line)
            return self.emit(indent, f"{e(s.target)} = {e(s.expr)}", s.line)
        if isinstance(s, ExprStmt):
            return self.emit(indent, e(s.expr), s.line)
        if isinstance(s, Return):
            return self.emit(indent, "return" + (f" {e(s.expr)}" if s.expr is not None else ""), s.line)
        if isinstance(s, Throw):
            return self.emit(indent, f"throw {e(s.expr)}", s.line)
        if isinstance(s, Break):
            return self.emit(indent, "break", s.line)
        if isinstance(s, Continue):
            return self.emit(indent, "continue", s.line)
        if isinstance(s, (If, IfLet)):
            return self.if_(s, indent, "if")
        if isinstance(s, While):
            return self.body(s.body, indent, f"while {e(s.cond)}", s.line)
        if isinstance(s, WhileLet):
            return self.body(s.body, indent, f"while let {s.name} = {e(s.expr)}", s.line)
        if isinstance(s, For):
            return self.body(s.body, indent, f"for {s.name} in {e(s.start)}..{e(s.stop)}", s.line)
        if isinstance(s, ForIn):
            names = s.name + (f", {s.second}" if s.second else "")
            return self.body(s.body, indent, f"for {names} in {e(s.items)}", s.line)
        if isinstance(s, Try):
            self.emit(indent, "try {", s.line)
            self.block(s.body, indent + 2, s.line)
            self.lines.append(" " * indent + f"}} catch {s.name} {{")
            self.block(s.handler, indent + 2, getattr(s.body, "end", s.line))
            return self.lines.append(" " * indent + "}")
        if isinstance(s, Match):
            return self.match(s, indent)
        raise PlankError(s.line, f"plank fmt does not know how to print {type(s).__name__}")

    def if_(self, s, indent, word):
        e = lambda x: self.expr(x, indent)
        head = f"{word} let {s.name} = {e(s.expr)}" if isinstance(s, IfLet) else f"{word} {e(s.cond)}"
        if not s.other:
            return self.body(s.then, indent, head, s.line)
        if span_end(s) == s.line:
            whole = self.inline_if(s)
            if whole is not None:
                return self.emit(indent, whole, s.line)
        one = self.inline_block(s.then, s.line)
        other_one = self.inline_block(s.other, s.line) if not (len(s.other) == 1 and isinstance(s.other[0], (If, IfLet))) else None
        if one is not None and other_one is not None:
            return self.emit(indent, f"{head} {one} else {other_one}", s.line)
        self.emit(indent, head + " {", s.line)
        self.block(s.then, indent + 2, s.line)
        if len(s.other) == 1 and isinstance(s.other[0], (If, IfLet)):
            self.lines.append(" " * indent + "} else " + "")
            self.lines[-1] = self.lines[-1].rstrip()
            keep = len(self.lines)
            self.if_(s.other[0], indent, "if")
            self.lines[keep - 1] += " " + self.lines[keep].strip()
            del self.lines[keep]
            return
        self.lines.append(" " * indent + "} else {")
        self.block(s.other, indent + 2, getattr(s.other, "start", 0) or getattr(s.then, "end", s.line))
        self.lines.append(" " * indent + "}")

    def inline_if(self, s):
        """A whole if / else if / else chain as one line, or None if any part cannot be inline."""
        head = f"if let {s.name} = {self.expr(s.expr)}" if isinstance(s, IfLet) else f"if {self.expr(s.cond)}"
        then = self.inline_block(s.then, s.line)
        if then is None:
            return None
        if not s.other:
            return f"{head} {then}"
        if len(s.other) == 1 and isinstance(s.other[0], (If, IfLet)):
            rest = self.inline_if(s.other[0])
            return None if rest is None else f"{head} {then} else {rest}"
        other = self.inline_block(s.other, s.line)
        return None if other is None else f"{head} {then} else {other}"

    def pattern(self, pat, indent):
        if isinstance(pat, tuple):
            case, names = pat
            return "." + case + (f"({', '.join(names)})" if names else "")
        return self.expr(pat, indent)

    def match(self, m, indent, as_value=False):
        self.emit(indent, f"match {self.expr(m.subject, indent)} {{", m.line)
        prev = m.line
        arms = list(m.arms) + ([(None, m.other)] if m.other is not None else [])
        lines = list(getattr(m, "arm_lines", [])) + ([getattr(m, "else_line", 0)] if m.other is not None else [])
        for (pats, body), line in zip(arms, lines + [0] * len(arms)):
            line = line or (body[0].line if body else prev)
            prev = self.leading(line, indent + 2, prev)
            head = "else" if pats is None else ", ".join(self.pattern(p, indent + 2) for p in pats)
            if as_value:
                self.lines.append(" " * (indent + 2) + f"{head} {{ {self.expr(body[0].expr, indent + 2)} }}")
            else:
                self.body(body, indent + 2, head, line)
            prev = max([prev, getattr(body, "end", 0)] + [span_end(st) for st in body])
        self.leading(getattr(m, "end", 0) or prev, indent + 2, prev, gap=False)
        self.lines.append(" " * indent + "}")

    # -- expressions: strings, with parentheses only where the tree needs them
    def prec(self, x):
        if isinstance(x, Binary):
            return PREC[x.op]
        if isinstance(x, Unary):
            return self.UNARY
        return 100

    def wrap(self, x, indent, limit):
        text = self.expr(x, indent)
        return f"({text})" if self.prec(x) < limit or isinstance(x, (IfExpr, IfLetExpr, Lambda)) or self.is_match_value(x) else text

    def atom(self, x, indent):
        text = self.expr(x, indent)
        return f"({text})" if isinstance(x, (Binary, Unary, IfExpr, IfLetExpr, Lambda)) or self.is_match_value(x) else text

    def is_match_value(self, x):
        return (isinstance(x, CallValue) and not x.args and isinstance(x.target, Lambda) and not x.target.params
                and x.target.ret is None and len(x.target.body) == 1 and isinstance(x.target.body[0], Match))

    def args(self, args, labels, indent):
        inner = indent + 2 if len(args) > 1 and args[0].line != args[-1].line else indent  # one big argument sits at the call's own level
        parts = [f"{l}: {self.expr(a, inner)}" if l else self.expr(a, inner) for a, l in zip(args, labels or [None] * len(args))]
        if len(args) > 1 and args[0].line != args[-1].line:  # the source spread them out
            return "\n" + ",\n".join(" " * (indent + 2) + p for p in parts) + ",\n" + " " * indent
        return ", ".join(parts)

    def expr(self, x, indent=0):
        if isinstance(x, Num):
            return (getattr(x, "text", None) or repr(x.val)) if x.ty == "float" else str(x.val)
        if isinstance(x, Str):
            return quote(x.val)
        if isinstance(x, Interp):
            out = '"'
            for part in x.parts:
                out += quote(part.val)[1:-1] if isinstance(part, Str) else f"\\({self.expr(part, indent)})"
            return out + '"'
        if isinstance(x, Bool):
            return "true" if x.val else "false"
        if isinstance(x, Nil):
            return "nil"
        if isinstance(x, Name):
            return x.name
        if isinstance(x, Tuple):
            return "(" + ", ".join(self.expr(i, indent) for i in x.items) + ")"
        if isinstance(x, Unary):
            inner = self.wrap(x.expr, indent, self.UNARY if x.op == "-" else 100)  # not (a in b) keeps its parens
            return ("-" + inner) if x.op == "-" else ("not " + inner)
        if isinstance(x, Binary):
            p = PREC[x.op]
            def side(child, limit):
                keep = isinstance(child, Binary) and (child.op == "??" or (x.op == "or" and child.op == "and") or (x.op == "in" and child is x.left))
                return self.wrap(child, indent, 100 if keep else limit)
            return f"{side(x.left, p)} {x.op} {side(x.right, p + 0.5)}"
        if isinstance(x, Call):
            return f"{x.name}({self.args(x.args, x.labels, indent)})"
        if isinstance(x, CallValue):
            if self.is_match_value(x):
                m = x.target.body[0]
                if span_end(m) == m.line:  # written on one line, printed on one line
                    arms = [(", ".join(self.pattern(p, indent) for p in pats), body[0].expr) for pats, body in m.arms]
                    if m.other is not None:
                        arms.append(("else", m.other[0].expr))
                    inner = " ".join(f"{head} {{ {self.expr(e, indent)} }}" for head, e in arms)
                    return f"match {self.expr(m.subject, indent)} {{ {inner} }}"
                keep, self.lines = self.lines, []
                self.match(m, indent, as_value=True)
                text, self.lines = "\n".join(self.lines).strip(), keep
                return text
            return f"{self.atom(x.target, indent)}({self.args(x.args, None, indent)})"
        if isinstance(x, Method):
            return f"{self.atom(x.target, indent)}.{x.name}({self.args(x.args, x.labels, indent)})"
        if isinstance(x, OptChain):
            call = f"({self.args(x.args, x.labels, indent)})" if x.args is not None else ""
            return f"{self.atom(x.target, indent)}?.{x.name}{call}"
        if isinstance(x, Field):
            name = x.name[1:] if re.fullmatch(r"_\d+", x.name) else x.name
            return f"{self.atom(x.target, indent)}.{name}"
        if isinstance(x, Index):
            return f"{self.atom(x.target, indent)}[{self.expr(x.index, indent)}]"
        if isinstance(x, Slice):
            a = self.expr(x.start, indent) if x.start is not None else ""
            b = self.expr(x.stop, indent) if x.stop is not None else ""
            return f"{self.atom(x.target, indent)}[{a}..{b}]"
        if isinstance(x, Unwrap):
            return f"{self.atom(x.expr, indent)}!"
        if isinstance(x, List):
            return f"[{self.args(x.items, None, indent)}]" if x.items else "[]"
        if isinstance(x, Dict):
            if not x.keys:
                return "[:]"
            pairs = [f"{self.expr(k, indent + 2)}: {self.expr(v, indent + 2)}" for k, v in zip(x.keys, x.vals)]
            if len(pairs) > 1 and x.keys[0].line != x.keys[-1].line:
                return "[\n" + ",\n".join(" " * (indent + 2) + p for p in pairs) + ",\n" + " " * indent + "]"
            return "[" + ", ".join(pairs) + "]"
        if isinstance(x, IfExpr):
            return f"if {self.expr(x.cond, indent)} {{ {self.expr(x.then, indent)} }} else {{ {self.expr(x.other, indent)} }}".replace("else { if ", "else if ").replace(" } }", " }") if isinstance(x.other, (IfExpr, IfLetExpr)) else f"if {self.expr(x.cond, indent)} {{ {self.expr(x.then, indent)} }} else {{ {self.expr(x.other, indent)} }}"
        if isinstance(x, IfLetExpr):
            return f"if let {x.name} = {self.expr(x.expr, indent)} {{ {self.expr(x.then, indent)} }} else {{ {self.expr(x.other, indent)} }}"
        if isinstance(x, Lambda):
            head = f"fn({self.params(x, indent)})"
            if x.ret is None and len(x.body) == 1 and isinstance(x.body[0], Return) and x.body[0].expr is not None and x.body[0].line == x.line:
                return f"{head} => {self.expr(x.body[0].expr, indent)}"
            ret = f" -> {x.ret}" if x.ret and x.ret != "void" else ""
            keep, self.lines = self.lines, []
            self.block(x.body, indent + 2, x.line)
            inner, self.lines = "\n".join(self.lines), keep
            return f"{head}{ret} {{\n{inner}\n{' ' * indent}}}"
        raise PlankError(x.line, f"plank fmt does not know how to print {type(x).__name__}")


def format_source(src):
    comments = []
    items = Parser(lex(src, comments=comments)).program()
    return Fmt(comments).program(items)


def fmt_files(args):
    """plank fmt [--check] [files]: rewrite .pk files in the house layout, or with --check just say which would change."""
    import glob
    check = "--check" in args
    paths = [a for a in args if a != "--check"] or sorted(glob.glob("**/*.pk", recursive=True))
    changed = 0
    for path in paths:
        with open(path) as f:
            src = f.read()
        try:
            text = format_source(src)
            again = format_source(text)
        except PlankError as err:
            print(f"{path}:{err.line % STRIDE}: {err}", file=sys.stderr)
            return 1
        if again != text:
            print(f"{path}: plank fmt is not stable on this file, this is a Plank bug", file=sys.stderr)
            return 1
        if text != src:
            changed += 1
            if check:
                print(path)
            else:
                with open(path, "w") as f:
                    f.write(text)
                print("formatted", path)
    if check and changed:
        print(f"{changed} file{'s' * (changed != 1)} would change; run plank fmt", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------- runtime
# The handful of things LLVM does not hand you: joining strings, reading a
# line, turning numbers into text. Compiled by cc next to your program.
RUNTIME = r"""
#define _GNU_SOURCE 1
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <setjmp.h>
#include <time.h>
#include <unistd.h>
#include <sys/wait.h>
#include <regex.h>
#include <dirent.h>
#include <sys/stat.h>

/* try blocks form a stack; a panic with a try open jumps to it instead of exiting */
typedef struct PkTry { jmp_buf jb; struct PkTry *prev; } PkTry;
static PkTry *pk_try_top;
static const char *pk_caught_msg = "";

void *pk_try_push(void) {
    PkTry *t = malloc(sizeof *t);
    t->prev = pk_try_top;
    pk_try_top = t;
    return t->jb;
}

void pk_try_pop(void) { PkTry *t = pk_try_top; pk_try_top = t->prev; free(t); }

const char *pk_caught(void) { return pk_caught_msg; }

void pk_panic(const char *file, long long line, const char *msg) {
    if (pk_try_top) {
        PkTry *t = pk_try_top;
        pk_try_top = t->prev;
        pk_caught_msg = msg;
        longjmp(t->jb, 1);  /* t stays allocated: its jmp_buf is in use; one small leak per catch */
    }
    fflush(stdout);
    fprintf(stderr, "%s:%lld: %s\n", file, line, msg);
    exit(1);
}

/* ---- memory: a conservative mark and sweep collector.
   Every allocation gets a 16-byte header holding its slot in a table of blocks. A collection starts
   from the stack, the registers (spilled by setjmp) and the open try frames, treats every word that
   points into a block as a reference, follows them, and frees the blocks nothing reached. It never
   moves anything, so the pointers LLVM keeps in registers stay valid. Strings are marked atomic:
   their bytes are text, not pointers, so they are never scanned. */
typedef struct { size_t idx, pad; } PkHdr;
typedef struct { char *p; size_t n; unsigned char mark, atomic; } PkBlock;

static PkBlock *pk_blocks;
static size_t pk_nblocks, pk_capblocks;
static size_t *pk_order, *pk_marks, pk_nmarks, pk_capmarks;
static size_t pk_since, pk_min = 8u << 20, pk_limit = 8u << 20;
static int pk_fixed_limit, pk_hold;  /* pk_hold: a runtime helper is mid-work with pointers only in C locals, do not collect */
static char *pk_stack_base;

void pk_collect(void);
static void pk_oom(void) { fputs("plank: out of memory\n", stderr); exit(1); }

static void *pk_new(size_t n, int atomic) {
    if (pk_since >= pk_limit && !pk_hold) pk_collect();
    PkHdr *h = calloc(1, sizeof *h + n);
    if (!h) pk_oom();
    if (pk_nblocks == pk_capblocks) {
        pk_capblocks = pk_capblocks ? pk_capblocks * 2 : 1024;
        pk_blocks = realloc(pk_blocks, pk_capblocks * sizeof *pk_blocks);
        if (!pk_blocks) pk_oom();
    }
    h->idx = pk_nblocks;
    pk_blocks[pk_nblocks++] = (PkBlock){(char *)(h + 1), n, 0, (unsigned char)atomic};
    pk_since += n + sizeof *h;
    return h + 1;
}

void *pk_alloc(long long n) { return pk_new(n, 0); }
void *pk_alloc_text(long long n) { return pk_new(n, 1); }

/* grow a block in place in the table; the new tail is zeroed */
static void *pk_grow(void *p, size_t n) {
    PkHdr *h = (PkHdr *)p - 1;
    size_t i = h->idx, old = pk_blocks[i].n;
    PkHdr *r = realloc(h, sizeof *h + n);
    if (!r) pk_oom();
    if (n > old) memset((char *)(r + 1) + old, 0, n - old);
    pk_blocks[i].p = (char *)(r + 1);
    pk_blocks[i].n = n;
    pk_since += n > old ? n - old : 0;
    return r + 1;
}

static int pk_by_addr(const void *a, const void *b) {
    char *x = pk_blocks[*(const size_t *)a].p, *y = pk_blocks[*(const size_t *)b].p;
    return x < y ? -1 : x > y;
}

/* the block holding addr, or -1. One past the end counts, so a pointer that walked off an array still keeps it. */
static long pk_block_at(char *addr) {
    long lo = 0, hi = (long)pk_nblocks - 1, hit = -1;
    while (lo <= hi) {
        long mid = (lo + hi) / 2;
        if (pk_blocks[pk_order[mid]].p <= addr) { hit = mid; lo = mid + 1; } else hi = mid - 1;
    }
    if (hit < 0) return -1;
    PkBlock *b = &pk_blocks[pk_order[hit]];
    return addr <= b->p + b->n ? (long)pk_order[hit] : -1;
}

static void pk_mark_word(char *w) {
    long i = pk_block_at(w);
    if (i < 0 || pk_blocks[i].mark) return;
    pk_blocks[i].mark = 1;
    if (pk_blocks[i].atomic) return;
    if (pk_nmarks == pk_capmarks) {
        pk_capmarks = pk_capmarks ? pk_capmarks * 2 : 4096;
        pk_marks = realloc(pk_marks, pk_capmarks * sizeof *pk_marks);
        if (!pk_marks) pk_oom();
    }
    pk_marks[pk_nmarks++] = i;
}

static void pk_scan(char *lo, char *hi) {
    lo = (char *)(((size_t)lo + 7) & ~(size_t)7);
    for (; lo + 8 <= hi; lo += 8) pk_mark_word(*(char **)lo);
}

static void pk_collect_from(char *sp) {
    pk_order = realloc(pk_order, (pk_nblocks + 1) * sizeof *pk_order);
    if (!pk_order) pk_oom();
    for (size_t i = 0; i < pk_nblocks; i++) pk_order[i] = i;
    qsort(pk_order, pk_nblocks, sizeof *pk_order, pk_by_addr);
    pk_scan(sp, pk_stack_base);
    for (PkTry *t = pk_try_top; t; t = t->prev) pk_scan((char *)t->jb, (char *)t->jb + sizeof t->jb);
    pk_mark_word((char *)pk_caught_msg);
    while (pk_nmarks) {
        PkBlock *b = &pk_blocks[pk_marks[--pk_nmarks]];
        pk_scan(b->p, b->p + b->n);
    }
    size_t keep = 0, live = 0;
    for (size_t i = 0; i < pk_nblocks; i++) {
        PkBlock b = pk_blocks[i];
        if (b.mark) {
            b.mark = 0;
            pk_blocks[keep] = b;
            ((PkHdr *)b.p - 1)->idx = keep++;
            live += b.n;
        } else {
            free((PkHdr *)b.p - 1);
        }
    }
    pk_nblocks = keep;
    pk_since = 0;
    if (!pk_fixed_limit) pk_limit = live > pk_min ? live : pk_min;  /* collect again once as much new has piled up as survived */
}

__attribute__((noinline)) void pk_collect(void) {
    if (pk_hold) { fputs("plank: collector guard unbalanced, this is a Plank bug\n", stderr); abort(); }
    jmp_buf regs;  /* setjmp spills the callee-saved registers into regs, where the stack scan finds them */
    setjmp(regs);
    pk_collect_from((char *)regs);
}

void pk_gc_init(char **argv) {
    pk_stack_base = (char *)argv;
    const char *knob = getenv("PLANK_GC");  /* a byte count: collect every that-many bytes, to shake out bugs */
    if (knob && atoll(knob) > 0) { pk_min = pk_limit = (size_t)atoll(knob); pk_fixed_limit = 1; }
}

char *pk_concat(const char *a, const char *b) {
    pk_hold++;
    size_t x = strlen(a), y = strlen(b);
    char *r = pk_alloc_text(x + y + 1);
    memcpy(r, a, x);
    memcpy(r + x, b, y + 1);
    pk_hold--; return r;
}

/* length in characters, not bytes: count every byte that does not continue a UTF-8 sequence */
long long pk_len(const char *s) {
    long long n = 0;
    for (; *s; s++) n += ((unsigned char)*s & 0xC0) != 0x80;
    return n;
}

char *pk_str_int(long long v) { char *r = pk_alloc_text(24); snprintf(r, 24, "%lld", v); return r; }
char *pk_str_float(double v) { char *r = pk_alloc_text(32); snprintf(r, 32, "%.15g", v); return r; }

static const char *pk_number_end(const char *e) { while (isspace((unsigned char)*e)) e++; return e; }

long long pk_parse_int(const char *s, const char *file, long long line) {
    char *e;
    long long v = strtoll(s, &e, 10);
    if (e == s || *pk_number_end(e)) pk_panic(file, line, "int() got text that is not a whole number");
    return v;
}

double pk_parse_float(const char *s, const char *file, long long line) {
    char *e;
    double v = strtod(s, &e);
    if (e == s || *pk_number_end(e)) pk_panic(file, line, "float() got text that is not a number");
    return v;
}

/* One list shape for every element type. The compiler knows the type, the runtime only the size. */
typedef struct { long long len, cap; char *data; } PkList;

PkList *pk_list_new(long long cap, long long size) {
    PkList *l = pk_alloc(sizeof *l);
    l->len = 0;
    l->cap = cap > 4 ? cap : 4;
    l->data = pk_alloc(l->cap * size);
    return l;
}

/* room for one more at the end; the caller stores the value */
void *pk_list_push(PkList *l, long long size) {
    if (l->len == l->cap) {
        l->cap *= 2;
        l->data = pk_grow(l->data, l->cap * size);
    }
    return l->data + size * l->len++;
}

void *pk_list_pop(PkList *l, long long size, const char *file, long long line) {
    if (!l->len) pk_panic(file, line, "pop() on an empty list");
    return l->data + size * --l->len;
}

/* Dicts keep insertion order, like Python: entries in arrays, an open-addressing index on top.
   Keys are 8 bytes, an int or a string pointer; values are 8-byte slots. */
typedef struct { long long len, cap, mask, isstr; long long *keys, *vals, *index; } PkDict;

static unsigned long long pk_hash(PkDict *d, long long k) {
    unsigned long long h = 1469598103934665603ULL;
    if (!d->isstr) return ((unsigned long long)k * 0x9E3779B97F4A7C15ULL) >> 7;
    for (const unsigned char *c = (const unsigned char *)k; *c; c++) h = (h ^ *c) * 1099511628211ULL;
    return h;
}

static int pk_same(PkDict *d, long long a, long long b) {
    return d->isstr ? strcmp((char *)a, (char *)b) == 0 : a == b;
}

PkDict *pk_dict_new(long long isstr) {
    PkDict *d = pk_alloc(sizeof *d);
    d->len = 0; d->cap = 8; d->mask = 15; d->isstr = isstr;
    d->keys = pk_alloc(8 * d->cap);
    d->vals = pk_alloc(8 * d->cap);
    d->index = pk_alloc_text((d->mask + 1) * 8);  /* just numbers, nothing to scan */
    return d;
}

/* the index cell for key: entry number + 1, or 0 where the key would go */
static long long *pk_probe(PkDict *d, long long key) {
    unsigned long long i = pk_hash(d, key) & d->mask;
    while (d->index[i] && !pk_same(d, d->keys[d->index[i] - 1], key)) i = (i + 1) & d->mask;
    return &d->index[i];
}

static void pk_reindex(PkDict *d) {
    d->index = pk_alloc_text((d->mask + 1) * 8);
    for (long long e = 0; e < d->len; e++) *pk_probe(d, d->keys[e]) = e + 1;
}

static void pk_missing(PkDict *d, long long key, const char *file, long long line) {
    static char msg[160];
    if (d->isstr) snprintf(msg, sizeof msg, "key \"%.100s\" is not in this dict", (char *)key);
    else snprintf(msg, sizeof msg, "key %lld is not in this dict", key);
    pk_panic(file, line, msg);
}

/* every call that takes a key says what kind it is, so an empty [:] learns its kind on first use */
long long *pk_dict_put(PkDict *d, long long key, long long isstr) {
    d->isstr = isstr;
    long long *cell = pk_probe(d, key);
    if (*cell) return &d->vals[*cell - 1];
    if (d->len == d->cap) {
        d->cap *= 2;
        d->keys = pk_grow(d->keys, 8 * d->cap);
        d->vals = pk_grow(d->vals, 8 * d->cap);
    }
    d->keys[d->len] = key;
    d->vals[d->len] = 0;
    *cell = ++d->len;
    if (d->len * 2 > d->mask) { d->mask = d->mask * 2 + 1; pk_reindex(d); }
    return &d->vals[d->len - 1];
}

long long *pk_dict_find(PkDict *d, long long key, long long isstr) {
    d->isstr = isstr;
    long long e = *pk_probe(d, key);
    return e ? &d->vals[e - 1] : 0;
}

long long *pk_dict_get(PkDict *d, long long key, long long isstr, const char *file, long long line) {
    long long *v = pk_dict_find(d, key, isstr);
    if (!v) pk_missing(d, key, file, line);
    return v;
}

long long pk_dict_len(PkDict *d) { return d->len; }

/* ponytail: O(n), shifts the entries down and rebuilds the index; tombstones if big dicts churn */
void pk_dict_remove(PkDict *d, long long key, long long isstr, const char *file, long long line) {
    d->isstr = isstr;
    long long e = *pk_probe(d, key);
    if (!e) pk_missing(d, key, file, line);
    memmove(&d->keys[e - 1], &d->keys[e], 8 * (d->len - e));
    memmove(&d->vals[e - 1], &d->vals[e], 8 * (d->len - e));
    d->len--;
    pk_reindex(d);
}

PkList *pk_dict_keys(PkDict *d) {
    pk_hold++;
    PkList *l = pk_list_new(d->len, 8);
    memcpy(l->data, d->keys, 8 * d->len);
    l->len = d->len;
    pk_hold--; return l;
}

PkList *pk_dict_values(PkDict *d, long long size) {
    pk_hold++;
    PkList *l = pk_list_new(d->len, size);
    for (long long e = 0; e < d->len; e++) memcpy(l->data + e * size, &d->vals[e], size);
    l->len = d->len;
    pk_hold--; return l;
}

long long pk_list_find(PkList *l, long long size, long long bits, long long isstr) {
    for (long long i = 0; i < l->len; i++) {
        char *at = l->data + i * size;
        if (isstr ? strcmp(*(char **)at, (char *)bits) == 0 : memcmp(at, &bits, size) == 0) return i;
    }
    return -1;
}

PkList *pk_list_copy(PkList *l, long long size) {
    pk_hold++;
    PkList *r = pk_list_new(l->len, size);
    memcpy(r->data, l->data, size * l->len);
    r->len = l->len;
    pk_hold--; return r;
}

/* stable merge sort; less(env, a, b) says whether a goes before b */
typedef long long (*PkLess)(void *, void *, void *);

static void pk_merge(char *a, char *tmp, long long n, long long size, PkLess less, void *env) {
    if (n < 2) return;
    long long h = n / 2, i = 0, j = h, k = 0;
    pk_merge(a, tmp, h, size, less, env);
    pk_merge(a + h * size, tmp, n - h, size, less, env);
    while (i < h && j < n) {
        if (less(env, a + j * size, a + i * size)) memcpy(tmp + size * k++, a + size * j++, size);
        else memcpy(tmp + size * k++, a + size * i++, size);
    }
    while (i < h) memcpy(tmp + size * k++, a + size * i++, size);
    while (j < n) memcpy(tmp + size * k++, a + size * j++, size);
    memcpy(a, tmp, size * n);
}

void pk_list_sort(PkList *l, long long size, PkLess less, void *env) {
    char *tmp = malloc(size * (l->len ? l->len : 1));  /* plain malloc: every item stays in l->data until the merge ends */
    if (!tmp) pk_oom();
    pk_merge(l->data, tmp, l->len, size, less, env);
    free(tmp);
}

/* ---- strings: UTF-8 in, characters counted as code points */
static long long pk_skip(const char *s, long long n) {  /* byte offset of character n */
    const char *p = s;
    while (*p && n > 0) { p++; while (((unsigned char)*p & 0xC0) == 0x80) p++; n--; }
    return p - s;
}

static char *pk_strndup(const char *s, long long n) {
    pk_hold++;
    char *r = pk_alloc_text(n + 1);
    memcpy(r, s, n);
    r[n] = 0;
    pk_hold--; return r;
}

static void pk_clamp(long long len, long long *a, long long *b) {
    if (*a < 0) *a += len;
    if (*b < 0) *b += len;
    if (*a < 0) *a = 0;
    if (*b > len) *b = len;
    if (*a > *b) *a = *b;
}

char *pk_str_slice(const char *s, long long a, long long b) {
    pk_hold++;
    pk_clamp(pk_len(s), &a, &b);
    long long from = pk_skip(s, a);
    { void *pk_r = (void *)(pk_strndup(s + from, pk_skip(s + from, b - a))); pk_hold--; return pk_r; }
}

char *pk_char_at(const char *s, long long i, const char *file, long long line) {
    pk_hold++;
    long long n = pk_len(s), at = i < 0 ? i + n : i;
    if (at < 0 || at >= n) {
        static char msg[96];
        snprintf(msg, sizeof msg, "index %lld is out of range for a string of %lld", i, n);
        pk_panic(file, line, msg);
    }
    { void *pk_r = (void *)(pk_str_slice(s, at, at + 1)); pk_hold--; return pk_r; }
}

PkList *pk_chars(const char *s) {
    pk_hold++;
    PkList *l = pk_list_new(pk_len(s), 8);
    while (*s) {
        long long n = pk_skip(s, 1);
        *(char **)pk_list_push(l, 8) = pk_strndup(s, n);
        s += n;
    }
    pk_hold--; return l;
}

PkList *pk_split(const char *s, const char *sep) {
    pk_hold++;
    PkList *l = pk_list_new(4, 8);
    size_t k = strlen(sep);
    if (!k) {  /* no separator: split on runs of whitespace, like Python */
        while (*s) {
            while (*s && isspace((unsigned char)*s)) s++;
            const char *start = s;
            while (*s && !isspace((unsigned char)*s)) s++;
            if (s > start) *(char **)pk_list_push(l, 8) = pk_strndup(start, s - start);
        }
        pk_hold--; return l;
    }
    for (const char *hit; (hit = strstr(s, sep)); s = hit + k)
        *(char **)pk_list_push(l, 8) = pk_strndup(s, hit - s);
    *(char **)pk_list_push(l, 8) = pk_strndup(s, strlen(s));
    pk_hold--; return l;
}

char *pk_join(PkList *l, const char *sep) {
    pk_hold++;
    size_t n = 1, k = strlen(sep);
    char **items = (char **)l->data;
    for (long long i = 0; i < l->len; i++) n += strlen(items[i]) + k;
    char *r = pk_alloc_text(n), *p = r;
    for (long long i = 0; i < l->len; i++) {
        if (i) { memcpy(p, sep, k); p += k; }
        size_t m = strlen(items[i]);
        memcpy(p, items[i], m);
        p += m;
    }
    *p = 0;
    pk_hold--; return r;
}

char *pk_trim(const char *s) {
    pk_hold++;
    while (isspace((unsigned char)*s)) s++;
    size_t n = strlen(s);
    while (n && isspace((unsigned char)s[n - 1])) n--;
    { void *pk_r = (void *)(pk_strndup(s, n)); pk_hold--; return pk_r; }
}

char *pk_case(const char *s, long long upper) {
    pk_hold++;  /* ASCII letters only; other characters pass through */
    char *r = pk_strndup(s, strlen(s));
    for (char *p = r; *p; p++) *p = upper ? toupper((unsigned char)*p) : tolower((unsigned char)*p);
    pk_hold--; return r;
}

char *pk_replace(const char *s, const char *a, const char *b) {
    pk_hold++;
    if (!*a) return pk_strndup(s, strlen(s));
    PkList *parts = pk_split(s, a);
    { void *pk_r = (void *)(pk_join(parts, b)); pk_hold--; return pk_r; }
}

long long pk_find(const char *s, const char *x) {
    pk_hold++;
    const char *hit = strstr(s, x);
    long long at = hit ? pk_len(pk_strndup(s, hit - s)) : -1;
    pk_hold--;
    return at;
}

long long pk_starts(const char *s, const char *p) { return strncmp(s, p, strlen(p)) == 0; }

long long pk_ends(const char *s, const char *p) {
    size_t n = strlen(s), k = strlen(p);
    return k <= n && strcmp(s + n - k, p) == 0;
}

char *pk_fixed(double v, long long digits) {
    pk_hold++;
    char *r = pk_alloc_text(64);
    snprintf(r, 64, "%.*f", (int)(digits < 0 ? 0 : digits > 30 ? 30 : digits), v);
    pk_hold--; return r;
}

PkList *pk_list_slice(PkList *l, long long size, long long a, long long b) {
    pk_hold++;
    pk_clamp(l->len, &a, &b);
    PkList *r = pk_list_new(b - a, size);
    memcpy(r->data, l->data + a * size, (b - a) * size);
    r->len = b - a;
    pk_hold--; return r;
}

void pk_sleep(double seconds) {
    if (seconds <= 0) return;
    struct timespec t = { (time_t)seconds, (long)((seconds - (time_t)seconds) * 1e9) };
    nanosleep(&t, 0);
}

/* ---- regular expressions: POSIX extended, from the C library. One compiled pattern is cached. */
static regex_t *pk_re(const char *pat, const char *file, long long line) {
    static regex_t re;
    static char last[512];
    static int have;
    if (have && !strcmp(last, pat)) return &re;
    if (have) { regfree(&re); have = 0; }
    int err = regcomp(&re, pat, REG_EXTENDED);
    if (err) {
        static char msg[256];
        char why[160];
        regerror(err, &re, why, sizeof why);
        snprintf(msg, sizeof msg, "bad pattern \"%.60s\": %s", pat, why);
        pk_panic(file, line, msg);
    }
    snprintf(last, sizeof last, "%s", pat);
    have = strlen(pat) < sizeof last;
    return &re;
}

long long pk_matches(const char *s, const char *pat, const char *file, long long line) {
    return regexec(pk_re(pat, file, line), s, 0, 0, 0) == 0;
}

/* the whole match and every group, or NULL when the pattern does not match */
PkList *pk_captures(const char *s, const char *pat, const char *file, long long line) {
    regex_t *re = pk_re(pat, file, line);
    regmatch_t m[16];
    if (regexec(re, s, 16, m, 0)) return 0;
    pk_hold++;
    size_t n = re->re_nsub + 1 < 16 ? re->re_nsub + 1 : 16;
    PkList *l = pk_list_new(n, 8);
    for (size_t i = 0; i < n; i++)
        *(char **)pk_list_push(l, 8) = m[i].rm_so < 0 ? "" : pk_strndup(s + m[i].rm_so, m[i].rm_eo - m[i].rm_so);
    pk_hold--;
    return l;
}

PkList *pk_find_all(const char *s, const char *pat, const char *file, long long line) {
    regex_t *re = pk_re(pat, file, line);
    pk_hold++;
    PkList *l = pk_list_new(4, 8);
    regmatch_t m;
    int flags = 0;
    while (*s && regexec(re, s, 1, &m, flags) == 0) {
        *(char **)pk_list_push(l, 8) = pk_strndup(s + m.rm_so, m.rm_eo - m.rm_so);
        s += m.rm_eo > 0 ? m.rm_eo : 1;
        flags = REG_NOTBOL;
    }
    pk_hold--;
    return l;
}

char *pk_replace_all(const char *s, const char *pat, const char *rep, const char *file, long long line) {
    regex_t *re = pk_re(pat, file, line);
    pk_hold++;
    size_t cap = strlen(s) * 2 + strlen(rep) * 4 + 16, n = 0, k = strlen(rep);
    char *out = pk_alloc_text(cap);
    regmatch_t m;
    int flags = 0;
    while (*s && regexec(re, s, 1, &m, flags) == 0) {
        size_t keep = m.rm_so, step = m.rm_eo > 0 ? m.rm_eo : 1;
        if (n + keep + k + 2 > cap) { cap = (cap + keep + k) * 2; out = pk_grow(out, cap); }
        memcpy(out + n, s, keep); n += keep;
        memcpy(out + n, rep, k); n += k;
        if (m.rm_eo == 0) out[n++] = *s;  /* an empty match: copy one character so we move on */
        s += step;
        flags = REG_NOTBOL;
    }
    size_t rest = strlen(s);
    if (n + rest + 1 > cap) out = pk_grow(out, n + rest + 1);
    memcpy(out + n, s, rest + 1);
    pk_hold--;
    return out;
}

/* ---- files and folders, the clock, urls */
long long pk_exists(const char *path) { struct stat st; return stat(path, &st) == 0; }
long long pk_is_dir(const char *path) { struct stat st; return stat(path, &st) == 0 && S_ISDIR(st.st_mode); }
long long pk_mkdir(const char *path) { return mkdir(path, 0755) == 0 || pk_is_dir(path); }
long long pk_remove_file(const char *path) { return remove(path) == 0; }
char *pk_cwd(void) { char buf[4096]; return pk_strndup(getcwd(buf, sizeof buf) ? buf : "", strlen(getcwd(buf, sizeof buf) ? buf : "")); }

static int pk_by_name(const void *a, const void *b) { return strcmp(*(char *const *)a, *(char *const *)b); }

/* the names inside a folder, sorted, without . and .. ; empty when the folder cannot be read */
PkList *pk_list_dir(const char *path) {
    pk_hold++;
    PkList *l = pk_list_new(8, 8);
    DIR *d = opendir(path);
    if (d) {
        struct dirent *e;
        while ((e = readdir(d)))
            if (strcmp(e->d_name, ".") && strcmp(e->d_name, ".."))
                *(char **)pk_list_push(l, 8) = pk_strndup(e->d_name, strlen(e->d_name));
        closedir(d);
        qsort(l->data, l->len, 8, pk_by_name);
    }
    pk_hold--;
    return l;
}

long long pk_append_file(const char *path, const char *text) {
    FILE *f = fopen(path, "ab");
    if (!f) return 0;
    int ok = fputs(text, f) >= 0;
    return fclose(f) == 0 && ok;
}

char *pk_clock(const char *fmt, double at, long long given) {
    time_t when = given ? (time_t)at : time(0);
    char buf[256];
    size_t n = strftime(buf, sizeof buf, *fmt ? fmt : "%Y-%m-%d %H:%M:%S", localtime(&when));
    return pk_strndup(buf, n);
}

/* text to seconds since 1970, by a strftime layout; -1 when the text does not fit it */
double pk_parse_time(const char *text, const char *fmt) {
    struct tm tm = {0};
    tm.tm_isdst = -1;
    const char *end = strptime(text, *fmt ? fmt : "%Y-%m-%d", &tm);
    if (!end || *end) return -1;
    return (double)mktime(&tm);
}

char *pk_url_encode(const char *s) {
    pk_hold++;
    char *r = pk_alloc_text(strlen(s) * 3 + 1), *q = r;
    for (; *s; s++) {
        unsigned char c = *s;
        if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') *q++ = c;
        else q += sprintf(q, "%%%02X", c);
    }
    *q = 0;
    pk_hold--;
    return r;
}

/* ---- the outside world: arguments, files, the clock, randomness */
static int pk_argc;
static char **pk_argv;
void pk_set_args(int argc, char **argv) { pk_argc = argc; pk_argv = argv; pk_gc_init(argv); }

PkList *pk_args(void) {
    pk_hold++;
    PkList *l = pk_list_new(pk_argc, 8);
    for (int i = 1; i < pk_argc; i++) *(char **)pk_list_push(l, 8) = pk_argv[i];
    pk_hold--; return l;
}

static char *pk_slurp(FILE *f) {
    size_t cap = 4096, n = 0, got;
    pk_hold++;
    char *buf = pk_alloc_text(cap);
    while ((got = fread(buf + n, 1, cap - n - 1, f)) > 0) {
        n += got;
        if (cap - n < 2) { cap *= 2; buf = pk_grow(buf, cap); }
    }
    buf[n] = 0;
    pk_hold--;
    return buf;
}

char *pk_read_file(const char *path) {
    pk_hold++;
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    char *text = pk_slurp(f);
    fclose(f);
    pk_hold--; return text;
}

char *pk_read_stdin(void) { return pk_slurp(stdin); }

/* ---- shell: run a command through /bin/sh, hand back its output and exit code */
typedef struct { char *out; long long code; } PkRun;
static PkRun pk_last_run;

char *pk_run(const char *cmd) {
    pk_hold++;
    FILE *f = popen(cmd, "r");
    if (!f) { pk_last_run.code = 127; return ""; }
    char *out = pk_slurp(f);
    int st = pclose(f);
    pk_last_run.code = st == -1 ? 127 : WIFEXITED(st) ? WEXITSTATUS(st) : 128 + WTERMSIG(st);
    pk_hold--; return out;
}

long long pk_run_code(void) { return pk_last_run.code; }

/* shell-quote one argument so run("ls " + quote(name)) is safe with any name */
char *pk_quote(const char *s) {
    pk_hold++;
    size_t n = strlen(s), extra = 0;
    for (const char *p = s; *p; p++) extra += *p == '\'' ? 3 : 0;
    char *r = pk_alloc_text(n + extra + 3), *q = r;
    *q++ = '\'';
    for (const char *p = s; *p; p++) {
        if (*p == '\'') { memcpy(q, "'\\''", 4); q += 4; }
        else *q++ = *p;
    }
    *q++ = '\'';
    *q = 0;
    pk_hold--; return r;
}

/* ---- http: curl does the networking; the body comes back, the status is in pk_last_run.code.
   ponytail: one process per request; a libcurl binding when someone needs keep-alive. */
char *pk_http(const char *method, const char *url, const char *body, PkList *headers) {
    pk_hold++;
    size_t cap = 512 + strlen(url) + strlen(body) * 2;
    for (long long i = 0; i < headers->len; i++) cap += strlen(((char **)headers->data)[i]) * 2 + 8;
    char *cmd = malloc(cap), *q = cmd;
    q += sprintf(q, "curl -s -S -L -X %s -w '\\n%%{http_code}' ", method);
    for (long long i = 0; i < headers->len; i++) q += sprintf(q, "-H %s ", pk_quote(((char **)headers->data)[i]));
    if (*body) q += sprintf(q, "--data-binary %s ", pk_quote(body));
    q += sprintf(q, "%s 2>&1", pk_quote(url));
    char *out = pk_run(cmd);
    free(cmd);
    if (pk_last_run.code) return out;  /* curl itself failed: its message is the body, code is nonzero */
    char *nl = strrchr(out, '\n');
    if (nl) { pk_last_run.code = atoll(nl + 1); *nl = 0; }
    pk_hold--; return out;
}

/* ---- JSON text: escape a string for output, and a cursor for parsing */
char *pk_json_quote(const char *s) {
    pk_hold++;
    size_t n = 2;
    for (const char *p = s; *p; p++) n += (*p == '"' || *p == '\\' || (unsigned char)*p < 0x20) ? 6 : 1;
    char *r = pk_alloc_text(n + 1), *q = r;
    *q++ = '"';
    for (const char *p = s; *p; p++) {
        unsigned char c = *p;
        if (c == '"' || c == '\\') { *q++ = '\\'; *q++ = c; }
        else if (c == '\n') { *q++ = '\\'; *q++ = 'n'; }
        else if (c == '\t') { *q++ = '\\'; *q++ = 't'; }
        else if (c == '\r') { *q++ = '\\'; *q++ = 'r'; }
        else if (c < 0x20) q += sprintf(q, "\\u%04x", c);
        else *q++ = c;
    }
    *q++ = '"';
    *q = 0;
    pk_hold--; return r;
}

static const char *pk_jp;  /* the parse cursor */
static const char *pk_jfile;
static long long pk_jline;

static void pk_jfail(const char *what) {
    static char msg[96];
    snprintf(msg, sizeof msg, "bad JSON: %s", what);
    pk_panic(pk_jfile, pk_jline, msg);
}

static void pk_jws(void) { while (*pk_jp == ' ' || *pk_jp == '\n' || *pk_jp == '\t' || *pk_jp == '\r') pk_jp++; }

/* kinds: 0 null 1 bool 2 number 3 string 4 array-open 5 object-open, 6 close, 7 comma, 8 colon */
long long pk_json_next(void) { pk_jws(); return *pk_jp; }

long long pk_json_bool(void) {
    if (!strncmp(pk_jp, "true", 4)) { pk_jp += 4; return 1; }
    if (!strncmp(pk_jp, "false", 5)) { pk_jp += 5; return 0; }
    pk_jfail("expected true or false");
    return 0;
}

void pk_json_null(void) { if (strncmp(pk_jp, "null", 4)) pk_jfail("expected a value, got n"); pk_jp += 4; }

double pk_json_number(void) {
    char *e;
    double v = strtod(pk_jp, &e);
    if (e == pk_jp) pk_jfail("expected a number");
    pk_jp = e;
    return v;
}

static void pk_utf8(char **q, unsigned cp) {
    if (cp < 0x80) *(*q)++ = cp;
    else if (cp < 0x800) { *(*q)++ = 0xC0 | cp >> 6; *(*q)++ = 0x80 | (cp & 0x3F); }
    else if (cp < 0x10000) { *(*q)++ = 0xE0 | cp >> 12; *(*q)++ = 0x80 | (cp >> 6 & 0x3F); *(*q)++ = 0x80 | (cp & 0x3F); }
    else { *(*q)++ = 0xF0 | cp >> 18; *(*q)++ = 0x80 | (cp >> 12 & 0x3F); *(*q)++ = 0x80 | (cp >> 6 & 0x3F); *(*q)++ = 0x80 | (cp & 0x3F); }
}

char *pk_json_string(void) {
    pk_hold++;
    if (*pk_jp != '"') pk_jfail("expected a string");
    pk_jp++;
    char *r = pk_alloc_text(strlen(pk_jp) + 1), *q = r;
    while (*pk_jp && *pk_jp != '"') {
        if (*pk_jp != '\\') { *q++ = *pk_jp++; continue; }
        pk_jp++;
        char c = *pk_jp++;
        if (c == 'n') *q++ = '\n'; else if (c == 't') *q++ = '\t'; else if (c == 'r') *q++ = '\r';
        else if (c == 'b') *q++ = '\b'; else if (c == 'f') *q++ = '\f';
        else if (c == 'u') {
            unsigned cp = (unsigned)strtoul((char[]){pk_jp[0], pk_jp[1], pk_jp[2], pk_jp[3], 0}, 0, 16);
            pk_jp += 4;
            if (cp >= 0xD800 && cp < 0xDC00 && pk_jp[0] == '\\' && pk_jp[1] == 'u') {  /* surrogate pair */
                unsigned lo = (unsigned)strtoul((char[]){pk_jp[2], pk_jp[3], pk_jp[4], pk_jp[5], 0}, 0, 16);
                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                pk_jp += 6;
            }
            pk_utf8(&q, cp);
        }
        else if (c == '"' || c == '\\' || c == '/') *q++ = c;
        else pk_jfail("unknown escape in a string");
    }
    if (*pk_jp != '"') pk_jfail("a string never ends");
    pk_jp++;
    *q = 0;
    pk_hold--; return r;
}

void pk_json_expect(long long c) {
    pk_jws();
    if (c == 'v') pk_jfail(*pk_jp ? "expected a value" : "the text ends in the middle of a value");
    if (*pk_jp != c) {
        static char m[48];
        snprintf(m, sizeof m, *pk_jp ? "expected %c, got %c" : "expected %c before the end", (char)c, *pk_jp);
        pk_jfail(m);
    }
    pk_jp++;
}

void pk_json_begin(const char *text, const char *file, long long line) { pk_jp = text; pk_jfile = file; pk_jline = line; }
void pk_json_end(void) { pk_jws(); if (*pk_jp) pk_jfail("extra text after the value"); }

long long pk_write_file(const char *path, const char *text) {
    FILE *f = fopen(path, "wb");
    if (!f) return 0;
    int ok = fputs(text, f) >= 0;
    return fclose(f) == 0 && ok;
}

void pk_exit(long long code) { fflush(stdout); exit((int)code); }

char *pk_env(const char *name) { return getenv(name); }

double pk_time(void) {
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

static unsigned long long pk_seed;
static unsigned long long pk_next(void) {  /* xorshift64*, seeded from the clock and the process id */
    if (!pk_seed) pk_seed = ((unsigned long long)(pk_time() * 1e6) ^ ((unsigned long long)getpid() << 32)) | 1;
    pk_seed ^= pk_seed >> 12; pk_seed ^= pk_seed << 25; pk_seed ^= pk_seed >> 27;
    return pk_seed * 2685821657736338717ULL;
}

long long pk_random_int(long long lo, long long hi) {
    if (lo > hi) { long long t = lo; lo = hi; hi = t; }
    return lo + (long long)(pk_next() % (unsigned long long)(hi - lo + 1));
}

double pk_random_float(void) { return (pk_next() >> 11) * (1.0 / 9007199254740992.0); }

void pk_index_panic(const char *file, long long line, long long i, long long len);
static void pk_list_check(PkList *l, long long i, long long upto, const char *file, long long line) {
    if (i < 0 || i >= upto) pk_index_panic(file, line, i, l->len);
}

void *pk_list_insert(PkList *l, long long size, long long i, const char *file, long long line) {
    if (i < 0) i += l->len;
    pk_list_check(l, i, l->len + 1, file, line);
    pk_list_push(l, size);
    memmove(l->data + size * (i + 1), l->data + size * i, size * (l->len - 1 - i));
    return l->data + size * i;
}

static long long pk_removed;
void *pk_list_remove_at(PkList *l, long long size, long long i, const char *file, long long line) {
    if (i < 0) i += l->len;
    pk_list_check(l, i, l->len, file, line);
    memcpy(&pk_removed, l->data + size * i, size);
    memmove(l->data + size * i, l->data + size * (i + 1), size * (l->len - 1 - i));
    l->len--;
    return &pk_removed;
}

void pk_list_reverse(PkList *l, long long size) {
    char tmp[8];
    for (long long a = 0, b = l->len - 1; a < b; a++, b--) {
        memcpy(tmp, l->data + size * a, size);
        memcpy(l->data + size * a, l->data + size * b, size);
        memcpy(l->data + size * b, tmp, size);
    }
}

void pk_index_panic(const char *file, long long line, long long i, long long len) {
    static char msg[96];
    snprintf(msg, sizeof msg, "index %lld is out of range for a list of %lld", i, len);
    pk_panic(file, line, msg);
}

char *pk_input(const char *prompt) {
    pk_hold++;
    fputs(prompt, stdout);
    fflush(stdout);
    size_t cap = 0;
    char *buf = NULL;
    ssize_t n = getline(&buf, &cap, stdin);
    if (n <= 0) { free(buf); return ""; }
    if (buf[n - 1] == '\n') n--;
    char *r = pk_strndup(buf, n);  /* getline's buffer is plain malloc; hand the program a collected copy */
    free(buf);
    pk_hold--; return r;
}
"""


# ---------------------------------------------------------------- codegen
LL = {"int": ir.IntType(64), "float": ir.DoubleType(), "bool": ir.IntType(1),
      "str": ir.IntType(8).as_pointer(), "void": ir.VoidType()}
LIST = ir.LiteralStructType([LL["int"], LL["int"], LL["str"]]).as_pointer()  # len, cap, data
CLOSURE = ir.LiteralStructType([LL["str"], LL["str"]]).as_pointer()  # code, captured variables
I32 = ir.IntType(32)


def with_self(m, ty):
    """A method as a plain function: the same Fn with self as its first parameter."""
    return Fn(m.line, m.name, [("self", ty)] + m.params, m.ret, m.body, m.defaults, m.tparams)


def captures(body):
    """Names any closure inside body refers to. Conservative: a name is enough."""
    out = set()
    for node in walk(body):
        if isinstance(node, Lambda):
            out |= {n.name for n in walk(node.body) if isinstance(n, (Name, Call))} - {p for p, _ in node.params}
    return out


@dataclass
class Sig:
    func: object
    params: list    # [(name, type)]
    ret: str
    defaults: dict  # name -> expression, evaluated at the call


@dataclass
class EnumInfo:
    type: object    # {i64 tag, i64 slot, ...}; values are pointers to it
    cases: list     # [(name, [(field, type)])]

    def case(self, name):
        for tag, (case, fields) in enumerate(self.cases):
            if case == name:
                return tag, fields
        return None, None


@dataclass
class StructInfo:
    type: object    # the LLVM struct; values are pointers to it
    fields: list    # [(name, type)]
    defaults: dict


def size(ty):
    return 1 if ty == "bool" else 8  # ponytail: 64-bit targets only


def fn_sig(ty):
    """(["int", "str"], "bool") for "fn(int, str) -> bool", None for anything else."""
    if not ty.startswith("fn(") or ty.endswith("?"):
        return None
    depth, parts, cur = 0, [], ""
    for i, c in enumerate(ty[3:], 3):
        if c == ")" and depth == 0:
            parts.append(cur.strip())
            return [p for p in parts if p], ty[i + 5:]
        if c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        depth += (c in "([") - (c in ")]")
        cur += c


def walk(node):
    """Every AST node under node."""
    if isinstance(node, (list, tuple)):
        for x in node:
            yield from walk(x)
    elif isinstance(node, dict):
        yield from walk(list(node.values()))
    elif isinstance(node, Node):
        yield node
        for f in node.__dataclass_fields__:
            yield from walk(getattr(node, f))


def tuple_parts(ty):
    """["int", "str"] for "(int, str)", None for anything else."""
    if not ty.startswith("(") or not ty.endswith(")"):
        return None
    parts, depth, cur = [], 0, ""
    for c in ty[1:-1]:
        if c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        depth += (c in "<[(") - (c in ">])")
        cur += c
    parts.append(cur.strip())
    return parts


def generic_name(ty):
    """("Stack", ["int"]) for "Stack<int>", None for anything else."""
    if not ty or "<" not in ty or not ty.endswith(">"):
        return None
    base, rest = ty.split("<", 1)
    if not base.split(".")[-1][:1].isupper():
        return None
    args, depth, cur = [], 0, ""
    for c in rest[:-1]:
        if c == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
            continue
        depth += (c in "<[(") - (c in ">])")
        cur += c
    args.append(cur.strip())
    return base, args


def dict_kv(ty):
    """("str", "int") for "[str: int]", None for anything that is not a dict."""
    if ty == "[:]" or not ty.startswith("[") or ty.endswith("?"):
        return None
    depth = 0
    for i, c in enumerate(ty[1:-1]):
        depth += (c == "[") - (c == "]")
        if c == ":" and depth == 0:
            return ty[1:i + 1], ty[i + 3:-1]
    return None


def is_list(ty):
    return ty.startswith("[") and ty != "[:]" and not ty.endswith("?") and dict_kv(ty) is None


def fits(got, want):
    if want.endswith("?") and (got == "nil" or fits(got, want[:-1])):
        return True
    return got == want or (got == "[]" and is_list(want)) or (got == "[:]" and dict_kv(want) is not None)
INT_OPS = {"+": "add", "-": "sub", "*": "mul", "/": "sdiv", "%": "srem"}
FLOAT_OPS = {"+": "fadd", "-": "fsub", "*": "fmul", "/": "fdiv", "%": "frem"}
CMP = {"==", "!=", "<", ">", "<=", ">="}
BUILTINS = {"print", "int", "float", "str", "len", "input", "assert"}  # user functions cannot take these names
FMT = {"int": "%lld", "float": "%.15g", "str": "%s", "bool": "%s"}


@dataclass
class Var:
    ptr: object
    ty: str
    mutable: bool


class Codegen:
    def __init__(self, name, file=None, files=None, uses_json=True, modules=(), uses_set=True):
        self.uses_json = uses_json  # the Json enum is only compiled in when the program mentions it
        self.uses_set = uses_set    # same for Set<T>
        self.modules = set(modules)  # import aliases: x.parse(), x.Point
        self.files = files or [file or name]  # what runtime errors call each source file: the path you typed
        self.module = ir.Module(name=name)
        self.module.triple = TRIPLE
        self.fns = {}       # name or Struct.method -> Sig
        self.generics = {}  # name -> Fn with type parameters, instantiated per call
        self.generic_structs = {}  # name -> Struct with type parameters, instantiated per use
        self.externs = set()       # C functions declared with extern fn; bools cross as C ints
        self.structs = {}   # name -> StructInfo
        self.enums = {}     # name -> EnumInfo
        self.scopes = []
        self.loops = []     # (continue block, break block)
        self.strings = {}
        self.builder = self.fn_ret = None
        self.captured = set()   # names some closure in the current function uses
        self.has_try, self.tries = False, 0  # does this function use try; how many are open here
        self.lambdas = 0
        self.printf = self.c("printf", ir.IntType(32), LL["str"], var_arg=True)

    # -- helpers
    def ll(self, ty, line=0):
        """The LLVM type for a Plank type. Every list is the same pointer; [int] vs [str] lives in the Plank type."""
        if ty.endswith("?"):
            return self.ll(ty[:-1], line).as_pointer()  # an optional points at a boxed value, or is null
        if tuple_parts(ty):
            return self.tuple_struct(ty, line).as_pointer()
        if fn_sig(ty):
            return CLOSURE
        if ty.startswith("["):
            return LIST if is_list(ty) else LL["str"]  # a dict is an opaque runtime pointer
        if ty in LL:
            return LL[ty]
        if ty in self.structs:
            return self.structs[ty].type.as_pointer()
        if generic_name(ty) and self.instantiate_struct(ty, line):
            return self.structs[ty].type.as_pointer()
        if ty in self.enums:
            return self.enums[ty].type.as_pointer()
        raise PlankError(line, f"unknown type {ty!r}")

    def c(self, name, ret, *args, var_arg=False):
        """A C function from libc, libm or RUNTIME, declared on first use."""
        if name in self.module.globals:
            return self.module.globals[name]
        return ir.Function(self.module, ir.FunctionType(ret, args, var_arg=var_arg), name)

    def call_c(self, name, ret, *args):
        ret = ret if isinstance(ret, ir.Type) else LL[ret]
        return self.builder.call(self.c(name, ret, *[a.type for a in args]), list(args))

    def where(self, line):
        path, n = locate(line, self.files)
        return [self.cstr(path), ir.Constant(LL["int"], n)]

    def coerce(self, val, got, want):
        """Make a value that fits `want` into one: box it when an optional is expected, or give nil its type."""
        if got == want or not want.endswith("?"):
            return val
        if got == "nil":
            return ir.Constant(self.ll(want), None)
        val = self.coerce(val, got, want[:-1])
        box = self.builder.bitcast(self.call_c("pk_alloc", "str", ir.Constant(LL["int"], 8)), self.ll(want))
        self.builder.store(val, box)
        return box

    def to_str(self, val, ty):
        if ty == "nil":
            return self.cstr("nil")
        if ty.endswith("?"):
            return self.builder.call(self.show_optional(ty), [val])
        if ty == "str":
            return val
        if ty == "bool":
            return self.builder.select(val, self.cstr("true"), self.cstr("false"))
        if ty in ("[]", "[:]"):
            return self.cstr(ty)
        if dict_kv(ty):
            return self.builder.call(self.show_dict(ty), [val])
        if ty.startswith("["):
            return self.builder.call(self.show_list(ty), [val])
        if tuple_parts(ty):
            return self.builder.call(self.show_tuple(ty), [val])
        if ty in self.structs:
            return self.builder.call(self.show_struct(ty), [val])
        if ty in self.enums:
            return self.builder.call(self.show_enum(ty), [val])
        if fn_sig(ty):
            return self.cstr(ty)
        return self.call_c("pk_str_" + ty, "str", val)
    def cstr(self, s):
        if s not in self.strings:
            data = bytearray(s.encode() + b"\0")
            arr = ir.ArrayType(ir.IntType(8), len(data))
            g = ir.GlobalVariable(self.module, arr, f".str{len(self.strings)}")
            g.global_constant, g.linkage = True, "private"
            g.initializer = ir.Constant(arr, data)
            self.strings[s] = g
        g = self.strings[s]
        return g.gep([ir.Constant(ir.IntType(32), 0)] * 2) if self.builder is None \
            else self.builder.gep(g, [ir.Constant(ir.IntType(32), 0)] * 2, inbounds=True)

    def lookup(self, name, line):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise PlankError(line, f"unknown variable {name!r}")

    def declare(self, name, ty, mutable, line):
        if name in self.scopes[-1]:
            raise PlankError(line, f"{name!r} already declared in this scope")
        if name in self.captured or self.has_try:  # a closure may outlive this call; a try's jump would lose registers
            cell = self.call_c("pk_alloc", "str", ir.Constant(LL["int"], 8))
            ptr = self.builder.bitcast(cell, self.ll(ty).as_pointer(), name=name)
        else:
            with self.builder.goto_entry_block():
                ptr = self.builder.alloca(self.ll(ty), name=name)
        self.scopes[-1][name] = Var(ptr, ty, mutable)
        return ptr

    # -- program
    SET_SRC = """
struct Set<T> {
  members: [T: bool] = [:]

  fn add(x: T) {
    self.members[x] = true
  }

  fn remove(x: T) {
    if x in self.members {
      self.members.remove(x)
    }
  }

  fn has(x: T) -> bool {
    return x in self.members
  }

  fn size() -> int {
    return len(self.members)
  }

  fn items() -> [T] {
    return self.members.keys()
  }

  fn union(other: Set<T>) -> Set<T> {
    let out = Set<T>()
    for x in self.members {
      out.add(x)
    }
    for x in other.members {
      out.add(x)
    }
    return out
  }

  fn intersect(other: Set<T>) -> Set<T> {
    let out = Set<T>()
    for x in self.members {
      if other.has(x) {
        out.add(x)
      }
    }
    return out
  }

  fn minus(other: Set<T>) -> Set<T> {
    let out = Set<T>()
    for x in self.members {
      if not other.has(x) {
        out.add(x)
      }
    }
    return out
  }

  fn text() -> str {
    return "Set" + str(self.members.keys())
  }
}

fn set_of<T>(xs: [T]) -> Set<T> {
  let out = Set<T>()
  for x in xs {
    out.add(x)
  }
  return out
}
"""

    JSON_SRC = """
enum Json {
  null
  bool(b: bool)
  number(n: float)
  string(s: str)
  array(items: [Json])
  object(fields: [str: Json])

  fn get(key: str) -> Json {
    match self {
      .object(fields) {
        if key in fields { return fields[key] }
        throw "no key \\"\\(key)\\" in this JSON object"
      }
      else { throw "not a JSON object, cannot look up \\"\\(key)\\"" }
    }
  }

  fn at(i: int) -> Json {
    match self {
      .array(items) { return items[i] }
      else { throw "not a JSON array, cannot take item \\(i)" }
    }
  }

  fn str() -> str {
    match self {
      .string(s) { return s }
      else { throw "this JSON value is not a string" }
    }
  }

  fn num() -> float {
    match self {
      .number(n) { return n }
      else { throw "this JSON value is not a number" }
    }
  }

  fn int() -> int {
    return int(self.num())
  }

  fn truth() -> bool {
    match self {
      .bool(b) { return b }
      else { throw "this JSON value is not a bool" }
    }
  }

  fn keys() -> [str] {
    match self {
      .object(fields) { return fields.keys() }
      else { throw "not a JSON object, it has no keys" }
    }
  }

  fn items() -> [Json] {
    match self {
      .array(items) { return items }
      else { throw "not a JSON array, it has no items" }
    }
  }

  fn text() -> str {
    match self {
      .null { return "null" }
      .bool(b) { return str(b) }
      .number(n) {
        if n == float(int(n)) and abs(n) < 1000000000000000.0 { return str(int(n)) }
        return str(n)
      }
      .string(s) { return json_quote(s) }
      .array(items) { return "[" + items.map(fn(x) => x.text()).join(",") + "]" }
      .object(fields) {
        return "{" + fields.keys().map(fn(k) => json_quote(k) + ":" + fields[k].text()).join(",") + "}"
      }
    }
  }
}
"""

    def program(self, items):
        if self.uses_json:
            items = Parser(lex(self.JSON_SRC, 900 * STRIDE + 1)).program() + items
        if self.uses_set:
            items = Parser(lex(self.SET_SRC, 901 * STRIDE + 1)).program() + items
        structs = [x for x in items if isinstance(x, Struct) and not x.tparams]
        for st in items:
            if isinstance(st, Struct) and st.tparams:
                if st.name in self.generic_structs:
                    raise PlankError(st.line, f"type {st.name!r} defined twice")
                self.generic_structs[st.name] = st
        enums = [x for x in items if isinstance(x, Enum)]
        C_TYPES = {"int": LL["int"], "float": LL["float"], "bool": I32, "str": LL["str"], "void": ir.VoidType()}
        for f in items:  # extern fn: a C function by its own name, int is long long, float is double, bool is int
            if isinstance(f, Fn) and f.extern:
                for _, t in f.params + [("", f.ret)]:
                    if t not in C_TYPES:
                        raise PlankError(f.line, f"extern fn {f.name} can only pass int, float, bool and str, not {t}")
                if f.name in self.fns:
                    raise PlankError(f.line, f"function {f.name!r} defined twice")
                func = self.c(f.name, C_TYPES[f.ret], *[C_TYPES[t] for _, t in f.params])
                self.fns[f.name] = Sig(func, f.params, f.ret, {})
                self.externs.add(f.name)
        fns = [(f.name, f, []) for f in items if isinstance(f, Fn) and not f.tparams and not f.extern]
        for f in items:
            if isinstance(f, Fn) and f.tparams:
                if f.name in self.generics or any(x.name == f.name for x in items if isinstance(x, Fn) and not x.tparams):
                    raise PlankError(f.line, f"function {f.name!r} defined twice")
                self.generics[f.name] = f
        for t in structs + enums:  # name every type first so fields can point at each other
            if t.name in self.structs or t.name in self.enums:
                raise PlankError(t.line, f"type {t.name!r} defined twice")
            ll_type = self.module.context.get_identified_type(t.name)
            if isinstance(t, Struct):
                self.structs[t.name] = StructInfo(ll_type, t.fields, t.defaults)
            else:
                self.enums[t.name] = EnumInfo(ll_type, t.cases)
        for st in structs:
            self.structs[st.name].type.set_body(*[self.ll(t, st.line) for _, t in st.fields])
        for en in enums:
            names = [c for c, _ in en.cases]
            for c in names:
                if names.count(c) > 1:
                    raise PlankError(en.line, f"{en.name} has two cases called {c}")
            for _, fields in en.cases:
                for _, fty in fields:
                    self.ll(fty, en.line)
            slots = max([len(f) for _, f in en.cases] + [0])
            self.enums[en.name].type.set_body(LL["int"], *[LL["int"]] * slots)  # tag, then 8-byte payload slots
        for t in structs + enums:
            for m in t.methods:
                if m.tparams:  # a generic method: instantiated per call like a generic function, with self in front
                    self.generics[f"{t.name}.{m.name}"] = with_self(m, t.name)
                else:
                    fns.append((f"{t.name}.{m.name}", m, [("self", t.name)]))
        for key, f, recv in fns:
            if key in self.fns:
                raise PlankError(f.line, f"function {key!r} defined twice")
            if (key in BUILTINS or key in self.structs or key in self.enums) and not key.startswith("Json."):  # math helpers like sqrt can be redefined, these cannot
                raise PlankError(f.line, f"{key!r} is a built-in or a struct, pick another name")
            params = recv + f.params
            fty = ir.FunctionType(self.ll(f.ret, f.line), [self.ll(t, f.line) for _, t in params])
            self.fns[key] = Sig(ir.Function(self.module, fty, "pk." + key), params, f.ret, f.defaults)  # the dot keeps them apart from C and the runtime
        main = self.fns.get("main")
        if not main or main.params or main.ret != "void":
            raise PlankError(1, "need a `fn main()` with no parameters and no return type")
        for key, f, _ in fns:
            self.function(key, f)
        argv = LL["str"].as_pointer()
        entry = ir.Function(self.module, ir.FunctionType(I32, [I32, argv]), "main")
        b = ir.IRBuilder(entry.append_basic_block())
        b.call(self.c("pk_set_args", ir.VoidType(), I32, argv), entry.args)
        b.call(main.func, [])
        b.ret(ir.Constant(ir.IntType(32), 0))
        return self.module

    def function(self, key, f):
        sig = self.fns[key]
        func, self.fn_ret = sig.func, sig.ret
        self.builder = ir.IRBuilder(func.append_basic_block("entry"))
        self.scopes = [{}]
        self.captured = captures(f.body)
        self.has_try, self.tries = any(isinstance(n, Try) for n in walk(f.body)), 0
        for (name, ty), arg in zip(sig.params, func.args):
            arg.name = name
            self.builder.store(arg, self.declare(name, ty, False, f.line))
        self.stmts(f.body)
        if not self.builder.block.is_terminated:
            if f.ret != "void":
                raise PlankError(f.line, f"function {f.name!r} can reach its end without returning")
            self.builder.ret_void()

    # -- statements
    def stmts(self, body):
        self.scopes.append({})
        for s in body:
            self.stmt(s)
            if self.builder.block.is_terminated:
                break
        self.scopes.pop()

    def stmt(self, s):
        getattr(self, "s_" + type(s).__name__)(s)

    def s_Let(self, s):
        if s.ty:
            self.ll(s.ty, s.line)  # an unknown type is its own error
        val, ty = self.expr(s.expr, hint=s.ty)
        if s.ty and not fits(ty, s.ty):
            raise PlankError(s.line, f"{s.name!r} is declared {s.ty} but assigned {ty}")
        if ty == "[]" and not s.ty:
            raise PlankError(s.line, f"an empty list needs its type: let {s.name}: [int] = []")
        if ty == "[:]" and not s.ty:
            raise PlankError(s.line, f"an empty dict needs its type: let {s.name}: [str: int] = [:]")
        if ty == "nil" and not s.ty:
            raise PlankError(s.line, f"nil needs a type to be nil of: let {s.name}: int? = nil")
        self.builder.store(self.coerce(val, ty, s.ty or ty), self.declare(s.name, s.ty or ty, s.mutable, s.line))

    def s_Assign(self, s):
        if isinstance(s.target, Index):
            ptr, want = self.index_ptr(s.target, write=True)
            what = "this list"
        elif isinstance(s.target, Field):
            ptr, want = self.field_ptr(s.target)
            what = repr(s.target.name)
        else:
            var = self.lookup(s.target.name, s.line)
            if not var.mutable:
                raise PlankError(s.line, f"{s.target.name!r} is a let, use var to reassign it")
            ptr, want, what = var.ptr, var.ty, repr(s.target.name)
        val, ty = self.expr(s.expr)
        if not fits(ty, want):
            raise PlankError(s.line, f"cannot assign {ty} to {what} which holds {want}")
        self.builder.store(self.coerce(val, ty, want), ptr)

    def s_ExprStmt(self, s):
        self.expr(s.expr, allow_void=True)

    def s_Return(self, s):
        if s.expr is not None and self.fn_ret in ("_", "void"):
            val, ty = self.expr(s.expr, allow_void=True, hint=None if self.fn_ret == "_" else self.fn_ret)
            if self.fn_ret == "_":
                self.fn_ret = self.probed = ty  # the first return in a probe sets the type; the rest must agree
            if ty == "void":
                self.leave(self.tries)
                self.builder.ret_void()
                return
            if self.fn_ret == "void":
                raise PlankError(s.line, f"this function returns nothing, so return cannot carry a {ty}")
            val = self.coerce(val, ty, self.fn_ret)
            self.leave(self.tries)
            self.builder.ret(val)
            return
        if s.expr is None:
            if self.fn_ret == "_":
                self.fn_ret = self.probed = "void"
            if self.fn_ret != "void":
                raise PlankError(s.line, f"return needs a {self.fn_ret} value")
            self.leave(self.tries)
            self.builder.ret_void()
            return
        val, ty = self.expr(s.expr, hint=self.fn_ret)
        if not fits(ty, self.fn_ret):
            raise PlankError(s.line, f"returning {ty} from a function that returns {self.fn_ret}")
        val = self.coerce(val, ty, self.fn_ret)
        self.leave(self.tries)
        self.builder.ret(val)

    def leave(self, n):
        """Close n open try blocks before jumping out of them."""
        for _ in range(n):
            self.builder.call(self.c("pk_try_pop", ir.VoidType()), [])

    def s_Try(self, s):
        b = self.builder
        jb = self.call_c("pk_try_push", "str")
        setjmp = self.c("_setjmp", I32, LL["str"])
        setjmp.attributes.add("returns_twice")
        first = b.icmp_signed("==", b.call(setjmp, [jb]), ir.Constant(I32, 0))
        body_bb, catch_bb, merge = (b.append_basic_block(n) for n in ("try", "catch", "endtry"))
        b.cbranch(first, body_bb, catch_bb)
        b.position_at_end(body_bb)
        self.tries += 1
        self.stmts(s.body)
        self.tries -= 1
        live = False
        if not b.block.is_terminated:
            self.leave(1)
            b.branch(merge)
            live = True
        b.position_at_end(catch_bb)
        self.scopes.append({})
        b.store(self.call_c("pk_caught", "str"), self.declare(s.name, "str", False, s.line))
        live |= self.arm(s.handler, merge)
        self.scopes.pop()
        b.position_at_end(merge)
        if not live:
            b.unreachable()

    def s_Throw(self, s):
        val, ty = self.expr(s.expr)
        if ty != "str":
            raise PlankError(s.line, f"throw takes a str message, got {ty}")
        panic = self.c("pk_panic", ir.VoidType(), LL["str"], LL["int"], LL["str"])
        self.builder.call(panic, self.where(s.line) + [val])
        self.builder.unreachable()

    def cond(self, e):
        val, ty = self.expr(e)
        if ty != "bool":
            raise PlankError(e.line, f"condition must be bool, got {ty}")
        return val

    def s_If(self, s):
        cond = self.cond(s.cond)
        then_bb = self.builder.append_basic_block("then")
        else_bb = self.builder.append_basic_block("else")
        merge = self.builder.append_basic_block("endif")
        self.builder.cbranch(cond, then_bb, else_bb)
        live = False
        for bb, body in ((then_bb, s.then), (else_bb, s.other)):
            self.builder.position_at_end(bb)
            self.stmts(body)
            if not self.builder.block.is_terminated:
                self.builder.branch(merge)
                live = True
        self.builder.position_at_end(merge)
        if not live:
            self.builder.unreachable()

    def s_Match(self, s):
        val, ty = self.expr(s.subject)
        b = self.builder
        merge = b.append_basic_block("endmatch")
        live = False
        if ty in self.enums:
            info = self.enums[ty]
            tag = b.load(b.gep(val, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            other_bb = b.append_basic_block("other")
            switch = b.switch(tag, other_bb)
            seen = set()
            for pats, body in s.arms:
                arm = b.append_basic_block("case")
                binds = None
                for pat in pats:
                    if not isinstance(pat, tuple):
                        raise PlankError(s.line, f"match on {ty} wants cases like .{info.cases[0][0]}")
                    case, names = pat
                    t, fields = info.case(case)
                    if t is None:
                        raise PlankError(s.line, f"{ty} has no case .{case}")
                    if case in seen:
                        raise PlankError(s.line, f".{case} is matched twice")
                    seen.add(case)
                    if names and len(pats) > 1:
                        raise PlankError(s.line, "an arm that binds values can only match one case")
                    if names and len(names) != len(fields):
                        raise PlankError(s.line, f".{case} carries {len(fields)} value{'s' * (len(fields) != 1)}, the pattern names {len(names)}")
                    if names:
                        binds = list(zip(names, fields, range(len(fields))))
                    switch.add_case(ir.Constant(LL["int"], t), arm)
                b.position_at_end(arm)
                self.scopes.append({})
                for name, (_, fty), i in binds or []:
                    slot = b.gep(val, [ir.Constant(I32, 0), ir.Constant(I32, 1 + i)])
                    self.builder.store(b.load(b.bitcast(slot, self.ll(fty).as_pointer())), self.declare(name, fty, False, s.line))
                live |= self.arm(body, merge)
                self.scopes.pop()
            missing = [c for c, _ in info.cases if c not in seen]
            if missing and s.other is None:
                raise PlankError(s.line, f"match on {ty} misses {', '.join('.' + c for c in missing)}; handle {'it' if len(missing) == 1 else 'them'} or add an else")
            b.position_at_end(other_bb)
            if s.other is None or not missing:
                b.unreachable()
                if s.other is not None:
                    raise PlankError(s.line, "this match covers every case, the else can never run")
            else:
                live |= self.arm(s.other, merge)
        else:
            for pats, body in s.arms:
                hit = None
                for pat in pats:
                    if isinstance(pat, tuple):
                        raise PlankError(s.line, f".{pat[0]} is an enum case, but this match is on {ty}")
                    eq = self.e_Binary(Binary(s.line, "==", Given(s.line, val, ty), pat))[0]
                    hit = eq if hit is None else b.or_(hit, eq)
                arm, nxt = b.append_basic_block("case"), b.append_basic_block("next")
                b.cbranch(hit, arm, nxt)
                b.position_at_end(arm)
                live |= self.arm(body, merge)
                b.position_at_end(nxt)
            if s.other is not None:
                live |= self.arm(s.other, merge)
            else:
                b.branch(merge)
                live = True
        b.position_at_end(merge)
        if not live:
            b.unreachable()

    def arm(self, body, merge):
        """Emit one arm; True if it can fall through to the end of the match."""
        self.stmts(body)
        if self.builder.block.is_terminated:
            return False
        self.builder.branch(merge)
        return True

    def s_IfLet(self, s):
        val, ty = self.expr(s.expr)
        if not ty.endswith("?"):
            raise PlankError(s.line, f"if let unwraps an optional, {ty} is never nil; use a plain let")
        b = self.builder
        then_bb, else_bb, merge = (b.append_basic_block(n) for n in ("some", "none", "endif"))
        b.cbranch(b.icmp_unsigned("!=", val, ir.Constant(val.type, None)), then_bb, else_bb)
        live = False
        for bb, body in ((then_bb, s.then), (else_bb, s.other)):
            b.position_at_end(bb)
            self.scopes.append({})
            if bb is then_bb:
                b.store(b.load(val), self.declare(s.name, ty[:-1], False, s.line))
            live |= self.arm(body, merge)
            self.scopes.pop()
        b.position_at_end(merge)
        if not live:
            b.unreachable()

    def s_While(self, s):
        cond_bb = self.builder.append_basic_block("while")
        body_bb = self.builder.append_basic_block("body")
        end_bb = self.builder.append_basic_block("endwhile")
        self.builder.branch(cond_bb)
        self.builder.position_at_end(cond_bb)
        self.builder.cbranch(self.cond(s.cond), body_bb, end_bb)
        self.builder.position_at_end(body_bb)
        self.loops.append([cond_bb, end_bb, False, self.tries])
        self.stmts(s.body)
        _, _, broke, _ = self.loops.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_bb)
        self.builder.position_at_end(end_bb)
        if isinstance(s.cond, Bool) and s.cond.val and not broke:  # `while true` with no break never ends
            self.builder.unreachable()

    def s_For(self, s):
        start, t1 = self.expr(s.start)
        stop, t2 = self.expr(s.stop)
        if t1 != "int" or t2 != "int":
            raise PlankError(s.line, "for ranges are int..int")
        self.scopes.append({})
        i = self.declare(s.name, "int", False, s.line)
        self.builder.store(start, i)
        cond_bb = self.builder.append_basic_block("for")
        body_bb = self.builder.append_basic_block("body")
        step_bb = self.builder.append_basic_block("step")
        end_bb = self.builder.append_basic_block("endfor")
        self.builder.branch(cond_bb)
        self.builder.position_at_end(cond_bb)
        cur = self.builder.load(i)
        self.builder.cbranch(self.builder.icmp_signed("<", cur, stop), body_bb, end_bb)
        self.builder.position_at_end(body_bb)
        self.loops.append([step_bb, end_bb, False, self.tries])
        self.stmts(s.body)
        self.loops.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(step_bb)
        self.builder.position_at_end(step_bb)
        self.builder.store(self.builder.add(self.builder.load(i), ir.Constant(LL["int"], 1)), i)
        self.builder.branch(cond_bb)
        self.builder.position_at_end(end_bb)
        self.scopes.pop()

    def s_WhileLet(self, s):
        b = self.builder
        cond_bb, body_bb, end_bb = (b.append_basic_block(n) for n in ("whilelet", "body", "endwhile"))
        b.branch(cond_bb)
        b.position_at_end(cond_bb)
        val, ty = self.expr(s.expr)
        if not ty.endswith("?"):
            raise PlankError(s.line, f"while let unwraps an optional each time round, {ty} is never nil")
        b.cbranch(b.icmp_unsigned("!=", val, ir.Constant(val.type, None)), body_bb, end_bb)
        b.position_at_end(body_bb)
        self.scopes.append({})
        b.store(b.load(val), self.declare(s.name, ty[:-1], False, s.line))
        self.loops.append([cond_bb, end_bb, False, self.tries])
        self.stmts(s.body)
        self.loops.pop()
        self.scopes.pop()
        if not b.block.is_terminated:
            b.branch(cond_bb)
        b.position_at_end(end_bb)

    def s_ForIn(self, s):
        source, source_ty = self.expr(s.items)
        if generic_name(source_ty) and generic_name(source_ty)[0] == "Set":
            source, source_ty = self.e_Method(Method(s.line, Given(s.line, source, source_ty), "items", [], []))
        items, ty = source, source_ty
        if dict_kv(ty):
            items, ty = self.call_c("pk_dict_keys", LIST, items), f"[{dict_kv(ty)[0]}]"
        if ty == "str":
            items, ty = self.call_c("pk_chars", LIST, items), "[str]"
        if not is_list(ty) or ty == "[]":
            raise PlankError(s.line, f"for ... in needs a list or a range, got {ty}")
        b = self.builder
        self.scopes.append({})
        with b.goto_entry_block():
            i = b.alloca(LL["int"], name="i")
        b.store(ir.Constant(LL["int"], 0), i)
        elem = ty[1:-1]
        kv = dict_kv(source_ty)
        if s.second is None:
            x = self.declare(s.name, elem, False, s.line)
        elif kv:  # for k, v in d
            x = self.declare(s.name, elem, False, s.line)
            v = self.declare(s.second, kv[1], False, s.line)
        else:     # for i, x in xs
            idx = self.declare(s.name, "int", False, s.line)
            x = self.declare(s.second, elem, False, s.line)
        cond_bb, body_bb = b.append_basic_block("forin"), b.append_basic_block("body")
        step_bb, end_bb = b.append_basic_block("step"), b.append_basic_block("endfor")
        b.branch(cond_bb)
        b.position_at_end(cond_bb)
        b.cbranch(b.icmp_signed("<", b.load(i), self.list_len(items)), body_bb, end_bb)
        b.position_at_end(body_bb)
        item = b.load(self.slot(items, b.load(i), elem))
        b.store(item, x)
        if s.second is not None and kv:
            b.store(b.load(self.dict_slot(source, kv, item, kv[0], s.line, "pk_dict_find")), v)
        elif s.second is not None:
            b.store(b.load(i), idx)
        self.loops.append([step_bb, end_bb, False, self.tries])
        self.stmts(s.body)
        self.loops.pop()
        if not b.block.is_terminated:
            b.branch(step_bb)
        b.position_at_end(step_bb)
        b.store(b.add(b.load(i), ir.Constant(LL["int"], 1)), i)
        b.branch(cond_bb)
        b.position_at_end(end_bb)
        self.scopes.pop()

    def s_Break(self, s):
        if not self.loops:
            raise PlankError(s.line, "break outside a loop")
        self.loops[-1][2] = True
        self.leave(self.tries - self.loops[-1][3])
        self.builder.branch(self.loops[-1][1])

    def s_Continue(self, s):
        if not self.loops:
            raise PlankError(s.line, "continue outside a loop")
        self.leave(self.tries - self.loops[-1][3])
        self.builder.branch(self.loops[-1][0])

    # -- expressions: each returns (llvm value, plank type)
    def expr(self, e, allow_void=False, hint=None):
        if isinstance(e, Lambda):
            return self.e_Lambda(e, hint)
        val, ty = getattr(self, "e_" + type(e).__name__)(e)
        if ty == "void" and not allow_void:
            raise PlankError(e.line, "this call returns nothing, it cannot be used as a value")
        return val, ty

    def e_Num(self, e):
        return ir.Constant(LL[e.ty], e.val), e.ty

    def e_Str(self, e):
        return self.cstr(e.val), "str"

    def e_Interp(self, e):
        out = None
        for part in e.parts:
            if isinstance(part, Str) and not part.val:
                continue
            val = self.to_str(*self.expr(part))
            out = val if out is None else self.call_c("pk_concat", "str", out, val)
        return out if out is not None else self.cstr(""), "str"

    def list_len(self, lst):
        return self.builder.load(self.builder.gep(lst, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))

    def slot(self, lst, i, elem):
        data = self.builder.load(self.builder.gep(lst, [ir.Constant(I32, 0), ir.Constant(I32, 2)]))
        return self.builder.gep(self.builder.bitcast(data, self.ll(elem).as_pointer()), [i])

    def bits(self, val, ty):
        """Any value as 8 bytes, the way the runtime stores keys and compares list items."""
        b = self.builder
        if ty == "float":
            return b.bitcast(val, LL["int"])
        if ty == "bool":
            return b.zext(val, LL["int"])
        return val if ty == "int" else b.ptrtoint(val, LL["int"])

    def dict_slot(self, d, kv, key, kt, line, fn):
        if kt != kv[0]:
            raise PlankError(line, f"this dict's keys are {kv[0]}, got {kt}")
        slot_ty = LL["int"].as_pointer()
        args = [d, self.bits(key, kt), ir.Constant(LL["int"], int(kt == "str"))] + (self.where(line) if fn == "pk_dict_get" else [])
        slot = self.builder.call(self.c(fn, slot_ty, *[a.type for a in args]), args)
        return self.builder.bitcast(slot, self.ll(kv[1]).as_pointer())

    def index_ptr(self, e, write=False, target=None):
        """Pointer to xs[i], bounds checked, negative i counts from the end, like Python. Or to d[k]."""
        lst, ty = target or self.expr(e.target)
        if ty == "str":
            raise PlankError(e.line, "strings cannot be changed in place; build a new one with + or replace()")
        kv = dict_kv(ty)
        if kv:
            key, kt = self.expr(e.index)
            return self.dict_slot(lst, kv, key, kt, e.line, "pk_dict_put" if write else "pk_dict_get"), kv[1]
        if not is_list(ty) or ty == "[]":
            raise PlankError(e.line, f"cannot index {ty}, only lists and dicts")
        i, it = self.expr(e.index)
        if it != "int":
            raise PlankError(e.line, f"list index must be int, got {it}")
        b = self.builder
        n = self.list_len(lst)
        at = b.select(b.icmp_signed("<", i, ir.Constant(i.type, 0)), b.add(i, n), i)
        with b.if_then(b.icmp_unsigned(">=", at, n), likely=False):
            panic = self.c("pk_index_panic", ir.VoidType(), LL["str"], LL["int"], LL["int"], LL["int"])
            b.call(panic, self.where(e.line) + [i, n])
            b.unreachable()
        return self.slot(lst, at, ty[1:-1]), ty[1:-1]

    def e_Index(self, e):
        target = self.expr(e.target)
        if target[1] == "str":
            i, it = self.expr(e.index)
            if it != "int":
                raise PlankError(e.line, f"string index must be int, got {it}")
            return self.call_c("pk_char_at", "str", target[0], i, *self.where(e.line)), "str"
        ptr, ty = self.index_ptr(e, target=target)
        return self.builder.load(ptr), ty

    def e_Slice(self, e):
        """xs[a..b], s[..b], xs[a..]: a copy, ends clamped like Python, negatives count from the end."""
        val, ty = self.expr(e.target)
        ends = []
        for end, missing in ((e.start, 0), (e.stop, 2 ** 62)):
            if end is None:
                ends.append(ir.Constant(LL["int"], missing))
                continue
            v, t = self.expr(end)
            if t != "int":
                raise PlankError(e.line, f"slice ends must be int, got {t}")
            ends.append(v)
        if ty == "str":
            return self.call_c("pk_str_slice", "str", val, *ends), "str"
        if is_list(ty) and ty != "[]":
            return self.call_c("pk_list_slice", LIST, val, ir.Constant(LL["int"], size(ty[1:-1])), *ends), ty
        raise PlankError(e.line, f"cannot slice {ty}, only lists and strings")

    def e_List(self, e):
        items = [self.expr(x) for x in e.items]
        new = self.c("pk_list_new", LIST, LL["int"], LL["int"])
        if not items:
            return self.builder.call(new, [ir.Constant(LL["int"], 0), ir.Constant(LL["int"], 8)]), "[]"
        ty = next((t for _, t in items if t not in ("[]", "[:]", "nil")), items[0][1])  # an empty [] takes the type of its neighbours
        for _, t in items:
            if not fits(t, ty):
                raise PlankError(e.line, f"a list holds one type, this one mixes {ty} and {t}")
        lst = self.builder.call(new, [ir.Constant(LL["int"], len(items)), ir.Constant(LL["int"], size(ty))])
        for v, t in items:
            self.push(lst, self.coerce(v, t, ty), ty)
        return lst, f"[{ty}]"

    def e_Dict(self, e):
        if not e.keys:
            return self.builder.call(self.c("pk_dict_new", LL["str"], LL["int"]), [ir.Constant(LL["int"], 0)]), "[:]"
        pairs = [(self.expr(k), self.expr(v)) for k, v in zip(e.keys, e.vals)]
        kt, vt = pairs[0][0][1], pairs[0][1][1]
        if kt not in ("int", "str"):
            raise PlankError(e.line, f"dict keys are int or str, got {kt}")
        for (_, k), (_, v) in pairs:
            if (k, v) != (kt, vt):
                raise PlankError(e.line, f"a dict holds one key type and one value type, this one mixes {kt}: {vt} and {k}: {v}")
        d = self.builder.call(self.c("pk_dict_new", LL["str"], LL["int"]), [ir.Constant(LL["int"], int(kt == "str"))])
        ty = f"[{kt}: {vt}]"
        for (k, _), (v, _) in pairs:
            self.builder.store(v, self.dict_slot(d, (kt, vt), k, kt, e.line, "pk_dict_put"))
        return d, ty

    STR_METHODS = {  # name: (runtime function, argument types, result)
        "split": ("pk_split", ["str"], "[str]"), "trim": ("pk_trim", [], "str"),
        "upper": ("pk_case", [], "str"), "lower": ("pk_case", [], "str"),
        "replace": ("pk_replace", ["str", "str"], "str"), "find": ("pk_find", ["str"], "int?"),
        "starts_with": ("pk_starts", ["str"], "bool"), "ends_with": ("pk_ends", ["str"], "bool"),
        "chars": ("pk_chars", [], "[str]"),
    }

    REGEX_METHODS = {"matches": ("pk_matches", ["str"], "bool"), "captures": ("pk_captures", ["str"], "[str]?"),
                     "find_all": ("pk_find_all", ["str"], "[str]"), "replace_all": ("pk_replace_all", ["str", "str"], "str")}

    def str_method(self, e, s, args):
        if e.name in self.REGEX_METHODS:
            fn, want, ret = self.REGEX_METHODS[e.name]
            if [t for _, t in args] != want:
                raise PlankError(e.line, f"{e.name}() takes ({', '.join(want)}), got ({', '.join(t for _, t in args)})")
            vals = [s] + [v for v, _ in args] + self.where(e.line)
            if ret == "bool":
                return self.builder.trunc(self.call_c(fn, "int", *vals), LL["bool"]), "bool"
            if ret == "[str]?":
                return self.maybe(self.call_c(fn, LIST, *vals), "[str]")
            return self.call_c(fn, LIST if ret == "[str]" else ret, *vals), ret
        if e.name not in self.STR_METHODS:
            raise PlankError(e.line, f"str has no method {e.name}(); try {', '.join(m + '()' for m in self.STR_METHODS)}")
        fn, want, ret = self.STR_METHODS[e.name]
        if e.name == "split" and not args:
            args = [(self.cstr(""), "str")]  # no separator: whitespace
        if [t for _, t in args] != want:
            raise PlankError(e.line, f"{e.name}() takes ({', '.join(want)}), got ({', '.join(t for _, t in args)})")
        vals = [v for v, _ in args]
        if fn == "pk_case":
            vals.append(ir.Constant(LL["int"], int(e.name == "upper")))
        b = self.builder
        if ret == "bool":
            return b.trunc(self.call_c(fn, "int", s, *vals), LL["bool"]), "bool"
        if ret == "int?":
            at = self.call_c(fn, "int", s, *vals)
            found = b.icmp_signed(">=", at, ir.Constant(LL["int"], 0))
            with b.if_else(found) as (yes, no):
                with yes:
                    some, some_bb = self.coerce(at, "int", "int?"), b.block
                with no:
                    no_bb = b.block
            phi = b.phi(self.ll("int?"))
            phi.add_incoming(some, some_bb)
            phi.add_incoming(ir.Constant(self.ll("int?"), None), no_bb)
            return phi, "int?"
        return self.call_c(fn, LIST if ret == "[str]" else ret, s, *vals), ret

    def dict_method(self, e, d, kv, args):
        b = self.builder
        if e.name == "keys" and not args:
            return self.call_c("pk_dict_keys", LIST, d), f"[{kv[0]}]"
        if e.name == "items" and not args:  # [(K, V)] in insertion order
            keys = self.call_c("pk_dict_keys", LIST, d)
            pair_ty = f"({kv[0]}, {kv[1]})"
            self.tuple_struct(pair_ty, e.line)
            out = b.call(self.c("pk_list_new", LIST, LL["int"], LL["int"]), [self.list_len(keys), ir.Constant(LL["int"], 8)])
            def add(key):
                value = b.load(self.dict_slot(d, kv, key, kv[0], e.line, "pk_dict_find"))
                pair = self.construct(Call(e.line, pair_ty, [Given(e.line, key, kv[0]), Given(e.line, value, kv[1])], [None, None]))
                self.push(out, pair, pair_ty)
            self.each(keys, kv[0], add)
            return out, f"[{pair_ty}]"
        if e.name == "values" and not args:
            lst = self.call_c("pk_dict_values", LIST, d, ir.Constant(LL["int"], size(kv[1])))
            return lst, f"[{kv[1]}]"
        if e.name == "remove" and len(args) == 1:
            if args[0][1] != kv[0]:
                raise PlankError(e.line, f"this dict's keys are {kv[0]}, got {args[0][1]}")
            fn = self.c("pk_dict_remove", ir.VoidType(), LL["str"], LL["int"], LL["int"], LL["str"], LL["int"])
            b.call(fn, [d, self.bits(*args[0]), ir.Constant(LL["int"], int(kv[0] == "str"))] + self.where(e.line))
            return None, "void"
        if e.name == "get" and len(args) == 1:
            key, kt = args[0]
            slot = self.dict_slot(d, kv, key, kt, e.line, "pk_dict_find")
            want = kv[1] + "?"
            with b.if_else(b.icmp_unsigned("!=", slot, ir.Constant(slot.type, None))) as (found, missing):
                with found:
                    hit, hit_bb = self.coerce(b.load(slot), kv[1], want), b.block  # a copy, not the dict's own slot
                with missing:
                    miss_bb = b.block
            phi = b.phi(self.ll(want))
            phi.add_incoming(hit, hit_bb)
            phi.add_incoming(ir.Constant(self.ll(want), None), miss_bb)
            return phi, want
        if e.name == "get" and len(args) == 2:
            (key, kt), (fallback, ft) = args
            if not fits(ft, kv[1]):
                raise PlankError(e.line, f"get() default should be {kv[1]}, got {ft}")
            slot = self.dict_slot(d, kv, key, kt, e.line, "pk_dict_find")
            with b.if_else(b.icmp_unsigned("!=", slot, ir.Constant(slot.type, None))) as (found, missing):
                with found:
                    hit, hit_bb = b.load(slot), b.block
                with missing:
                    fallback, miss_bb = self.coerce(fallback, ft, kv[1]), b.block
            phi = b.phi(self.ll(kv[1]))
            phi.add_incoming(hit, hit_bb)
            phi.add_incoming(fallback, miss_bb)
            return phi, kv[1]
        raise PlankError(e.line, f"{e.name}() is not a dict method; dicts have keys(), values(), get(k, default), remove(k)")

    def quoted(self, val, ty):
        text = self.to_str(val, ty)
        if ty != "str":
            return text
        return self.call_c("pk_concat", "str", self.call_c("pk_concat", "str", self.cstr('"'), text), self.cstr('"'))

    def show_dict(self, ty):
        """["a": 1, "b": 2], or [:] when empty, the way Swift writes them."""
        name = "show" + ty
        if name in self.module.globals:
            return self.module.globals[name]
        fn = ir.Function(self.module, ir.FunctionType(LL["str"], [LL["str"]]), name)
        fn.linkage = "private"
        outer, self.builder = self.builder, ir.IRBuilder(fn.append_basic_block("entry"))
        b, d, (kt, vt) = self.builder, fn.args[0], dict_kv(ty)
        keys = self.call_c("pk_dict_keys", LIST, d)
        acc, i = b.alloca(LL["str"]), b.alloca(LL["int"])
        b.store(self.cstr("["), acc)
        b.store(ir.Constant(LL["int"], 0), i)
        cond, body, done = (fn.append_basic_block(n) for n in ("cond", "body", "done"))
        b.branch(cond)
        b.position_at_end(cond)
        n = self.list_len(keys)
        b.cbranch(b.icmp_signed("<", b.load(i), n), body, done)
        b.position_at_end(body)
        key = b.load(self.slot(keys, b.load(i), kt))
        val = b.load(self.dict_slot(d, (kt, vt), key, kt, 0, "pk_dict_find"))
        sep = b.select(b.icmp_signed("==", b.load(i), ir.Constant(LL["int"], 0)), self.cstr(""), self.cstr(", "))
        pair = self.call_c("pk_concat", "str", self.call_c("pk_concat", "str", self.quoted(key, kt), self.cstr(": ")), self.quoted(val, vt))
        b.store(self.call_c("pk_concat", "str", self.call_c("pk_concat", "str", b.load(acc), sep), pair), acc)
        b.store(b.add(b.load(i), ir.Constant(LL["int"], 1)), i)
        b.branch(cond)
        b.position_at_end(done)
        empty = b.icmp_signed("==", n, ir.Constant(LL["int"], 0))
        b.ret(b.select(empty, self.cstr("[:]"), self.call_c("pk_concat", "str", b.load(acc), self.cstr("]"))))
        self.builder = outer
        return fn

    def contains(self, e):
        item, it = self.expr(e.left)
        coll, ct = self.expr(e.right)
        b = self.builder
        if ct in ("[]", "[:]"):
            return ir.Constant(LL["bool"], 0), "bool"
        if ct == "str":
            if it != "str":
                raise PlankError(e.line, f"in on a str looks for a str, got {it}")
            hit = b.call(self.c("strstr", LL["str"], LL["str"], LL["str"]), [coll, item])
            return b.icmp_unsigned("!=", hit, ir.Constant(LL["str"], None)), "bool"
        if generic_name(ct) and generic_name(ct)[0] == "Set":
            return self.e_Method(Method(e.line, Given(e.line, coll, ct), "has", [Given(e.line, item, it)], [None]))
        kv = dict_kv(ct)
        if kv:
            slot = self.dict_slot(coll, kv, item, it, e.line, "pk_dict_find")
            return b.icmp_unsigned("!=", slot, ir.Constant(slot.type, None)), "bool"
        if is_list(ct):
            if not fits(it, ct[1:-1]):
                raise PlankError(e.line, f"this list holds {ct[1:-1]}, got {it}")
            at = self.find_index(coll, ct[1:-1], self.coerce(item, it, ct[1:-1]))
            return b.icmp_signed(">=", at, ir.Constant(LL["int"], 0)), "bool"
        raise PlankError(e.line, f"in needs a list, a dict or a str on the right, got {ct}")

    def each(self, lst, elem, body):
        """Emit a loop over lst calling body(item) to emit the inside."""
        b = self.builder
        with b.goto_entry_block():
            i = b.alloca(LL["int"])
        b.store(ir.Constant(LL["int"], 0), i)
        cond, inside, done = (b.append_basic_block(n) for n in ("each", "item", "done"))
        b.branch(cond)
        b.position_at_end(cond)
        b.cbranch(b.icmp_signed("<", b.load(i), self.list_len(lst)), inside, done)
        b.position_at_end(inside)
        body(b.load(self.slot(lst, b.load(i), elem)))
        b.store(b.add(b.load(i), ir.Constant(LL["int"], 1)), i)
        b.branch(cond)
        b.position_at_end(done)

    def fn_arg(self, e, want):
        if len(e.args) != 1:
            raise PlankError(e.line, f"{e.name}() takes one function")
        clo, ty = self.expr(e.args[0], hint=want)
        sig, wsig = fn_sig(ty), fn_sig(want)
        if sig is None or sig[0] != wsig[0] or (wsig[1] != "_" and sig[1] != wsig[1]):
            raise PlankError(e.line, f"{e.name}() wants a {want.replace('_', 'value')}, got {ty}")
        return clo, ty

    def list_fn(self, e, lst, elem):
        b = self.builder
        new = self.c("pk_list_new", LIST, LL["int"], LL["int"])
        if e.name == "map":
            clo, ty = self.fn_arg(e, f"fn({elem}) -> _")
            ret = fn_sig(ty)[1]
            if ret == "void":
                raise PlankError(e.line, "map() needs a function that returns something")
            out = b.call(new, [self.list_len(lst), ir.Constant(LL["int"], size(ret))])
            self.each(lst, elem, lambda x: self.push(out, self.invoke(clo, ty, [x])[0], ret))
            return out, f"[{ret}]"
        if e.name == "filter":
            clo, ty = self.fn_arg(e, f"fn({elem}) -> bool")
            out = b.call(new, [ir.Constant(LL["int"], 0), ir.Constant(LL["int"], size(elem))])
            def keep(x):
                with b.if_then(self.invoke(clo, ty, [x])[0]):
                    self.push(out, x, elem)
            self.each(lst, elem, keep)
            return out, f"[{elem}]"
        if e.name == "reduce":
            if len(e.args) != 2:
                raise PlankError(e.line, "reduce() takes a starting value and a function: xs.reduce(0, fn(acc, x) => acc + x)")
            start, st = self.expr(e.args[0])
            clo, ty = self.expr(e.args[1], hint=f"fn({st}, {elem}) -> {st}")
            if fn_sig(ty) != ([st, elem], st):
                raise PlankError(e.line, f"reduce() wants a fn({st}, {elem}) -> {st}, got {ty}")
            with b.goto_entry_block():
                acc = b.alloca(self.ll(st))
            b.store(start, acc)
            self.each(lst, elem, lambda x: b.store(self.invoke(clo, ty, [b.load(acc), x])[0], acc))
            return b.load(acc), st
        # sort in place, sorted gives a copy; both take an optional by: fn(a, b) -> bool, a goes first
        if e.name == "sorted":
            lst = self.call_c("pk_list_copy", LIST, lst, ir.Constant(LL["int"], size(elem)))
        if e.args:
            if e.labels != ["by"]:
                raise PlankError(e.line, f"{e.name}() takes by: fn(a, b) -> bool, or nothing")
            clo, ty = self.expr(e.args[0], hint=f"fn({elem}, {elem}) -> bool")
            if fn_sig(ty) != ([elem, elem], "bool"):
                raise PlankError(e.line, f"{e.name}(by:) wants a fn({elem}, {elem}) -> bool, got {ty}")
            less, env = self.less_by(elem, ty), b.bitcast(clo, LL["str"])
        else:
            if elem not in ("int", "float", "str"):
                raise PlankError(e.line, f"{e.name}() on {elem} needs by: fn(a, b) -> bool to say the order")
            less, env = self.less_by(elem, None), ir.Constant(LL["str"], None)
        sort = self.c("pk_list_sort", ir.VoidType(), LIST, LL["int"], LL["str"], LL["str"])
        b.call(sort, [lst, ir.Constant(LL["int"], size(elem)), b.bitcast(less, LL["str"]), env])
        return (lst, f"[{elem}]") if e.name == "sorted" else (None, "void")

    def less_by(self, elem, ty):
        """A C-callable less(env, a, b) for the runtime's sort: natural order, or a Plank closure in env."""
        name = f"less.{elem}" if ty is None else f"less.{ty}"
        if name in self.module.globals:
            return self.module.globals[name]
        fn = ir.Function(self.module, ir.FunctionType(LL["int"], [LL["str"]] * 3), name)
        fn.linkage = "private"
        outer, self.builder = self.builder, ir.IRBuilder(fn.append_basic_block())
        b = self.builder
        a, c = (b.load(b.bitcast(p, self.ll(elem).as_pointer())) for p in fn.args[1:])
        if ty is not None:
            res = self.invoke(b.bitcast(fn.args[0], CLOSURE), ty, [a, c])[0]
        elif elem == "float":
            res = b.fcmp_ordered("<", a, c)
        elif elem == "str":
            res = b.icmp_signed("<", b.call(self.c("strcmp", I32, LL["str"], LL["str"]), [a, c]), ir.Constant(I32, 0))
        else:
            res = b.icmp_signed("<", a, c)
        b.ret(b.zext(res, LL["int"]))
        self.builder = outer
        return fn

    def list_helper(self, e, lst, elem, args):
        """first, last, index_of, insert, remove_at, reverse, reversed, sum, min, max. None if e.name is not one."""
        b, n = self.builder, e.name
        sz = ir.Constant(LL["int"], size(elem))
        tys = [t for _, t in args]
        if n == "enumerate" and not args:  # [(int, T)]
            pair_ty = f"(int, {elem})"
            self.tuple_struct(pair_ty, e.line)
            out = b.call(self.c("pk_list_new", LIST, LL["int"], LL["int"]), [self.list_len(lst), ir.Constant(LL["int"], 8)])
            with b.goto_entry_block():
                i = b.alloca(LL["int"])
            b.store(ir.Constant(LL["int"], 0), i)
            def add(x):
                pair = self.construct(Call(e.line, pair_ty, [Given(e.line, b.load(i), "int"), Given(e.line, x, elem)], [None, None]))
                self.push(out, pair, pair_ty)
                b.store(b.add(b.load(i), ir.Constant(LL["int"], 1)), i)
            self.each(lst, elem, add)
            return out, f"[{pair_ty}]"
        if n in ("first", "last") and not args:
            i = ir.Constant(LL["int"], 0 if n == "first" else -1)
            length = self.list_len(lst)
            with b.if_else(b.icmp_signed("==", length, ir.Constant(LL["int"], 0))) as (empty, some):
                with empty:
                    none, none_bb = ir.Constant(self.ll(elem + "?"), None), b.block
                with some:
                    at = b.select(b.icmp_signed("<", i, ir.Constant(LL["int"], 0)), b.add(i, length), i)
                    val, val_bb = self.coerce(b.load(self.slot(lst, at, elem)), elem, elem + "?"), b.block
            phi = b.phi(self.ll(elem + "?"))
            phi.add_incoming(none, none_bb)
            phi.add_incoming(val, val_bb)
            return phi, elem + "?"
        if n == "index_of" and len(args) == 1:
            if not fits(tys[0], elem):
                raise PlankError(e.line, f"index_of() on a list of {elem} wants a {elem}, got {tys[0]}")
            return self.maybe_int(self.find_index(lst, elem, self.coerce(args[0][0], tys[0], elem)))
        if n == "insert" and len(args) == 2:
            if tys[0] != "int" or not fits(tys[1], elem):
                raise PlankError(e.line, f"insert(i, x) takes an int and {'an' if elem[0] in 'aeiou' else 'a'} {elem}, got {tys[0]} and {tys[1]}")
            fn = self.c("pk_list_insert", LL["str"], LIST, LL["int"], LL["int"], LL["str"], LL["int"])
            slot = b.call(fn, [lst, sz, args[0][0]] + self.where(e.line))
            b.store(self.coerce(args[1][0], tys[1], elem), b.bitcast(slot, self.ll(elem).as_pointer()))
            return None, "void"
        if n == "remove_at" and len(args) == 1 and tys[0] == "int":
            fn = self.c("pk_list_remove_at", LL["str"], LIST, LL["int"], LL["int"], LL["str"], LL["int"])
            slot = b.call(fn, [lst, sz, args[0][0]] + self.where(e.line))
            return b.load(b.bitcast(slot, self.ll(elem).as_pointer())), elem
        if n in ("reverse", "reversed") and not args:
            if n == "reversed":
                lst = self.call_c("pk_list_copy", LIST, lst, sz)
            b.call(self.c("pk_list_reverse", ir.VoidType(), LIST, LL["int"]), [lst, sz])
            return (lst, f"[{elem}]") if n == "reversed" else (None, "void")
        if n == "sum" and not args:
            if elem not in ("int", "float"):
                raise PlankError(e.line, f"sum() needs a list of int or float, got [{elem}]")
            with b.goto_entry_block():
                acc = b.alloca(self.ll(elem))
            b.store(ir.Constant(self.ll(elem), 0), acc)
            add = (lambda x: b.store(b.fadd(b.load(acc), x), acc)) if elem == "float" else (lambda x: b.store(b.add(b.load(acc), x), acc))
            self.each(lst, elem, add)
            return b.load(acc), elem
        if n in ("min", "max") and not args:
            if elem not in ("int", "float", "str"):
                raise PlankError(e.line, f"{n}() needs a list of int, float or str, got [{elem}]")
            ordered = self.list_fn(Method(e.line, Given(e.line, lst, f"[{elem}]"), "sorted", [], []), lst, elem)[0]
            return self.list_helper(Method(e.line, e.target, "first" if n == "min" else "last", [], []), ordered, elem, [])
        return None

    def find_index(self, lst, elem, needle):
        """The index of the first item equal to needle, part by part, or -1."""
        b = self.builder
        with b.goto_entry_block():
            found, i = b.alloca(LL["int"]), b.alloca(LL["int"])
        b.store(ir.Constant(LL["int"], -1), found)
        b.store(ir.Constant(LL["int"], 0), i)
        cond, body, done = (b.append_basic_block(k) for k in ("find", "item", "found"))
        b.branch(cond)
        b.position_at_end(cond)
        going = b.and_(b.icmp_signed("<", b.load(i), self.list_len(lst)), b.icmp_signed("<", b.load(found), ir.Constant(LL["int"], 0)))
        b.cbranch(going, body, done)
        b.position_at_end(body)
        with b.if_then(self.equal(b.load(self.slot(lst, b.load(i), elem)), needle, elem)):
            b.store(b.load(i), found)
        b.store(b.add(b.load(i), ir.Constant(LL["int"], 1)), i)
        b.branch(cond)
        b.position_at_end(done)
        return b.load(found)

    def maybe_int(self, at):
        """An int that is -1 for missing, as an int?."""
        b = self.builder
        found = b.icmp_signed(">=", at, ir.Constant(LL["int"], 0))
        with b.if_else(found) as (yes, no):
            with yes:
                some, some_bb = self.coerce(at, "int", "int?"), b.block
            with no:
                no_bb = b.block
        phi = b.phi(self.ll("int?"))
        phi.add_incoming(some, some_bb)
        phi.add_incoming(ir.Constant(self.ll("int?"), None), no_bb)
        return phi, "int?"

    def push(self, lst, val, elem):
        grow = self.c("pk_list_push", LL["str"], LIST, LL["int"])
        at = self.builder.call(grow, [lst, ir.Constant(LL["int"], size(elem))])
        self.builder.store(val, self.builder.bitcast(at, self.ll(elem).as_pointer()))

    def e_Method(self, e):
        if isinstance(e.target, Name) and e.target.name in self.modules and self.find(e.target.name) is None:
            return self.e_Call(Call(e.line, f"{e.target.name}.{e.name}", e.args, e.labels))  # x.parse(...), x.Point(...)
        if self.is_enum_name(e.target):
            return self.make_case(e, self.qualified(e.target), e.name, e)
        target, ty = self.expr(e.target)
        if f"{ty}.{e.name}" in self.generics:
            return self.call_generic(Call(e.line, f"{ty}.{e.name}", [Given(e.line, target, ty)] + e.args, [None] + e.labels))
        if ty in self.structs or ty in self.enums:
            sig = self.fns.get(f"{ty}.{e.name}")
            if sig is None:
                raise PlankError(e.line, f"{ty} has no method {e.name}()")
            vals = self.arrange(e, f"{e.name}()", sig.params[1:], sig.defaults)
            return self.builder.call(sig.func, [target] + vals), sig.ret
        if is_list(ty) and ty != "[]" and e.name in ("map", "filter", "reduce", "sort", "sorted"):
            return self.list_fn(e, target, ty[1:-1])
        if any(e.labels):
            raise PlankError(e.line, f"{e.name}() does not take labels")
        args = [self.expr(a) for a in e.args]
        if ty == "str":
            return self.str_method(e, target, args)
        if ty == "[str]" and e.name == "join":
            if len(args) > 1 or (args and args[0][1] != "str"):
                raise PlankError(e.line, "join() takes one str to put between the items")
            return self.call_c("pk_join", "str", target, args[0][0] if args else self.cstr("")), "str"
        if dict_kv(ty):
            return self.dict_method(e, target, dict_kv(ty), args)
        if is_list(ty) and ty != "[]":
            elem = ty[1:-1]
            if e.name == "append":
                if len(args) != 1 or not fits(args[0][1], elem):
                    raise PlankError(e.line, f"append() takes one {elem}")
                self.push(target, self.coerce(args[0][0], args[0][1], elem), elem)
                return None, "void"
            if e.name in ("map", "filter", "reduce", "sort", "sorted"):
                return self.list_fn(e, target, elem)
            helper = self.list_helper(e, target, elem, args)
            if helper is not None:
                return helper
            if e.name == "pop" and not args:
                pop = self.c("pk_list_pop", LL["str"], LIST, LL["int"], LL["str"], LL["int"])
                at = self.builder.call(pop, [target, ir.Constant(LL["int"], size(elem))] + self.where(e.line))
                return self.builder.load(self.builder.bitcast(at, self.ll(elem).as_pointer())), elem
        raise PlankError(e.line, f"{ty} has no method {e.name}()")

    def show_list(self, ty):
        """A private function that turns one list type into text: [1, 2, 3], ["a", "b"]."""
        name = "show" + ty
        if name in self.module.globals:
            return self.module.globals[name]
        fn = ir.Function(self.module, ir.FunctionType(LL["str"], [LIST]), name)
        fn.linkage = "private"
        outer, self.builder = self.builder, ir.IRBuilder(fn.append_basic_block("entry"))
        b, lst, elem = self.builder, fn.args[0], ty[1:-1]
        acc, i = b.alloca(LL["str"]), b.alloca(LL["int"])
        b.store(self.cstr("["), acc)
        b.store(ir.Constant(LL["int"], 0), i)
        cond, body, done = (fn.append_basic_block(n) for n in ("cond", "body", "done"))
        b.branch(cond)
        b.position_at_end(cond)
        b.cbranch(b.icmp_signed("<", b.load(i), self.list_len(lst)), body, done)
        b.position_at_end(body)
        first = b.icmp_signed("==", b.load(i), ir.Constant(LL["int"], 0))
        text = self.to_str(b.load(self.slot(lst, b.load(i), elem)), elem)
        if elem == "str":
            text = self.call_c("pk_concat", "str", self.call_c("pk_concat", "str", self.cstr('"'), text), self.cstr('"'))
        sep = b.select(first, self.cstr(""), self.cstr(", "))
        b.store(self.call_c("pk_concat", "str", self.call_c("pk_concat", "str", b.load(acc), sep), text), acc)
        b.store(b.add(b.load(i), ir.Constant(LL["int"], 1)), i)
        b.branch(cond)
        b.position_at_end(done)
        b.ret(self.call_c("pk_concat", "str", b.load(acc), self.cstr("]")))
        self.builder = outer
        return fn

    def e_Given(self, e):
        return e.val, e.ty

    def make_case(self, e, ename, case, args_node):
        info = self.enums[ename]
        tag, fields = info.case(case)
        if tag is None:
            raise PlankError(e.line, f"{ename} has no case {case}; it has {', '.join(c for c, _ in info.cases)}")
        if args_node is None and fields:
            raise PlankError(e.line, f"{ename}.{case} carries {', '.join(f'{n}: {t}' for n, t in fields)}; pass them in ()")
        vals = self.arrange(args_node, f"{ename}.{case}", fields, {}) if args_node else []
        b = self.builder
        ptr_ty = info.type.as_pointer()
        nbytes = b.ptrtoint(b.gep(ir.Constant(ptr_ty, None), [ir.Constant(I32, 1)]), LL["int"])
        obj = b.bitcast(self.call_c("pk_alloc", "str", nbytes), ptr_ty)
        b.store(ir.Constant(LL["int"], tag), b.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        for i, (v, (_, fty)) in enumerate(zip(vals, fields)):
            slot = b.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, 1 + i)])
            b.store(v, b.bitcast(slot, self.ll(fty).as_pointer()))
        return obj, ename

    def qualified(self, node):
        """A type or function spelled as a name, or module.Name; None when it is a variable or anything else."""
        if isinstance(node, Name) and not any(node.name in sc for sc in self.scopes):
            return node.name
        if isinstance(node, Field) and isinstance(node.target, Name) and node.target.name in self.modules and self.find(node.target.name) is None:
            return f"{node.target.name}.{node.name}"
        return None

    def is_enum_name(self, node):
        return self.qualified(node) in self.enums

    def show_enum(self, ty):
        """circle(r: 2), or just empty, the way Swift prints a case."""
        name = "show." + ty
        if name in self.module.globals:
            return self.module.globals[name]
        fn = ir.Function(self.module, ir.FunctionType(LL["str"], [self.ll(ty)]), name)
        fn.linkage = "private"
        outer, self.builder = self.builder, ir.IRBuilder(fn.append_basic_block("entry"))
        b, obj, info = self.builder, fn.args[0], self.enums[ty]
        tag = b.load(b.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        bad = fn.append_basic_block("bad")
        switch = b.switch(tag, bad)
        for t, (case, fields) in enumerate(info.cases):
            bb = fn.append_basic_block(case)
            switch.add_case(ir.Constant(LL["int"], t), bb)
            b.position_at_end(bb)
            out = self.cstr(case + ("(" if fields else ""))
            for i, (fname, fty) in enumerate(fields):
                slot = b.bitcast(b.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, 1 + i)]), self.ll(fty).as_pointer())
                label = (", " if i else "") + fname + ": "
                out = self.call_c("pk_concat", "str", self.call_c("pk_concat", "str", out, self.cstr(label)), self.quoted(b.load(slot), fty))
            b.ret(self.call_c("pk_concat", "str", out, self.cstr(")")) if fields else out)
        b.position_at_end(bad)
        b.unreachable()
        self.builder = outer
        return fn

    def e_IfExpr(self, e):
        cond = self.cond(e.cond)
        b = self.builder
        with b.if_else(cond) as (yes, no):
            with yes:
                a, at = self.expr(e.then)
                a_bb = b.block
            with no:
                c, ct = self.expr(e.other)
                c_bb = b.block
        return self.join(e, a, at, a_bb, c, ct, c_bb)

    def e_IfLetExpr(self, e):
        val, ty = self.expr(e.expr)
        if not ty.endswith("?"):
            raise PlankError(e.line, f"if let unwraps an optional, {ty} is never nil; use a plain if")
        b = self.builder
        with b.if_else(b.icmp_unsigned("!=", val, ir.Constant(val.type, None))) as (yes, no):
            with yes:
                self.scopes.append({})
                b.store(b.load(val), self.declare(e.name, ty[:-1], False, e.line))
                a, at = self.expr(e.then)
                self.scopes.pop()
                a_bb = b.block
            with no:
                c, ct = self.expr(e.other)
                c_bb = b.block
        return self.join(e, a, at, a_bb, c, ct, c_bb)

    def join(self, e, a, at, a_bb, c, ct, c_bb):
        """Two branch values into one: agree on a type, coerce each in its own block, phi at the merge."""
        b = self.builder
        if at == ct:
            ty = at
        elif "nil" in (at, ct):
            other = ct if at == "nil" else at
            ty = other if other.endswith("?") else other + "?"
        elif fits(at, ct):
            ty = ct
        elif fits(ct, at):
            ty = at
        else:
            raise PlankError(e.line, f"the two sides of this if are {at} and {ct}; they need to be the same type")
        if ty == "nil":
            raise PlankError(e.line, "both sides of this if are nil, so it has no type")
        with b.goto_block(a_bb):
            a = self.coerce(a, at, ty)
        with b.goto_block(c_bb):
            c = self.coerce(c, ct, ty)
        phi = b.phi(self.ll(ty))
        phi.add_incoming(a, a_bb)
        phi.add_incoming(c, c_bb)
        return phi, ty

    def tuple_struct(self, ty, line=0):
        """(int, str) as a struct with fields _0 and _1, made the first time the type is named."""
        if ty not in self.structs:
            parts = tuple_parts(ty)
            ll_type = self.module.context.get_identified_type(ty)
            self.structs[ty] = StructInfo(ll_type, [(f"_{i}", t) for i, t in enumerate(parts)], {})
            ll_type.set_body(*[self.ll(t, line) for t in parts])
        return self.structs[ty].type

    def e_Tuple(self, e):
        items = [self.expr(x) for x in e.items]
        for x, (_, t) in zip(e.items, items):
            if t in ("nil", "[]", "[:]"):
                raise PlankError(x.line, f"a tuple part cannot be a bare {t}; give it a type first, like let x: int? = nil")
        ty = f"({', '.join(t for _, t in items)})"
        self.tuple_struct(ty, e.line)
        return self.construct(Call(e.line, ty, [Given(e.line, v, t) for v, t in items], [None] * len(items))), ty

    def s_LetTuple(self, s):
        val, ty = self.expr(s.expr)
        parts = tuple_parts(ty)
        if parts is None:
            raise PlankError(s.line, f"let ({', '.join(s.names)}) needs a tuple on the right, got {ty}")
        if len(parts) != len(s.names):
            raise PlankError(s.line, f"this tuple has {len(parts)} parts, the let names {len(s.names)}")
        b = self.builder
        for i, (name, t) in enumerate(zip(s.names, parts)):
            b.store(b.load(b.gep(val, [ir.Constant(I32, 0), ir.Constant(I32, i)])), self.declare(name, t, s.mutable, s.line))

    def show_tuple(self, ty):
        name = "show." + ty
        if name in self.module.globals:
            return self.module.globals[name]
        fn = ir.Function(self.module, ir.FunctionType(LL["str"], [self.ll(ty)]), name)
        fn.linkage = "private"
        outer, self.builder = self.builder, ir.IRBuilder(fn.append_basic_block("entry"))
        b = self.builder
        out = self.cstr("(")
        for i, t in enumerate(tuple_parts(ty)):
            part = self.quoted(b.load(b.gep(fn.args[0], [ir.Constant(I32, 0), ir.Constant(I32, i)])), t)
            out = self.call_c("pk_concat", "str", self.call_c("pk_concat", "str", out, self.cstr(", " if i else "")), part)
        b.ret(self.call_c("pk_concat", "str", out, self.cstr(")")))
        self.builder = outer
        return fn

    def e_OptChain(self, e):
        """p?.x or p?.m(): the field or call on the value inside, or nil when the chain hits nil."""
        val, ty = self.expr(e.target)
        if not ty.endswith("?"):
            raise PlankError(e.line, f"?. is for an optional, and {ty} is never nil; use a plain .")
        b = self.builder
        inner = Given(e.line, None, ty[:-1])
        with b.if_else(b.icmp_unsigned("!=", val, ir.Constant(val.type, None))) as (some, none):
            with some:
                inner.val = b.load(val)
                if e.args is None:
                    got, gt = self.e_Field(Field(e.line, inner, e.name))
                else:
                    got, gt = self.e_Method(Method(e.line, inner, e.name, e.args, e.labels))
                if gt == "void":
                    raise PlankError(e.line, f"{e.name}() returns nothing, so p?.{e.name}() has no value; use if let")
                want = gt if gt.endswith("?") else gt + "?"
                got, some_bb = self.coerce(got, gt, want), b.block
            with none:
                none_bb = b.block
        phi = b.phi(self.ll(want))
        phi.add_incoming(got, some_bb)
        phi.add_incoming(ir.Constant(self.ll(want), None), none_bb)
        return phi, want

    # -- equality that looks inside
    def deep(self, ty):
        return bool(is_list(ty) or dict_kv(ty) or tuple_parts(ty) or ty in self.structs or ty in self.enums or ty.endswith("?"))

    def equal(self, a, c, ty):
        """An i1: are these two values of type ty the same, part by part?"""
        b = self.builder
        if ty == "float":
            return b.fcmp_ordered("==", a, c)
        if ty == "str":
            return b.icmp_signed("==", b.call(self.c("strcmp", I32, LL["str"], LL["str"]), [a, c]), ir.Constant(I32, 0))
        if ty in ("int", "bool") or fn_sig(ty):
            return b.icmp_signed("==", a, c) if ty in ("int", "bool") else b.icmp_unsigned("==", a, c)
        return b.call(self.eq_fn(ty), [a, c])

    def eq_fn(self, ty):
        """A private function eq.<ty>(a, b) -> i1, made once; registered before its body so a type that holds itself can use it."""
        name = "eq." + ty
        if name in self.module.globals:
            return self.module.globals[name]
        fn = ir.Function(self.module, ir.FunctionType(LL["bool"], [self.ll(ty), self.ll(ty)]), name)
        fn.linkage = "private"
        outer, self.builder = self.builder, ir.IRBuilder(fn.append_basic_block("entry"))
        b, (a, c) = self.builder, fn.args
        no, yes = ir.Constant(LL["bool"], 0), ir.Constant(LL["bool"], 1)
        def part(x, y, t):
            with b.if_then(b.not_(self.equal(x, y, t))):
                b.ret(no)
        if ty.endswith("?"):
            inner = ty[:-1]
            a_nil, c_nil = (b.icmp_unsigned("==", v, ir.Constant(v.type, None)) for v in (a, c))
            with b.if_then(b.and_(a_nil, c_nil)):
                b.ret(yes)
            with b.if_then(b.or_(a_nil, c_nil)):
                b.ret(no)
            part(b.load(a), b.load(c), inner)
            b.ret(yes)
        elif is_list(ty):
            elem = ty[1:-1]
            with b.if_then(b.icmp_signed("!=", self.list_len(a), self.list_len(c))):
                b.ret(no)
            with b.goto_entry_block():
                i = b.alloca(LL["int"])
            b.store(ir.Constant(LL["int"], 0), i)
            cond, body, done = (fn.append_basic_block(k) for k in ("cond", "body", "done"))
            b.branch(cond)
            b.position_at_end(cond)
            b.cbranch(b.icmp_signed("<", b.load(i), self.list_len(a)), body, done)
            b.position_at_end(body)
            part(b.load(self.slot(a, b.load(i), elem)), b.load(self.slot(c, b.load(i), elem)), elem)
            b.store(b.add(b.load(i), ir.Constant(LL["int"], 1)), i)
            b.branch(cond)
            b.position_at_end(done)
            b.ret(yes)
        elif dict_kv(ty):
            kv = dict_kv(ty)
            with b.if_then(b.icmp_signed("!=", self.call_c("pk_dict_len", "int", a), self.call_c("pk_dict_len", "int", c))):
                b.ret(no)
            keys = self.call_c("pk_dict_keys", LIST, a)
            def check(key):
                slot = self.dict_slot(c, kv, key, kv[0], 0, "pk_dict_find")
                with b.if_then(b.icmp_unsigned("==", slot, ir.Constant(slot.type, None))):
                    b.ret(no)
                part(b.load(self.dict_slot(a, kv, key, kv[0], 0, "pk_dict_find")), b.load(slot), kv[1])
            self.each(keys, kv[0], check)
            b.ret(yes)
        elif ty in self.structs:
            for i, (_, fty) in enumerate(self.structs[ty].fields):
                x, y = (b.load(b.gep(v, [ir.Constant(I32, 0), ir.Constant(I32, i)])) for v in (a, c))
                part(x, y, fty)
            b.ret(yes)
        else:  # an enum: same case, then the same values
            info = self.enums[ty]
            ta, tc = (b.load(b.gep(v, [ir.Constant(I32, 0), ir.Constant(I32, 0)])) for v in (a, c))
            with b.if_then(b.icmp_signed("!=", ta, tc)):
                b.ret(no)
            bad = fn.append_basic_block("bad")
            sw = b.switch(ta, bad)
            for tag, (case, fields) in enumerate(info.cases):
                bb = fn.append_basic_block(case)
                sw.add_case(ir.Constant(LL["int"], tag), bb)
                b.position_at_end(bb)
                for i, (_, fty) in enumerate(fields):
                    x, y = (b.load(b.bitcast(b.gep(v, [ir.Constant(I32, 0), ir.Constant(I32, 1 + i)]), self.ll(fty).as_pointer())) for v in (a, c))
                    part(x, y, fty)
                b.ret(yes)
            b.position_at_end(bad)
            b.unreachable()
        self.builder = outer
        return fn

    def e_Nil(self, e):
        return ir.Constant(LL["str"], None), "nil"

    def e_Unwrap(self, e):
        val, ty = self.expr(e.expr)
        if not ty.endswith("?"):
            raise PlankError(e.line, f"! unwraps an optional, and {ty} is not one")
        b = self.builder
        with b.if_then(b.icmp_unsigned("==", val, ir.Constant(val.type, None)), likely=False):
            panic = self.c("pk_panic", ir.VoidType(), LL["str"], LL["int"], LL["str"])
            b.call(panic, self.where(e.line) + [self.cstr("unwrapped nil with !")])
            b.unreachable()
        return b.load(val), ty[:-1]

    def coalesce(self, e):
        """a ?? b: a's value if it has one, otherwise b, which only runs when needed."""
        val, ty = self.expr(e.left)
        if not ty.endswith("?"):
            raise PlankError(e.line, f"?? needs an optional on the left, {ty} is never nil")
        b = self.builder
        with b.if_else(b.icmp_unsigned("==", val, ir.Constant(val.type, None))) as (none, some):
            with none:
                alt, at = self.expr(e.right)
                result = ty if at == ty else ty[:-1]
                if not fits(at, result):
                    raise PlankError(e.line, f"?? fallback should be {ty[:-1]}, got {at}")
                alt, none_bb = self.coerce(alt, at, result), b.block
            with some:
                got, some_bb = (val if result == ty else b.load(val)), b.block
        phi = b.phi(self.ll(result))
        phi.add_incoming(alt, none_bb)
        phi.add_incoming(got, some_bb)
        return phi, result

    def show_optional(self, ty):
        name = "show." + ty
        if name in self.module.globals:
            return self.module.globals[name]
        fn = ir.Function(self.module, ir.FunctionType(LL["str"], [self.ll(ty)]), name)
        fn.linkage = "private"
        outer, self.builder = self.builder, ir.IRBuilder(fn.append_basic_block("entry"))
        b, val = self.builder, fn.args[0]
        with b.if_then(b.icmp_unsigned("==", val, ir.Constant(val.type, None))):
            b.ret(self.cstr("nil"))
        b.ret(self.to_str(b.load(val), ty[:-1]))
        self.builder = outer
        return fn

    def e_Bool(self, e):
        return ir.Constant(LL["bool"], int(e.val)), "bool"

    def e_Name(self, e):
        if e.name in self.fns and not any(e.name in sc for sc in self.scopes):
            return self.fn_value(e.name)
        var = self.lookup(e.name, e.line)
        return self.builder.load(var.ptr, name=e.name), var.ty

    def fn_value_error(self, e, full):
        raise PlankError(e.line, f"{full} is generic; call it, or wrap it: fn(x) => {full}(x)")

    def fn_value(self, name):
        """A top-level function used as a value: a constant closure around a small wrapper."""
        sig = self.fns[name]
        ty = f"fn({', '.join(t for _, t in sig.params)}) -> {sig.ret}"
        gname = "closure." + name
        if gname not in self.module.globals:
            wrap_ty = ir.FunctionType(self.ll(sig.ret), [LL["str"]] + [self.ll(t) for _, t in sig.params])
            wrap = ir.Function(self.module, wrap_ty, "wrap." + name)
            wrap.linkage = "private"
            wb = ir.IRBuilder(wrap.append_basic_block())
            res = wb.call(sig.func, wrap.args[1:])
            wb.ret_void() if sig.ret == "void" else wb.ret(res)
            g = ir.GlobalVariable(self.module, CLOSURE.pointee, gname)
            g.global_constant, g.linkage = True, "private"
            g.initializer = ir.Constant(CLOSURE.pointee, [wrap.bitcast(LL["str"]), ir.Constant(LL["str"], None)])
        return self.module.globals[gname], ty

    def invoke(self, clo, ty, vals):
        """Call a closure with already-computed argument values."""
        params, ret = fn_sig(ty)
        b = self.builder
        code = b.load(b.gep(clo, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        env = b.load(b.gep(clo, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
        fty = ir.FunctionType(self.ll(ret), [LL["str"]] + [self.ll(t) for t in params])
        return b.call(b.bitcast(code, fty.as_pointer()), [env] + vals), ret

    def call_value(self, clo, ty, args, line, what):
        sig = fn_sig(ty)
        if sig is None:
            raise PlankError(line, f"{what} is {ty}, not a function")
        params, _ = sig
        if len(args) != len(params):
            raise PlankError(line, f"{what} takes {len(params)} argument{'s' * (len(params) != 1)}, got {len(args)}")
        vals = []
        for arg, want in zip(args, params):
            val, got = self.expr(arg, hint=want)
            if not fits(got, want):
                raise PlankError(line, f"{what} wants {want}, got {got}")
            vals.append(self.coerce(val, got, want))
        return self.invoke(clo, ty, vals)

    def e_CallValue(self, e):
        clo, ty = self.expr(e.target)
        return self.call_value(clo, ty, e.args, e.line, "this")

    def e_Lambda(self, e, hint=None):
        hinted = fn_sig(hint) if hint else None
        params = []
        for i, (name, ty) in enumerate(e.params):
            if ty is None:
                if not hinted or i >= len(hinted[0]):
                    raise PlankError(e.line, f"say what type {name} is: fn({name}: int) => ...")
                ty = hinted[0][i]
            params.append((name, ty))
        ret = e.ret
        if ret is None and hinted and hinted[1] != "_":
            ret = hinted[1]
        if ret is None:  # fn(x) => expr: work the type out by compiling the expression once, then throw that away
            probe = self.lambda_fn(e, params, None)
            ret = self.probed
            del self.module.globals[probe.name]
        func = self.lambda_fn(e, params, ret)
        free = [(n, v) for n in sorted({x.name for x in walk(e.body) if isinstance(x, (Name, Call))} - {p for p, _ in params})
                for v in [self.find(n)] if v is not None]
        b = self.builder
        env = self.call_c("pk_alloc", "str", ir.Constant(LL["int"], 8 * max(len(free), 1)))
        slots = b.bitcast(env, LL["str"].as_pointer())
        for i, (_, var) in enumerate(free):
            b.store(b.bitcast(var.ptr, LL["str"]), b.gep(slots, [ir.Constant(LL["int"], i)]))
        clo = b.bitcast(self.call_c("pk_alloc", "str", ir.Constant(LL["int"], 16)), CLOSURE)
        b.store(b.bitcast(func, LL["str"]), b.gep(clo, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        b.store(env, b.gep(clo, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
        return clo, f"fn({', '.join(t for _, t in params)}) -> {ret}"

    def find(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def lambda_fn(self, e, params, ret):
        """Compile a lambda body into its own function: (env, params...) -> ret. ret None is a probe run."""
        free = [(n, v) for n in sorted({x.name for x in walk(e.body) if isinstance(x, (Name, Call))} - {p for p, _ in params})
                for v in [self.find(n)] if v is not None]
        self.lambdas += 1
        fty = ir.FunctionType(self.ll(ret or "void"), [LL["str"]] + [self.ll(t, e.line) for _, t in params])
        func = ir.Function(self.module, fty, f"lambda.{self.lambdas}")
        func.linkage = "private"
        saved = self.builder, self.scopes, self.fn_ret, self.loops, self.captured, self.has_try, self.tries
        self.builder = ir.IRBuilder(func.append_basic_block("entry"))
        self.scopes, self.fn_ret, self.loops = [{}], ret, []
        self.has_try, self.tries = any(isinstance(n, Try) for n in walk(e.body)), 0
        self.captured = captures(e.body) | self.captured
        b = self.builder
        slots = b.bitcast(func.args[0], LL["str"].as_pointer())
        for i, (name, var) in enumerate(free):
            ptr = b.bitcast(b.load(b.gep(slots, [ir.Constant(LL["int"], i)])), var.ptr.type)
            self.scopes[0][name] = Var(ptr, var.ty, var.mutable)
        self.scopes.append({})
        for (name, ty), arg in zip(params, func.args[1:]):
            b.store(arg, self.declare(name, ty, False, e.line))
        try:
            if ret is None:  # a probe: compile the body once to learn what it returns, then throw it away
                self.fn_ret, self.probed = "_", "void"
                self.stmts(e.body)
                if not self.builder.block.is_terminated:
                    self.builder.unreachable()
            else:
                self.stmts(e.body)
                if not self.builder.block.is_terminated:
                    if ret != "void":
                        raise PlankError(e.line, f"this fn returns {ret} but can reach its end without returning")
                    self.builder.ret_void()
        finally:
            self.builder, self.scopes, self.fn_ret, self.loops, self.captured, self.has_try, self.tries = saved
        return func

    def e_Unary(self, e):
        val, ty = self.expr(e.expr)
        if e.op == "not":
            if ty != "bool":
                raise PlankError(e.line, f"not needs a bool, got {ty}")
            return self.builder.not_(val), "bool"
        if ty == "int":
            return self.builder.neg(val), ty
        if ty == "float":
            return self.builder.fneg(val), ty
        raise PlankError(e.line, f"cannot negate {ty}")

    def e_Binary(self, e):
        if e.op in ("and", "or"):
            return self.short_circuit(e)
        if e.op == "in":
            return self.contains(e)
        if e.op == "??":
            return self.coalesce(e)
        lhs, lt = self.expr(e.left)
        rhs, rt = self.expr(e.right)
        if e.op in ("==", "!=") and {lt, rt} - {"nil"} and (lt.endswith("?") != rt.endswith("?")) and "nil" not in (lt, rt):
            # an optional against a plain value: equal only when it holds one and that one matches
            opt, plain, pt = (lhs, rhs, rt) if lt.endswith("?") else (rhs, lhs, lt)
            if not fits(pt, (lt if lt.endswith("?") else rt)[:-1]):
                raise PlankError(e.line, f"{lt} {e.op} {rt}: these can never be equal")
            b = self.builder
            with b.if_else(b.icmp_unsigned("!=", opt, ir.Constant(opt.type, None))) as (some, none):
                with some:
                    eq, some_bb = self.e_Binary(Binary(e.line, "==", Given(e.line, b.load(opt), pt), Given(e.line, plain, pt)))[0], b.block
                with none:
                    none_bb = b.block
            phi = b.phi(LL["bool"])
            phi.add_incoming(eq, some_bb)
            phi.add_incoming(ir.Constant(LL["bool"], 0), none_bb)
            return (phi if e.op == "==" else b.not_(phi)), "bool"
        if "nil" in (lt, rt) and e.op in ("==", "!="):
            val, ty = (lhs, lt) if rt == "nil" else (rhs, rt)
            if ty == "nil":
                return ir.Constant(LL["bool"], int(e.op == "==")), "bool"
            if not ty.endswith("?"):
                raise PlankError(e.line, f"{ty} is never nil; only optionals like {ty}? can be")
            return self.builder.icmp_unsigned(e.op, val, ir.Constant(val.type, None)), "bool"
        if e.op in ("==", "!=") and rt in ("[]", "[:]") and (is_list(lt) or dict_kv(lt)):  # xs == []
            n = self.list_len(lhs) if is_list(lt) else self.call_c("pk_dict_len", "int", lhs)
            return self.builder.icmp_signed(e.op, n, ir.Constant(LL["int"], 0)), "bool"
        if lt != rt:
            fix = "str()" if "str" in (lt, rt) else "int() or float()"
            if lt.endswith("?") or rt.endswith("?"):
                fix = "if let, ?? or ! to get the value out of the optional first"
            raise PlankError(e.line, f"{lt} {e.op} {rt}: types must match, use {fix}")
        b = self.builder
        if e.op in ("==", "!=") and self.deep(lt):  # lists, dicts, tuples, structs, optionals and enums: part by part
            same = self.equal(lhs, rhs, lt)
            return (same if e.op == "==" else b.not_(same)), "bool"
        if lt == "str" and e.op == "+":
            return self.call_c("pk_concat", "str", lhs, rhs), "str"
        if lt == "str" and e.op in CMP:
            diff = b.call(self.c("strcmp", ir.IntType(32), LL["str"], LL["str"]), [lhs, rhs])  # C int, 32 bits
            return b.icmp_signed(e.op, diff, ir.Constant(diff.type, 0)), "bool"
        if e.op in CMP:
            if lt == "float":
                return b.fcmp_ordered(e.op, lhs, rhs), "bool"
            if lt == "bool" and e.op not in ("==", "!="):
                raise PlankError(e.line, f"cannot compare {lt} with {e.op}")
            return b.icmp_signed(e.op, lhs, rhs), "bool"
        if lt == "int":
            return getattr(b, INT_OPS[e.op])(lhs, rhs), lt
        if lt == "float":
            return getattr(b, FLOAT_OPS[e.op])(lhs, rhs), lt
        raise PlankError(e.line, f"{e.op} is not defined for {lt}")

    def short_circuit(self, e):
        b = self.builder
        lhs = self.cond(e.left)
        left_bb = b.block
        rhs_bb = b.append_basic_block(e.op)
        merge = b.append_basic_block("end" + e.op)
        if e.op == "and":
            b.cbranch(lhs, rhs_bb, merge)
        else:
            b.cbranch(lhs, merge, rhs_bb)
        b.position_at_end(rhs_bb)
        rhs = self.cond(e.right)
        rhs_end = b.block
        b.branch(merge)
        b.position_at_end(merge)
        phi = b.phi(LL["bool"])
        phi.add_incoming(ir.Constant(LL["bool"], int(e.op == "or")), left_bb)
        phi.add_incoming(rhs, rhs_end)
        return phi, "bool"

    def e_Call(self, e):
        b = self.builder
        var = self.find(e.name)
        if var is not None:
            if any(e.labels):
                raise PlankError(e.line, f"{e.name} is a closure, its arguments go by position")
            return self.call_value(b.load(var.ptr), var.ty, e.args, e.line, e.name)
        if e.name in self.fns:
            sig = self.fns[e.name]
            vals = self.arrange(e, f"{e.name}()", sig.params, sig.defaults)
            if e.name in self.externs:
                vals = [b.zext(v, I32) if t == "bool" else v for v, (_, t) in zip(vals, sig.params)]
                res = b.call(sig.func, vals)
                return (b.trunc(res, LL["bool"]) if sig.ret == "bool" else res), sig.ret
            return b.call(sig.func, vals), sig.ret
        if e.name in self.generics:
            return self.call_generic(e)
        if e.name in self.generic_structs:  # Stack(items: [1, 2]): T from the fields given
            g = self.generic_structs[e.name]
            binds, args, labels = self.bind_args(e, g.fields, g.tparams, e.name)
            ty = f"{e.name}<{', '.join(binds[t] for t in g.tparams)}>"
            self.instantiate_struct(ty, e.line)
            return self.construct(Call(e.line, ty, args, labels)), ty
        if e.name in self.structs or (generic_name(e.name) and self.instantiate_struct(e.name, e.line)):
            return self.construct(e), e.name
        if any(e.labels):
            raise PlankError(e.line, f"{e.name}() does not take labels")
        builtin = getattr(self, "b_" + e.name, None)
        if builtin is None:
            if "." in e.name and e.name.split(".")[0] in self.modules:
                alias, rest = e.name.split(".", 1)
                raise PlankError(e.line, f"module {alias} has nothing called {rest}")
            raise PlankError(e.line, f"unknown function {e.name!r}")
        args = []
        for a in e.args:
            val, ty = self.expr(a)
            if e.name == "print" and ty not in FMT:  # show a list as it is now, not after later arguments run
                val, ty = self.to_str(val, ty), "str"
            args.append((val, ty))
        return builtin(e, args)

    def instantiate_struct(self, ty, line=0):
        """Stack<int> from struct Stack<T>: register the struct and compile its methods, once. True if ty is such a type."""
        if ty in self.structs:
            return True
        base, args = generic_name(ty)
        g = self.generic_structs.get(base)
        if g is None:
            if base in self.structs or base in self.enums:
                raise PlankError(line, f"{base} is not generic, it takes no <>")
            return False
        if len(args) != len(g.tparams):
            raise PlankError(line, f"{base} takes {len(g.tparams)} type parameter{'s' * (len(g.tparams) != 1)}, got {len(args)}")
        binds = dict(zip(g.tparams, args))
        st = self.specialize(g, binds)
        ll_type = self.module.context.get_identified_type(ty)
        self.structs[ty] = StructInfo(ll_type, st.fields, st.defaults)
        ll_type.set_body(*[self.ll(t, line) for _, t in st.fields])
        keys = []
        for m in st.methods:
            key = f"{ty}.{m.name}"
            if m.tparams:
                self.generics[key] = with_self(m, ty)
                continue
            params = [("self", ty)] + m.params
            fty = ir.FunctionType(self.ll(m.ret, m.line), [self.ll(t, m.line) for _, t in params])
            self.fns[key] = Sig(ir.Function(self.module, fty, "pk." + key), params, m.ret, m.defaults)
            keys.append((key, m))
        saved = self.builder, self.scopes, self.fn_ret, self.loops, self.captured, self.has_try, self.tries
        try:
            for key, m in keys:
                self.function(key, m)
        finally:
            self.builder, self.scopes, self.fn_ret, self.loops, self.captured, self.has_try, self.tries = saved
        return True

    def bind_args(self, e, params, tparams, what):
        """Evaluate the non-closure arguments and bind type parameters from them. Returns binds, args, labels."""
        names = [n for n, _ in params]
        binds, args, labels = {}, [], []
        for i, (arg, label) in enumerate(zip(e.args, e.labels)):
            if isinstance(arg, Lambda):  # a lambda learns its types from the parameter, so it waits
                args.append(arg); labels.append(label)
                continue
            val, ty = self.expr(arg)
            name = label or (names[i] if i < len(names) else None)
            if name in names:
                self.unify(dict(params)[name], ty, tparams, binds, e.line, what)
            args.append(Given(arg.line, val, ty)); labels.append(label)
        def sub(ty):
            for t, real in binds.items():
                ty = re.sub(rf"\b{t}\b", real, ty)
            return ty
        def open_(ty):
            return any(re.search(rf"\b{t}\b", ty) for t in tparams if t not in binds)
        # a closure can pin down a parameter that only shows up in its result, like map<U>: compile it with
        # what is known so far and let its body say the rest
        for i, (arg, label) in enumerate(zip(args, labels)):
            name = label or (names[i] if i < len(names) else None)
            if not isinstance(arg, Lambda) or name not in names or not open_(dict(params)[name]):
                continue
            sig = fn_sig(dict(params)[name])
            if sig is None or any(open_(x) for x in sig[0]):
                continue
            hint = f"fn({', '.join(sub(x) for x in sig[0])}) -> {'_' if open_(sig[1]) else sub(sig[1])}"
            val, ty = self.expr(arg, hint=hint)
            self.unify(dict(params)[name], ty, tparams, binds, e.line, what)
            args[i] = Given(arg.line, val, ty)
        missing = [t for t in tparams if t not in binds]
        if missing:
            raise PlankError(e.line, f"cannot tell what {', '.join(missing)} is from the arguments to {what}; say it: {what.rstrip('()')}<int>(...)")
        return binds, args, labels

    def call_generic(self, e):
        """Work out the type parameters from the arguments, compile that version once, call it."""
        g = self.generics[e.name]
        binds, args, labels = self.bind_args(e, g.params, g.tparams, f"{e.name}()")
        key = f"{e.name}<{', '.join(binds[t] for t in g.tparams)}>"
        if key not in self.fns:
            f = self.specialize(g, binds)
            params = f.params
            fty = ir.FunctionType(self.ll(f.ret, f.line), [self.ll(t, f.line) for _, t in params])
            self.fns[key] = Sig(ir.Function(self.module, fty, "pk." + key), params, f.ret, f.defaults)
            saved = self.builder, self.scopes, self.fn_ret, self.loops, self.captured, self.has_try, self.tries
            try:
                self.function(key, f)
            finally:
                self.builder, self.scopes, self.fn_ret, self.loops, self.captured, self.has_try, self.tries = saved
        sig = self.fns[key]
        call = Call(e.line, e.name, args, labels)
        return self.builder.call(sig.func, self.arrange(call, f"{e.name}()", sig.params, sig.defaults)), sig.ret

    def unify(self, pattern, actual, tparams, binds, line, what):
        """Match a parameter type with type variables against a real type, filling binds."""
        if pattern in tparams:
            if actual in ("nil", "[]", "[:]"):
                return
            if pattern in binds and not (fits(actual, binds[pattern]) or fits(binds[pattern], actual)):
                raise PlankError(line, f"{what} got {pattern} as {binds[pattern]} and then as {actual}")
            binds.setdefault(pattern, actual)
            return
        if pattern.endswith("?") and actual.endswith("?"):
            return self.unify(pattern[:-1], actual[:-1], tparams, binds, line, what)
        if pattern.endswith("?"):
            return self.unify(pattern[:-1], actual, tparams, binds, line, what)
        pg, ag = generic_name(pattern), generic_name(actual)
        if pg and ag and pg[0] == ag[0] and len(pg[1]) == len(ag[1]):
            for x, y in zip(pg[1], ag[1]):
                self.unify(x, y, tparams, binds, line, what)
            return
        pk, ak = dict_kv(pattern), dict_kv(actual)
        if pk and ak:
            self.unify(pk[0], ak[0], tparams, binds, line, what)
            return self.unify(pk[1], ak[1], tparams, binds, line, what)
        if is_list(pattern) and is_list(actual) and actual != "[]":
            return self.unify(pattern[1:-1], actual[1:-1], tparams, binds, line, what)
        pt, at_ = tuple_parts(pattern), tuple_parts(actual)
        if pt and at_ and len(pt) == len(at_):
            for x, y in zip(pt, at_):
                self.unify(x, y, tparams, binds, line, what)
            return
        ps, as_ = fn_sig(pattern), fn_sig(actual)
        if ps and as_ and len(ps[0]) == len(as_[0]):
            for x, y in zip(ps[0] + [ps[1]], as_[0] + [as_[1]]):
                self.unify(x, y, tparams, binds, line, what)
            return
        if not fits(actual, pattern) and any(re.search(rf"\b{t}\b", pattern) for t in tparams):
            raise PlankError(line, f"{what} wants {pattern}, got {actual}")

    def specialize(self, g, binds):
        """A copy of a generic function with every type parameter replaced."""
        import copy
        f = copy.deepcopy(g)
        def sub(ty):
            for t, real in binds.items():
                ty = re.sub(rf"\b{t}\b", real, ty)
            return ty
        for node in walk(f):
            for field in node.__dataclass_fields__:
                v = getattr(node, field)
                if field in ("ty", "ret") and isinstance(v, str):
                    setattr(node, field, sub(v))
                elif field in ("params", "fields") and isinstance(v, list):
                    setattr(node, field, [(n, sub(t) if t else t) for n, t in v])
                elif field == "name" and isinstance(node, Call) and generic_name(v):
                    setattr(node, field, sub(v))
        f.tparams = []
        return f

    def arrange(self, e, what, params, defaults, noun="parameter"):
        """Match positional and labeled arguments to params, in source order, and fill in defaults."""
        names = [n for n, _ in params]
        given = {}
        for i, (arg, label) in enumerate(zip(e.args, e.labels)):
            if label is None and i >= len(params):
                raise PlankError(e.line, f"{what} takes {len(params)} argument{'s' * (len(params) != 1)}, got {len(e.args)}")
            name = label or names[i]
            if name not in names:
                raise PlankError(e.line, f"{what} has no {noun} called {name!r}")
            if name in given:
                raise PlankError(e.line, f"{what} got {name!r} twice")
            given[name] = self.expr(arg, hint=dict(params)[name])
        out = []
        for name, want in params:
            if name in given:
                val, got = given[name]
            elif name in defaults:
                scopes, self.scopes = self.scopes, [{}]  # a default cannot see the caller's variables
                val, got = self.expr(defaults[name])
                self.scopes = scopes
            else:
                raise PlankError(e.line, f"{what} is missing {name!r}")
            if not fits(got, want):
                raise PlankError(e.line, f"{what} {name!r} should be {want}, got {got}")
            out.append(self.coerce(val, got, want))
        return out

    def construct(self, e):
        info = self.structs[e.name]
        vals = self.arrange(e, e.name, info.fields, info.defaults, "field")
        b = self.builder
        ptr_ty = info.type.as_pointer()
        nbytes = b.ptrtoint(b.gep(ir.Constant(ptr_ty, None), [ir.Constant(I32, 1)]), LL["int"])  # sizeof, the LLVM way
        obj = b.bitcast(self.call_c("pk_alloc", "str", nbytes), ptr_ty)
        for i, v in enumerate(vals):
            b.store(v, b.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, i)]))
        return obj

    def field_ptr(self, e):
        obj, ty = self.expr(e.target)
        if ty not in self.structs:
            raise PlankError(e.line, f"{ty} has no fields")
        fields = [n for n, _ in self.structs[ty].fields]
        if e.name not in fields:
            if tuple_parts(ty):
                raise PlankError(e.line, f"this tuple has {len(fields)} parts, .0 to .{len(fields) - 1}; there is no .{e.name[1:]}")
            raise PlankError(e.line, f"{ty} has no field {e.name!r}, it has {', '.join(fields)}")
        i = fields.index(e.name)
        return self.builder.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, i)]), self.structs[ty].fields[i][1]

    def e_Field(self, e):
        if isinstance(e.target, Name) and e.target.name in self.modules and self.find(e.target.name) is None:
            full = f"{e.target.name}.{e.name}"
            if full in self.fns or full in self.generics:
                return self.fn_value(full) if full in self.fns else self.fn_value_error(e, full)
            raise PlankError(e.line, f"module {e.target.name} has no function called {e.name}")
        if self.is_enum_name(e.target):
            return self.make_case(e, self.qualified(e.target), e.name, None)
        ptr, ty = self.field_ptr(e)
        return self.builder.load(ptr), ty

    def show_struct(self, ty):
        """Point(x: 3, y: 4), the way you would build it."""
        name = "show." + ty
        if name in self.module.globals:
            return self.module.globals[name]
        fn = ir.Function(self.module, ir.FunctionType(LL["str"], [self.ll(ty)]), name)
        fn.linkage = "private"
        outer, self.builder = self.builder, ir.IRBuilder(fn.append_basic_block("entry"))
        b = self.builder
        out = self.cstr(ty + "(")
        for i, (fname, fty) in enumerate(self.structs[ty].fields):
            text = self.to_str(b.load(b.gep(fn.args[0], [ir.Constant(I32, 0), ir.Constant(I32, i)])), fty)
            if fty == "str":
                text = self.call_c("pk_concat", "str", self.call_c("pk_concat", "str", self.cstr('"'), text), self.cstr('"'))
            label = (", " if i else "") + fname + ": "
            out = self.call_c("pk_concat", "str", self.call_c("pk_concat", "str", out, self.cstr(label)), text)
        b.ret(self.call_c("pk_concat", "str", out, self.cstr(")")))
        self.builder = outer
        return fn

    def arity(self, e, args, *counts):
        if len(args) not in counts:
            want = " or ".join(map(str, counts))
            raise PlankError(e.line, f"{e.name}() takes {want} argument{'s' * (counts != (1,))}, got {len(args)}")

    # -- built-ins: each gets the call and its evaluated (value, type) args
    def b_print(self, e, args):
        vals = [self.to_str(v, t) if t == "bool" else v for v, t in args]
        fmt = " ".join(FMT[t] for _, t in args) + "\n"
        self.builder.call(self.printf, [self.cstr(fmt)] + vals)
        return None, "void"

    def b_str(self, e, args):
        self.arity(e, args, 1)
        return self.to_str(*args[0]), "str"

    def b_len(self, e, args):
        self.arity(e, args, 1)
        val, ty = args[0]
        if ty in ("[]", "[:]"):
            return ir.Constant(LL["int"], 0), "int"
        if generic_name(ty) and generic_name(ty)[0] == "Set":
            return self.e_Method(Method(e.line, Given(e.line, val, ty), "size", [], []))
        if dict_kv(ty):
            return self.call_c("pk_dict_len", "int", val), "int"
        if is_list(ty):
            return self.list_len(val), "int"
        if ty != "str":
            raise PlankError(e.line, f"len() needs a str, a list or a dict, got {ty}")
        return self.call_c("pk_len", "int", val), "int"

    def b_input(self, e, args):
        self.arity(e, args, 0, 1)
        if args and args[0][1] != "str":
            raise PlankError(e.line, f"input() takes a str prompt, got {args[0][1]}")
        return self.call_c("pk_input", "str", args[0][0] if args else self.cstr("")), "str"

    def b_int(self, e, args):
        return self.convert(e, args, "int")

    def b_float(self, e, args):
        return self.convert(e, args, "float")

    def convert(self, e, args, to):
        self.arity(e, args, 1)
        b = self.builder
        val, ty = args[0]
        if ty == to:
            return val, ty
        if ty == "str":
            return self.call_c("pk_parse_" + to, to, val, *self.where(e.line)), to
        if to == "int" and ty == "float":
            return b.fptosi(val, LL["int"]), "int"
        if to == "int" and ty == "bool":
            return b.zext(val, LL["int"]), "int"
        if to == "float" and ty == "int":
            return b.sitofp(val, LL["float"]), "float"
        raise PlankError(e.line, f"cannot convert {ty} to {to}")

    def number(self, e, args, n):
        self.arity(e, args, n)
        tys = {t for _, t in args}
        if len(tys) != 1 or tys - {"int", "float"}:
            raise PlankError(e.line, f"{e.name}() needs {'numbers of one type' if n > 1 else 'an int or a float'}, got {', '.join(t for _, t in args)}")
        return [v for v, _ in args], tys.pop()

    def b_abs(self, e, args):
        (v,), ty = self.number(e, args, 1)
        if ty == "float":
            return self.call_c("fabs", "float", v), ty
        return self.builder.select(self.builder.icmp_signed("<", v, ir.Constant(v.type, 0)), self.builder.neg(v), v), ty

    def b_min(self, e, args):
        return self.pick(e, args, "<")

    def b_max(self, e, args):
        return self.pick(e, args, ">")

    def pick(self, e, args, op):
        (x, y), ty = self.number(e, args, 2)
        b = self.builder
        smaller = b.fcmp_ordered(op, x, y) if ty == "float" else b.icmp_signed(op, x, y)
        return b.select(smaller, x, y), ty

    def libm(self, e, args, n=1):
        self.arity(e, args, n)
        for _, t in args:
            if t != "float":
                raise PlankError(e.line, f"{e.name}() needs float, got {t}; wrap it in float()")
        return self.call_c(e.name, "float", *[v for v, _ in args]), "float"

    b_sqrt = b_floor = b_ceil = b_round = libm

    def b_fixed(self, e, args):
        self.arity(e, args, 2)
        if [t for _, t in args] != ["float", "int"]:
            raise PlankError(e.line, "fixed(x, digits) takes a float and an int: fixed(3.14159, 2) is \"3.14\"")
        return self.call_c("pk_fixed", "str", args[0][0], args[1][0]), "str"

    def maybe(self, ptr, ty):
        """A C pointer that may be NULL, as a Plank optional."""
        b, want = self.builder, ty + "?"
        with b.if_else(b.icmp_unsigned("!=", ptr, ir.Constant(ptr.type, None))) as (yes, no):
            with yes:
                some, yes_bb = self.coerce(ptr, ty, want), b.block
            with no:
                no_bb = b.block
        phi = b.phi(self.ll(want))
        phi.add_incoming(some, yes_bb)
        phi.add_incoming(ir.Constant(self.ll(want), None), no_bb)
        return phi, want

    def typed(self, e, args, *want):
        if [t for _, t in args] != list(want):
            sig = ", ".join(want)
            raise PlankError(e.line, f"{e.name}() takes ({sig}), got ({', '.join(t for _, t in args)})")
        return [v for v, _ in args]

    def b_args(self, e, args):
        self.typed(e, args)
        return self.call_c("pk_args", LIST), "[str]"

    def b_read_file(self, e, args):
        return self.maybe(self.call_c("pk_read_file", "str", *self.typed(e, args, "str")), "str")

    def b_write_file(self, e, args):
        ok = self.call_c("pk_write_file", "int", *self.typed(e, args, "str", "str"))
        return self.builder.trunc(ok, LL["bool"]), "bool"

    def b_run(self, e, args):
        """run("cmd") -> str: stdout; the exit code is in status() right after."""
        return self.call_c("pk_run", "str", *self.typed(e, args, "str")), "str"

    def b_status(self, e, args):
        self.typed(e, args)
        return self.call_c("pk_run_code", "int"), "int"

    def b_quote(self, e, args):
        return self.call_c("pk_quote", "str", *self.typed(e, args, "str")), "str"

    def b_json_quote(self, e, args):
        return self.call_c("pk_json_quote", "str", *self.typed(e, args, "str")), "str"

    def b_http(self, e, args):
        """http(method, url, body = "", headers: [str] = []) -> str body; status() holds the HTTP code."""
        if any(e.labels):
            raise PlankError(e.line, "http() arguments go by position: http(method, url, body, headers)")
        tys = [t for _, t in args]
        want = ["str", "str", "str", "[str]"]
        if not 2 <= len(args) <= 4 or any(not fits(t, w) for t, w in zip(tys, want)):
            raise PlankError(e.line, "http(method, url, body?, headers?) takes str, str, str and [str]")
        vals = [v for v, _ in args]
        if len(vals) < 3:
            vals.append(self.cstr(""))
        if len(vals) < 4 or tys[3] == "[]":
            empty = self.builder.call(self.c("pk_list_new", LIST, LL["int"], LL["int"]), [ir.Constant(LL["int"], 0), ir.Constant(LL["int"], 8)])
            vals = vals[:3] + [empty]
        return self.call_c("pk_http", "str", *vals), "str"

    def b_json_parse(self, e, args):
        """json_parse(text) -> Json, or a throw naming what was wrong."""
        text, = self.typed(e, args, "str")
        b = self.builder
        b.call(self.c("pk_json_begin", ir.VoidType(), LL["str"], LL["str"], LL["int"]), [text] + self.where(e.line))
        val = b.call(self.json_reader(), [])
        b.call(self.c("pk_json_end", ir.VoidType()), [])
        return val, "Json"

    def json_reader(self):
        """A recursive private function that reads one JSON value from the runtime's cursor into a Json."""
        name = "json.read"
        if name in self.module.globals:
            return self.module.globals[name]
        fn = ir.Function(self.module, ir.FunctionType(self.ll("Json"), []), name)
        fn.linkage = "private"
        saved = self.builder, self.scopes, self.fn_ret, self.loops, self.captured, self.has_try, self.tries
        self.builder = ir.IRBuilder(fn.append_basic_block("entry"))
        self.scopes, self.fn_ret, self.loops, self.captured, self.has_try, self.tries = [{}], "Json", [], set(), False, 0
        b = self.builder
        c = b.call(self.c("pk_json_next", LL["int"]), [])
        done = fn.append_basic_block("done")
        sw = b.switch(c, done)
        def case(ch, build):
            bb = fn.append_basic_block("j" + ch)
            sw.add_case(ir.Constant(LL["int"], ord(ch)), bb)
            b.position_at_end(bb)
            b.ret(build())
        def make(casename, args_vals):
            tag, fields = self.enums["Json"].case(casename)
            info = self.enums["Json"]
            ptr_ty = info.type.as_pointer()
            nbytes = b.ptrtoint(b.gep(ir.Constant(ptr_ty, None), [ir.Constant(I32, 1)]), LL["int"])
            obj = b.bitcast(self.call_c("pk_alloc", "str", nbytes), ptr_ty)
            b.store(ir.Constant(LL["int"], tag), b.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            for i, (v, (_, fty)) in enumerate(zip(args_vals, fields)):
                slot = b.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, 1 + i)])
                b.store(v, b.bitcast(slot, self.ll(fty).as_pointer()))
            return obj
        case("n", lambda: (b.call(self.c("pk_json_null", ir.VoidType()), []), make("null", []))[1])
        for ch in "tf":
            case(ch, lambda: make("bool", [b.trunc(b.call(self.c("pk_json_bool", LL["int"]), []), LL["bool"])]))
        for ch in "-0123456789":
            case(ch, lambda: make("number", [b.call(self.c("pk_json_number", LL["float"]), [])]))
        case('"', lambda: make("string", [b.call(self.c("pk_json_string", LL["str"]), [])]))
        expect = self.c("pk_json_expect", ir.VoidType(), LL["int"])
        def seq(open_ch, close_ch, each):
            b.call(expect, [ir.Constant(LL["int"], ord(open_ch))])
            loop, body, out = (fn.append_basic_block(n) for n in ("loop", "item", "end"))
            b.branch(loop)
            b.position_at_end(loop)
            nxt = b.call(self.c("pk_json_next", LL["int"]), [])
            b.cbranch(b.icmp_signed("==", nxt, ir.Constant(LL["int"], ord(close_ch))), out, body)
            b.position_at_end(body)
            each()
            after = b.call(self.c("pk_json_next", LL["int"]), [])
            is_comma = b.icmp_signed("==", after, ir.Constant(LL["int"], ord(",")))
            with b.if_then(is_comma):
                b.call(expect, [ir.Constant(LL["int"], ord(","))])
            b.branch(loop)
            b.position_at_end(out)
            b.call(expect, [ir.Constant(LL["int"], ord(close_ch))])
        def array():
            lst = b.call(self.c("pk_list_new", LIST, LL["int"], LL["int"]), [ir.Constant(LL["int"], 4), ir.Constant(LL["int"], 8)])
            seq("[", "]", lambda: self.push(lst, b.call(fn, []), "Json"))
            return make("array", [lst])
        def obj():
            d = b.call(self.c("pk_dict_new", LL["str"], LL["int"]), [ir.Constant(LL["int"], 1)])
            def pair():
                key = b.call(self.c("pk_json_string", LL["str"]), [])
                b.call(expect, [ir.Constant(LL["int"], ord(":"))])
                b.store(b.call(fn, []), self.dict_slot(d, ("str", "Json"), key, "str", 0, "pk_dict_put"))
            seq("{", "}", pair)
            return make("object", [d])
        case("[", array)
        case("{", obj)
        b.position_at_end(done)
        b.call(self.c("pk_json_expect", ir.VoidType(), LL["int"]), [ir.Constant(LL["int"], ord("v"))])  # fails with "expected v": a value
        b.unreachable()
        self.builder, self.scopes, self.fn_ret, self.loops, self.captured, self.has_try, self.tries = saved
        return fn

    def b_read_stdin(self, e, args):
        self.typed(e, args)
        return self.call_c("pk_read_stdin", "str"), "str"

    def b_env(self, e, args):
        return self.maybe(self.call_c("pk_env", "str", *self.typed(e, args, "str")), "str")

    def b_assert(self, e, args):
        if not args or args[0][1] != "bool" or len(args) > 2 or (len(args) == 2 and args[1][1] != "str"):
            raise PlankError(e.line, "assert(cond) or assert(cond, message): the condition is a bool, the message a str")
        b = self.builder
        with b.if_then(b.not_(args[0][0]), likely=False):
            text = args[1][0] if len(args) == 2 else self.cstr("")
            msg = self.call_c("pk_concat", "str", self.cstr("assertion failed: "), text)
            b.call(self.c("pk_panic", ir.VoidType(), LL["str"], LL["int"], LL["str"]), self.where(e.line) + [msg])
            b.unreachable()
        return None, "void"

    def b_exit(self, e, args):
        self.builder.call(self.c("pk_exit", ir.VoidType(), LL["int"]), self.typed(e, args, "int"))
        return None, "void"

    def b_zip(self, e, args):
        """zip(xs, ys) -> [(X, Y)], as long as the shorter one."""
        self.arity(e, args, 2)
        (xs, xt), (ys, yt) = args
        if not is_list(xt) or not is_list(yt) or "[]" in (xt, yt):
            raise PlankError(e.line, f"zip() takes two lists, got {xt} and {yt}")
        xe, ye = xt[1:-1], yt[1:-1]
        pair_ty = f"({xe}, {ye})"
        self.tuple_struct(pair_ty, e.line)
        b = self.builder
        n = b.select(b.icmp_signed("<", self.list_len(xs), self.list_len(ys)), self.list_len(xs), self.list_len(ys))
        out = b.call(self.c("pk_list_new", LIST, LL["int"], LL["int"]), [n, ir.Constant(LL["int"], 8)])
        with b.goto_entry_block():
            i = b.alloca(LL["int"])
        b.store(ir.Constant(LL["int"], 0), i)
        cond, body, done = (b.append_basic_block(k) for k in ("zip", "pair", "zipped"))
        b.branch(cond)
        b.position_at_end(cond)
        b.cbranch(b.icmp_signed("<", b.load(i), n), body, done)
        b.position_at_end(body)
        x = b.load(self.slot(xs, b.load(i), xe))
        y = b.load(self.slot(ys, b.load(i), ye))
        pair = self.construct(Call(e.line, pair_ty, [Given(e.line, x, xe), Given(e.line, y, ye)], [None, None]))
        self.push(out, pair, pair_ty)
        b.store(b.add(b.load(i), ir.Constant(LL["int"], 1)), i)
        b.branch(cond)
        b.position_at_end(done)
        return out, f"[{pair_ty}]"

    # -- files and folders, the clock, urls
    def flag(self, fn, e, args, *want):
        return self.builder.trunc(self.call_c(fn, "int", *self.typed(e, args, *want)), LL["bool"]), "bool"

    def b_exists(self, e, args):
        return self.flag("pk_exists", e, args, "str")

    def b_is_dir(self, e, args):
        return self.flag("pk_is_dir", e, args, "str")

    def b_mkdir(self, e, args):
        return self.flag("pk_mkdir", e, args, "str")

    def b_remove_file(self, e, args):
        return self.flag("pk_remove_file", e, args, "str")

    def b_append_file(self, e, args):
        return self.flag("pk_append_file", e, args, "str", "str")

    def b_list_dir(self, e, args):
        return self.call_c("pk_list_dir", LIST, *self.typed(e, args, "str")), "[str]"

    def b_cwd(self, e, args):
        self.typed(e, args)
        return self.call_c("pk_cwd", "str"), "str"

    def b_clock(self, e, args):
        """clock() -> "2026-10-01 18:30:00", clock("%H:%M") -> any strftime layout, clock(fmt, at) for another moment."""
        self.arity(e, args, 0, 1, 2)
        tys = [t for _, t in args]
        if tys[:1] not in ([], ["str"]) or tys[1:] not in ([], ["float"]):
            raise PlankError(e.line, f"clock() takes a format string and maybe a time as a float, got ({', '.join(tys)})")
        fmt = args[0][0] if args else self.cstr("")
        at = args[1][0] if len(args) > 1 else ir.Constant(LL["float"], 0)
        return self.call_c("pk_clock", "str", fmt, at, ir.Constant(LL["int"], int(len(args) > 1))), "str"

    def b_parse_time(self, e, args):
        """parse_time("2026-10-01") -> float?, seconds since 1970; parse_time(text, "%d/%m/%Y") for another layout."""
        self.arity(e, args, 1, 2)
        if any(t != "str" for _, t in args):
            raise PlankError(e.line, "parse_time(text, layout?) takes strings")
        secs = self.call_c("pk_parse_time", "float", args[0][0], args[1][0] if len(args) > 1 else self.cstr(""))
        b = self.builder
        ok = b.fcmp_ordered(">=", secs, ir.Constant(LL["float"], 0))
        with b.if_else(ok) as (yes, no):
            with yes:
                some, yes_bb = self.coerce(secs, "float", "float?"), b.block
            with no:
                no_bb = b.block
        phi = b.phi(self.ll("float?"))
        phi.add_incoming(some, yes_bb)
        phi.add_incoming(ir.Constant(self.ll("float?"), None), no_bb)
        return phi, "float?"

    def b_url_encode(self, e, args):
        return self.call_c("pk_url_encode", "str", *self.typed(e, args, "str")), "str"

    def b_sleep(self, e, args):
        self.typed(e, args, "float")
        self.builder.call(self.c("pk_sleep", ir.VoidType(), LL["float"]), [args[0][0]])
        return None, "void"

    def b_time(self, e, args):
        self.typed(e, args)
        return self.call_c("pk_time", "float"), "float"

    def b_random(self, e, args):
        if not args:
            return self.call_c("pk_random_float", "float"), "float"
        return self.call_c("pk_random_int", "int", *self.typed(e, args, "int", "int")), "int"

    def b_pow(self, e, args):
        return self.libm(e, args, 2)


# ---------------------------------------------------------------- driver
def load(src, path):
    """Parse a program and every file it imports, each once. Returns the items and the file list."""
    files, items, todo, uses_json, uses_set, modules = [path], [], [(src, path, None)], False, False, set()
    seen = {os.path.realpath(path)} if os.path.exists(path) else set()
    while todo:
        text, at, alias = todo.pop(0)
        toks = lex(text, files.index(at) * STRIDE + 1)
        uses_json |= any(t.kind == "name" and t.val in ("Json", "json_parse") for t in toks)
        uses_set |= any(t.kind == "name" and t.val in ("Set", "set_of") for t in toks)
        parsed = Parser(toks).program()
        if alias:
            parsed = qualify(parsed, alias)
            modules.add(alias)
        for it in parsed:
            if not isinstance(it, Import):
                items.append(it)
                continue
            target = os.path.normpath(os.path.join(os.path.dirname(at), it.path))
            if os.path.realpath(target) in seen:
                if it.alias and it.alias not in modules:
                    raise PlankError(it.line, f"{it.path} is already imported; use the name it has")
                continue
            try:
                with open(target) as f:
                    todo.append((f.read(), target, it.alias))
            except OSError:
                raise PlankError(it.line, f"cannot import {it.path!r}: no file at {target}")
            seen.add(os.path.realpath(target))
            files.append(target)
    return items, files, uses_json, modules, uses_set


def qualify(items, alias):
    """Every top-level name in a module becomes alias.name, and every reference to it inside the module follows."""
    fns = {it.name for it in items if isinstance(it, Fn)}
    types = {it.name for it in items if isinstance(it, (Struct, Enum))}
    own = fns | types
    pat = re.compile(r"(?<![\w.])(" + "|".join(sorted(map(re.escape, types), key=len, reverse=True)) + r")\b") if types else None
    def sub(ty):
        return pat.sub(lambda m: f"{alias}.{m.group(1)}", ty) if pat and ty else ty
    for it in items:
        if isinstance(it, Import):
            continue
        it.name = f"{alias}.{it.name}"
        for node in walk(it):
            if isinstance(node, Call) and node.name.split("<")[0] in own:
                node.name = f"{alias}.{node.name}"
            elif isinstance(node, Name) and node.name in own:
                node.name = f"{alias}.{node.name}"
            for field in node.__dataclass_fields__:
                v = getattr(node, field)
                if field in ("ty", "ret") and isinstance(v, str):
                    setattr(node, field, sub(v))
                elif field in ("params", "fields") and isinstance(v, list):
                    setattr(node, field, [(n, sub(t) if t else t) for n, t in v])
                elif field == "cases" and isinstance(v, list):
                    setattr(node, field, [(c, [(n, sub(t)) for n, t in fs]) for c, fs in v])
    return items


def compile_source(src, name="plank", file=None):
    files = [file or name]
    try:
        items, files, uses_json, modules, uses_set = load(src, file or name)
        return Codegen(name, file, files, uses_json, modules, uses_set).program(items)
    except PlankError as err:
        err.file, err.line = locate(err.line, files)
        raise


def optimize(module_text, level=2):
    binding.initialize_native_target()
    binding.initialize_native_asmprinter()
    target = binding.Target.from_triple(TRIPLE)
    tm = target.create_target_machine(opt=level, reloc="pic", codemodel="default")
    mod = binding.parse_assembly(module_text)
    mod.verify()
    pto = binding.create_pipeline_tuning_options(speed_level=level)
    pb = binding.create_pass_builder(tm, pto)
    pb.getModulePassManager().run(mod, pb)
    return tm, mod


def build(path, out=None, static=False):
    """Compile, optimize and link. static asks for a binary with no shared libraries, which Linux can do and macOS cannot."""
    with open(path) as f:
        src = f.read()
    module = compile_source(src, os.path.basename(path), path)
    tm, mod = optimize(str(module))
    out = out or os.path.splitext(path)[0]
    tmp = tempfile.mkdtemp()
    obj, rt = os.path.join(tmp, "prog.o"), os.path.join(tmp, "runtime.c")
    with open(obj, "wb") as f:
        f.write(tm.emit_object(mod))
    with open(rt, "w") as f:
        f.write(RUNTIME)
    try:
        libs = os.environ.get("PLANK_LIBS", "").split()  # extra -l flags for extern fn from other libraries
        if static and sys.platform == "darwin":
            print("plank: macOS has no static libc, so --static builds a normal binary here; it works as asked on Linux", file=sys.stderr)
        flags = ["-static"] if static and sys.platform != "darwin" else []
        link = subprocess.run(["cc", "-O2", "-w"] + flags + [obj, rt, "-o", out, "-lm"] + libs, capture_output=True, text=True)
        if link.returncode:
            missing = [a or b for a, b in re.findall(r'"_?(\w+)", referenced from|undefined reference to [`\x27]_?(\w+)', link.stderr)]
            if missing:
                raise PlankError(0, f"the C library has no function called {missing[0]}; check the extern fn name, or set PLANK_LIBS=\"-lsomething\" for another library")
            raise PlankError(0, "linking failed, this is a Plank bug, please report it:\n" + link.stderr.strip())
    finally:
        os.unlink(obj); os.unlink(rt); os.rmdir(tmp)
    return out


def repl():
    """A conversation with the compiler. Every entry rebuilds and reruns the whole program, so what you
    see is always what a real binary printed; only the new output is shown. fn, struct, enum and import
    entries define things, anything else runs, and a bare expression is printed."""
    try:
        import readline  # arrow keys and history where the platform has it
    except ImportError:
        pass
    print(f"plank {VERSION}. Type Plank; a bare expression prints itself. Ctrl-D or exit leaves.")
    decls, body, shown, pending, depth = [], [], 0, [], 0
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "repl.pk")
    keyword = re.compile(r"^\s*(let|var|if|while|for|match|try|throw|return|break|continue)\b")
    assign = re.compile(r"^\s*[\w.\[\]!]+\s*(=|\+=|-=|\*=|/=|%=)[^=]")
    def attempt(new_decls, new_body):
        with open(path, "w") as f:
            f.write("\n".join(new_decls) + "\nfn main() {\n" + "\n".join(new_body) + "\n}\n")
        exe = build(path, os.path.join(tmp, "a.out"))
        got = subprocess.run([exe], capture_output=True, text=True)
        os.unlink(exe)
        return got
    while True:
        try:
            line = input(". " if pending else "> ")
        except EOFError:
            print()
            return 0
        if not pending and line.strip() in ("exit", "quit"):
            return 0
        pending.append(line)
        depth += line.count("{") - line.count("}")
        if depth > 0 or not line.strip():
            if not line.strip() and depth <= 0:
                pending = []
            continue
        entry, pending, depth = "\n".join(pending), [], 0
        is_decl = re.match(r"^\s*(fn|struct|enum|import)\b", entry)
        candidates = [entry] if is_decl or keyword.match(entry) or assign.match(entry) or "\n" in entry else [f"print({entry})", entry]
        err = None
        for text in candidates:
            try:
                got = attempt(decls + ([text] if is_decl else []), body + ([] if is_decl else [text]))
            except PlankError as e:
                err = str(e)
                continue
            if got.returncode != 0:
                err = got.stderr.strip().replace(path + ":", "line ")
                continue
            if is_decl:
                decls.append(text)
            else:
                body.append(text)
            sys.stdout.write(got.stdout[shown:])
            shown = len(got.stdout)
            err = None
            break
        if err:
            print("error:", err)


def run_tests(folder):
    """Every .pk in the folder is a test; it passes when it exits 0 and prints exactly `ok`."""
    import glob
    files = sorted(glob.glob(os.path.join(folder, "*.pk")))
    if not files:
        print(f"plank test: no .pk files in {folder}", file=sys.stderr)
        return 2
    failed = 0
    for path in files:
        try:
            exe = build(path, os.path.join(tempfile.mkdtemp(), "t.out"))
            got = subprocess.run([exe], capture_output=True, text=True)
            os.unlink(exe)
            ok = got.returncode == 0 and got.stdout.strip() == "ok"
            detail = "" if ok else (got.stderr.strip() or got.stdout.strip() or f"exit {got.returncode}")
        except PlankError as err:
            ok, detail = False, f"{err.file or path}:{err.line}: {err}"
        failed += not ok
        print(("ok   " if ok else "FAIL ") + path + ("" if ok else "\n     " + detail.replace("\n", "\n     ")))
    print(f"{len(files) - failed} of {len(files)} passed")
    return 1 if failed else 0


def main(argv=sys.argv[1:]):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] == "--version":
        print(f"plank {VERSION}")
        return 0
    if argv[0] == "repl":
        return repl()
    if argv[0] == "fmt":
        return fmt_files(argv[1:])
    cmd, rest = (argv[0], argv[1:]) if argv[0] in ("run", "build", "emit", "test") else ("run", argv)
    if cmd == "test":
        return run_tests(rest[0] if rest else "tests")
    if not rest:
        print("plank: need a .pk file", file=sys.stderr)
        return 2
    path = rest[0]
    static = "--static" in rest
    rest = [a for a in rest if a != "--static"]
    out = rest[rest.index("-o") + 1] if "-o" in rest else None
    prog_args = [a for i, a in enumerate(rest[1:], 1) if a != "-o" and (i < 2 or rest[i - 1] != "-o")]
    try:
        if cmd == "emit":
            with open(path) as f:
                print(compile_source(f.read(), os.path.basename(path), path))
            return 0
        if cmd == "build":
            print(build(path, out, static))
            return 0
        exe = build(path, out or os.path.join(tempfile.mkdtemp(), "a.out"))
        code = subprocess.run([exe] + prog_args).returncode
        if not out:
            os.unlink(exe)
        return code
    except PlankError as err:
        print(f"{err.file or path}:{err.line}: {err}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"plank: no such file {path}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
