#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["llvmlite>=0.44"]
# ///
"""Plank: a small compiled language. Lexer, parser, codegen, one file.

    plank run hello.pk a b  compile and run, passing a and b to args()
    plank build hello.pk    native binary next to the source
    plank emit hello.pk     print the LLVM IR
"""
import os, platform, re, subprocess, sys, tempfile
from dataclasses import dataclass, field

from llvmlite import binding, ir

VERSION = "1.0.0"
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
    return files[min(line // STRIDE, len(files) - 1)], line % STRIDE


# ---------------------------------------------------------------- lexer
KEYWORDS = {"fn", "import", "try", "catch", "throw", "struct", "enum", "match", "nil", "let", "var", "if", "else", "while", "for", "in", "return",
            "break", "continue", "true", "false", "and", "or", "not"}
TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t\r]+) | (?P<comment>\#[^\n]*) | (?P<nl>\n) |
    (?P<float>\d+\.\d+(?:[eE][+-]?\d+)?) | (?P<int>\d+) |
    (?P<name>[A-Za-z_]\w*) |
    (?P<op>\+=|-=|\*=|/=|%=|->|=>|\.\.|==|!=|<=|>=|\?\?|[-+*/%<>=(){}\[\]:,.?!])
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


def lex(src, line=1):
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
        if kind in ("ws", "comment"):
            continue
        if kind == "nl":
            if depth == 0:
                toks.append(Tok("nl", None, line))
            line += 1
        elif kind == "int":
            toks.append(Tok("int", int(text), line))
        elif kind == "float":
            toks.append(Tok("float", float(text), line))
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
class Binary(Node): op: str; left: Node; right: Node
@dataclass
class Call(Node): name: str; args: list; labels: list
@dataclass
class Let(Node): name: str; ty: str; expr: Node; mutable: bool
@dataclass
class Assign(Node): target: Node; expr: Node
@dataclass
class If(Node): cond: Node; then: list; other: list
@dataclass
class While(Node): cond: Node; body: list
@dataclass
class For(Node): name: str; start: Node; stop: Node; body: list
@dataclass
class ForIn(Node): name: str; items: Node; body: list
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
class Fn(Node): name: str; params: list; ret: str; body: list; defaults: dict
@dataclass
class Import(Node): path: str
@dataclass
class Struct(Node): name: str; fields: list; defaults: dict; methods: list
@dataclass
class Enum(Node): name: str; cases: list; methods: list
@dataclass
class Match(Node): subject: Node; arms: list; other: list


# ---------------------------------------------------------------- parser
PREC = {"or": 1, "and": 2, "in": 4, "??": 4.5, "==": 4, "!=": 4, "<": 4, ">": 4, "<=": 4, ">=": 4,
        "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}
TYPES = {"int", "float", "bool", "str"}


class Parser:
    def __init__(self, toks):
        self.toks, self.i = toks, 0

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
                items.append(Import(line, path))
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
        cases, methods = [], []
        self.skip_nl()
        while not self.at("}"):
            if self.at("fn"):
                methods.append(self.fn())
            else:
                case = self.expect("name").val
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
        self.expect("}")
        return Enum(line, name, cases, methods)

    def match(self):
        line = self.expect("match").line
        subject = self.expr()
        self.expect("{")
        arms, other = [], None
        self.skip_nl()
        while not self.at("}"):
            if self.at("else"):
                self.next()
                other = self.block()
            else:
                pats = [self.pattern()]
                while self.at(","):
                    self.next()
                    pats.append(self.pattern())
                arms.append((pats, self.block()))
            self.skip_nl()
        self.expect("}")
        return Match(line, subject, arms, other)

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
        self.expect("}")
        return Struct(line, name, fields, defaults, methods)

    def fn(self):
        line = self.expect("fn").line
        name = self.expect("name").val
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
        return Fn(line, name, params, ret, self.block(), defaults)

    def type(self):
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
        if t.val not in TYPES and not t.val[0].isupper():  # capitalized names are structs, checked in codegen
            raise PlankError(t.line, f"unknown type {t.val!r}")
        return self.optional(t.val)

    def optional(self, ty):
        while self.at("?", "??"):
            ty += self.next().kind
        return ty

    def block(self):
        self.expect("{")
        stmts = []
        self.skip_nl()
        while not self.at("}"):
            stmts.append(self.stmt())
            if not self.at("}"):
                self.expect("nl")
            self.skip_nl()
        self.expect("}")
        return stmts

    def stmt(self):
        t = self.tok
        if self.at("let", "var"):
            self.next()
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
            cond = self.expr()
            return While(t.line, cond, self.block())
        if self.at("for"):
            self.next()
            name = self.expect("name").val
            self.expect("in")
            start = self.expr()
            if not self.at(".."):
                return ForIn(t.line, name, start, self.block())
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

    def else_(self):
        other = []
        mark = self.i
        self.skip_nl()
        if not self.at("else"):
            self.i = mark
        else:
            self.next()
            other = [self.if_()] if self.at("if") else self.block()
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
        while self.at("[", ".", "!", "("):
            line = self.next().line
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
            name = self.expect("name").val
            if self.at("("):
                self.next()
                e = Method(line, e, name, *self.call_args())
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
        ret = "void"
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
            return Num(t.line, t.val, "float")
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
            self.expect(")")
            return e
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
                return List(t.line, [first] + self.args("]"))
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
            self.expect("]")
            return Dict(t.line, keys, vals)
        if t.kind == "name":
            if self.at("("):
                self.next()
                return Call(t.line, t.val, *self.call_args())
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


# ---------------------------------------------------------------- runtime
# The handful of things LLVM does not hand you: joining strings, reading a
# line, turning numbers into text. Compiled by cc next to your program.
RUNTIME = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <setjmp.h>
#include <time.h>
#include <unistd.h>

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

/* ponytail: nothing is ever freed. Fine for programs that run and exit; an arena or refcounts when that stops being true. */
void *pk_alloc(long long n) {
    void *p = malloc(n);
    if (!p) { fputs("plank: out of memory\n", stderr); exit(1); }
    return p;
}

char *pk_concat(const char *a, const char *b) {
    size_t x = strlen(a), y = strlen(b);
    char *r = pk_alloc(x + y + 1);
    memcpy(r, a, x);
    memcpy(r + x, b, y + 1);
    return r;
}

/* length in characters, not bytes: count every byte that does not continue a UTF-8 sequence */
long long pk_len(const char *s) {
    long long n = 0;
    for (; *s; s++) n += ((unsigned char)*s & 0xC0) != 0x80;
    return n;
}

char *pk_str_int(long long v) { char *r = pk_alloc(24); snprintf(r, 24, "%lld", v); return r; }
char *pk_str_float(double v) { char *r = pk_alloc(32); snprintf(r, 32, "%.15g", v); return r; }

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
        l->data = realloc(l->data, l->cap * size);
        if (!l->data) { fputs("plank: out of memory\n", stderr); exit(1); }
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
    d->index = calloc(d->mask + 1, 8);
    return d;
}

/* the index cell for key: entry number + 1, or 0 where the key would go */
static long long *pk_probe(PkDict *d, long long key) {
    unsigned long long i = pk_hash(d, key) & d->mask;
    while (d->index[i] && !pk_same(d, d->keys[d->index[i] - 1], key)) i = (i + 1) & d->mask;
    return &d->index[i];
}

static void pk_reindex(PkDict *d) {
    free(d->index);
    d->index = calloc(d->mask + 1, 8);
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
        d->keys = realloc(d->keys, 8 * d->cap);
        d->vals = realloc(d->vals, 8 * d->cap);
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
    PkList *l = pk_list_new(d->len, 8);
    memcpy(l->data, d->keys, 8 * d->len);
    l->len = d->len;
    return l;
}

PkList *pk_dict_values(PkDict *d, long long size) {
    PkList *l = pk_list_new(d->len, size);
    for (long long e = 0; e < d->len; e++) memcpy(l->data + e * size, &d->vals[e], size);
    l->len = d->len;
    return l;
}

long long pk_list_find(PkList *l, long long size, long long bits, long long isstr) {
    for (long long i = 0; i < l->len; i++) {
        char *at = l->data + i * size;
        if (isstr ? strcmp(*(char **)at, (char *)bits) == 0 : memcmp(at, &bits, size) == 0) return i;
    }
    return -1;
}

PkList *pk_list_copy(PkList *l, long long size) {
    PkList *r = pk_list_new(l->len, size);
    memcpy(r->data, l->data, size * l->len);
    r->len = l->len;
    return r;
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
    char *tmp = pk_alloc(size * (l->len ? l->len : 1));
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
    char *r = pk_alloc(n + 1);
    memcpy(r, s, n);
    r[n] = 0;
    return r;
}

static void pk_clamp(long long len, long long *a, long long *b) {
    if (*a < 0) *a += len;
    if (*b < 0) *b += len;
    if (*a < 0) *a = 0;
    if (*b > len) *b = len;
    if (*a > *b) *a = *b;
}

char *pk_str_slice(const char *s, long long a, long long b) {
    pk_clamp(pk_len(s), &a, &b);
    long long from = pk_skip(s, a);
    return pk_strndup(s + from, pk_skip(s + from, b - a));
}

char *pk_char_at(const char *s, long long i, const char *file, long long line) {
    long long n = pk_len(s), at = i < 0 ? i + n : i;
    if (at < 0 || at >= n) {
        static char msg[96];
        snprintf(msg, sizeof msg, "index %lld is out of range for a string of %lld", i, n);
        pk_panic(file, line, msg);
    }
    return pk_str_slice(s, at, at + 1);
}

PkList *pk_chars(const char *s) {
    PkList *l = pk_list_new(pk_len(s), 8);
    while (*s) {
        long long n = pk_skip(s, 1);
        *(char **)pk_list_push(l, 8) = pk_strndup(s, n);
        s += n;
    }
    return l;
}

PkList *pk_split(const char *s, const char *sep) {
    PkList *l = pk_list_new(4, 8);
    size_t k = strlen(sep);
    if (!k) {  /* no separator: split on runs of whitespace, like Python */
        while (*s) {
            while (*s && isspace((unsigned char)*s)) s++;
            const char *start = s;
            while (*s && !isspace((unsigned char)*s)) s++;
            if (s > start) *(char **)pk_list_push(l, 8) = pk_strndup(start, s - start);
        }
        return l;
    }
    for (const char *hit; (hit = strstr(s, sep)); s = hit + k)
        *(char **)pk_list_push(l, 8) = pk_strndup(s, hit - s);
    *(char **)pk_list_push(l, 8) = pk_strndup(s, strlen(s));
    return l;
}

char *pk_join(PkList *l, const char *sep) {
    size_t n = 1, k = strlen(sep);
    char **items = (char **)l->data;
    for (long long i = 0; i < l->len; i++) n += strlen(items[i]) + k;
    char *r = pk_alloc(n), *p = r;
    for (long long i = 0; i < l->len; i++) {
        if (i) { memcpy(p, sep, k); p += k; }
        size_t m = strlen(items[i]);
        memcpy(p, items[i], m);
        p += m;
    }
    *p = 0;
    return r;
}

char *pk_trim(const char *s) {
    while (isspace((unsigned char)*s)) s++;
    size_t n = strlen(s);
    while (n && isspace((unsigned char)s[n - 1])) n--;
    return pk_strndup(s, n);
}

char *pk_case(const char *s, long long upper) {  /* ASCII letters only; other characters pass through */
    char *r = pk_strndup(s, strlen(s));
    for (char *p = r; *p; p++) *p = upper ? toupper((unsigned char)*p) : tolower((unsigned char)*p);
    return r;
}

char *pk_replace(const char *s, const char *a, const char *b) {
    if (!*a) return pk_strndup(s, strlen(s));
    PkList *parts = pk_split(s, a);
    return pk_join(parts, b);
}

long long pk_find(const char *s, const char *x) {
    const char *hit = strstr(s, x);
    return hit ? pk_len(pk_strndup(s, hit - s)) : -1;
}

long long pk_starts(const char *s, const char *p) { return strncmp(s, p, strlen(p)) == 0; }

long long pk_ends(const char *s, const char *p) {
    size_t n = strlen(s), k = strlen(p);
    return k <= n && strcmp(s + n - k, p) == 0;
}

char *pk_fixed(double v, long long digits) {
    char *r = pk_alloc(64);
    snprintf(r, 64, "%.*f", (int)(digits < 0 ? 0 : digits > 30 ? 30 : digits), v);
    return r;
}

PkList *pk_list_slice(PkList *l, long long size, long long a, long long b) {
    pk_clamp(l->len, &a, &b);
    PkList *r = pk_list_new(b - a, size);
    memcpy(r->data, l->data + a * size, (b - a) * size);
    r->len = b - a;
    return r;
}

/* ---- the outside world: arguments, files, the clock, randomness */
static int pk_argc;
static char **pk_argv;
void pk_set_args(int argc, char **argv) { pk_argc = argc; pk_argv = argv; }

PkList *pk_args(void) {
    PkList *l = pk_list_new(pk_argc, 8);
    for (int i = 1; i < pk_argc; i++) *(char **)pk_list_push(l, 8) = pk_argv[i];
    return l;
}

static char *pk_slurp(FILE *f) {
    size_t cap = 4096, n = 0, got;
    char *buf = pk_alloc(cap);
    while ((got = fread(buf + n, 1, cap - n - 1, f)) > 0) {
        n += got;
        if (cap - n < 2) { cap *= 2; buf = realloc(buf, cap); }
    }
    buf[n] = 0;
    return buf;
}

char *pk_read_file(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    char *text = pk_slurp(f);
    fclose(f);
    return text;
}

char *pk_read_stdin(void) { return pk_slurp(stdin); }

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

void pk_index_panic(const char *file, long long line, long long i, long long len) {
    static char msg[96];
    snprintf(msg, sizeof msg, "index %lld is out of range for a list of %lld", i, len);
    pk_panic(file, line, msg);
}

char *pk_input(const char *prompt) {
    fputs(prompt, stdout);
    fflush(stdout);
    size_t cap = 0;
    char *buf = NULL;
    ssize_t n = getline(&buf, &cap, stdin);
    if (n <= 0) return "";
    if (buf[n - 1] == '\n') buf[n - 1] = 0;
    return buf;
}
"""


# ---------------------------------------------------------------- codegen
LL = {"int": ir.IntType(64), "float": ir.DoubleType(), "bool": ir.IntType(1),
      "str": ir.IntType(8).as_pointer(), "void": ir.VoidType()}
LIST = ir.LiteralStructType([LL["int"], LL["int"], LL["str"]]).as_pointer()  # len, cap, data
CLOSURE = ir.LiteralStructType([LL["str"], LL["str"]]).as_pointer()  # code, captured variables
I32 = ir.IntType(32)


def captures(body):
    """Names any closure inside body refers to. Conservative: a name is enough."""
    out = set()
    for node in walk(body):
        if isinstance(node, Lambda):
            out |= {n.name for n in walk(node.body) if isinstance(n, Name)} - {p for p, _ in node.params}
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
BUILTINS = {"print", "int", "float", "str", "len", "input"}  # user functions cannot take these names
FMT = {"int": "%lld", "float": "%.15g", "str": "%s", "bool": "%s"}


@dataclass
class Var:
    ptr: object
    ty: str
    mutable: bool


class Codegen:
    def __init__(self, name, file=None, files=None):
        self.files = files or [file or name]  # what runtime errors call each source file: the path you typed
        self.module = ir.Module(name=name)
        self.module.triple = TRIPLE
        self.fns = {}       # name or Struct.method -> Sig
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
        if fn_sig(ty):
            return CLOSURE
        if ty.startswith("["):
            return LIST if is_list(ty) else LL["str"]  # a dict is an opaque runtime pointer
        if ty in LL:
            return LL[ty]
        if ty in self.structs:
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
    def program(self, items):
        structs = [x for x in items if isinstance(x, Struct)]
        enums = [x for x in items if isinstance(x, Enum)]
        fns = [(f.name, f, []) for f in items if isinstance(f, Fn)]
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
            fns += [(f"{t.name}.{m.name}", m, [("self", t.name)]) for m in t.methods]
        for key, f, recv in fns:
            if key in self.fns:
                raise PlankError(f.line, f"function {key!r} defined twice")
            if key in BUILTINS or key in self.structs or key in self.enums:  # math helpers like sqrt can be redefined, these cannot
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
        if s.expr is None:
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

    def s_ForIn(self, s):
        items, ty = self.expr(s.items)
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
        x = self.declare(s.name, ty[1:-1], False, s.line)
        cond_bb, body_bb = b.append_basic_block("forin"), b.append_basic_block("body")
        step_bb, end_bb = b.append_basic_block("step"), b.append_basic_block("endfor")
        b.branch(cond_bb)
        b.position_at_end(cond_bb)
        b.cbranch(b.icmp_signed("<", b.load(i), self.list_len(items)), body_bb, end_bb)
        b.position_at_end(body_bb)
        b.store(b.load(self.slot(items, b.load(i), ty[1:-1])), x)
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
        ty = items[0][1]
        for _, t in items:
            if t != ty:
                raise PlankError(e.line, f"a list holds one type, this one mixes {ty} and {t}")
        lst = self.builder.call(new, [ir.Constant(LL["int"], len(items)), ir.Constant(LL["int"], size(ty))])
        for v, _ in items:
            self.push(lst, v, ty)
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

    def str_method(self, e, s, args):
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
        kv = dict_kv(ct)
        if kv:
            slot = self.dict_slot(coll, kv, item, it, e.line, "pk_dict_find")
            return b.icmp_unsigned("!=", slot, ir.Constant(slot.type, None)), "bool"
        if is_list(ct):
            if not fits(it, ct[1:-1]):
                raise PlankError(e.line, f"this list holds {ct[1:-1]}, got {it}")
            at = self.call_c("pk_list_find", "int", coll, ir.Constant(LL["int"], size(it)), self.bits(item, it),
                             ir.Constant(LL["int"], int(it == "str")))
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

    def push(self, lst, val, elem):
        grow = self.c("pk_list_push", LL["str"], LIST, LL["int"])
        at = self.builder.call(grow, [lst, ir.Constant(LL["int"], size(elem))])
        self.builder.store(val, self.builder.bitcast(at, self.ll(elem).as_pointer()))

    def e_Method(self, e):
        if self.is_enum_name(e.target):
            return self.make_case(e, e.target.name, e.name, e)
        target, ty = self.expr(e.target)
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

    def is_enum_name(self, node):
        return isinstance(node, Name) and node.name in self.enums and not any(node.name in sc for sc in self.scopes)

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
        free = [(n, v) for n in sorted({x.name for x in walk(e.body) if isinstance(x, Name)} - {p for p, _ in params})
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
        free = [(n, v) for n in sorted({x.name for x in walk(e.body) if isinstance(x, Name)} - {p for p, _ in params})
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
            if ret is None:
                _, ty = self.expr(e.body[0].expr, allow_void=True)
                self.probed = ty
                b.unreachable()
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
        if "nil" in (lt, rt) and e.op in ("==", "!="):
            val, ty = (lhs, lt) if rt == "nil" else (rhs, rt)
            if ty == "nil":
                return ir.Constant(LL["bool"], int(e.op == "==")), "bool"
            if not ty.endswith("?"):
                raise PlankError(e.line, f"{ty} is never nil; only optionals like {ty}? can be")
            return self.builder.icmp_unsigned(e.op, val, ir.Constant(val.type, None)), "bool"
        if lt != rt:
            fix = "str()" if "str" in (lt, rt) else "int() or float()"
            if lt.endswith("?") or rt.endswith("?"):
                fix = "if let, ?? or ! to get the value out of the optional first"
            raise PlankError(e.line, f"{lt} {e.op} {rt}: types must match, use {fix}")
        b = self.builder
        if lt == "str" and e.op == "+":
            return self.call_c("pk_concat", "str", lhs, rhs), "str"
        if lt == "str" and e.op in CMP:
            diff = b.call(self.c("strcmp", ir.IntType(32), LL["str"], LL["str"]), [lhs, rhs])  # C int, 32 bits
            return b.icmp_signed(e.op, diff, ir.Constant(diff.type, 0)), "bool"
        if lt in self.enums and e.op in ("==", "!="):
            if any(f for _, f in self.enums[lt].cases):
                raise PlankError(e.line, f"{lt} cases carry values, so == is ambiguous; use match")
            tags = [b.load(b.gep(v, [ir.Constant(I32, 0), ir.Constant(I32, 0)])) for v in (lhs, rhs)]
            return b.icmp_signed(e.op, *tags), "bool"
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
            return b.call(sig.func, self.arrange(e, f"{e.name}()", sig.params, sig.defaults)), sig.ret
        if e.name in self.structs:
            return self.construct(e), e.name
        if any(e.labels):
            raise PlankError(e.line, f"{e.name}() does not take labels")
        builtin = getattr(self, "b_" + e.name, None)
        if builtin is None:
            raise PlankError(e.line, f"unknown function {e.name!r}")
        args = []
        for a in e.args:
            val, ty = self.expr(a)
            if e.name == "print" and ty not in FMT:  # show a list as it is now, not after later arguments run
                val, ty = self.to_str(val, ty), "str"
            args.append((val, ty))
        return builtin(e, args)

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
            raise PlankError(e.line, f"{ty} has no field {e.name!r}, it has {', '.join(fields)}")
        i = fields.index(e.name)
        return self.builder.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, i)]), self.structs[ty].fields[i][1]

    def e_Field(self, e):
        if self.is_enum_name(e.target):
            return self.make_case(e, e.target.name, e.name, None)
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

    def b_read_stdin(self, e, args):
        self.typed(e, args)
        return self.call_c("pk_read_stdin", "str"), "str"

    def b_env(self, e, args):
        return self.maybe(self.call_c("pk_env", "str", *self.typed(e, args, "str")), "str")

    def b_exit(self, e, args):
        self.builder.call(self.c("pk_exit", ir.VoidType(), LL["int"]), self.typed(e, args, "int"))
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
    files, items, todo = [path], [], [(src, path)]
    seen = {os.path.realpath(path)} if os.path.exists(path) else set()
    while todo:
        text, at = todo.pop(0)
        for it in Parser(lex(text, files.index(at) * STRIDE + 1)).program():
            if not isinstance(it, Import):
                items.append(it)
                continue
            target = os.path.normpath(os.path.join(os.path.dirname(at), it.path))
            if os.path.realpath(target) in seen:
                continue
            try:
                with open(target) as f:
                    todo.append((f.read(), target))
            except OSError:
                raise PlankError(it.line, f"cannot import {it.path!r}: no file at {target}")
            seen.add(os.path.realpath(target))
            files.append(target)
    return items, files


def compile_source(src, name="plank", file=None):
    files = [file or name]
    try:
        items, files = load(src, file or name)
        return Codegen(name, file, files).program(items)
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


def build(path, out=None):
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
        link = subprocess.run(["cc", "-O2", "-w", obj, rt, "-o", out, "-lm"], capture_output=True, text=True)
        if link.returncode:
            raise PlankError(0, "linking failed, this is a Plank bug, please report it:\n" + link.stderr.strip())
    finally:
        os.unlink(obj); os.unlink(rt); os.rmdir(tmp)
    return out


def main(argv=sys.argv[1:]):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] == "--version":
        print(f"plank {VERSION}")
        return 0
    cmd, rest = (argv[0], argv[1:]) if argv[0] in ("run", "build", "emit") else ("run", argv)
    if not rest:
        print("plank: need a .pk file", file=sys.stderr)
        return 2
    path = rest[0]
    out = rest[rest.index("-o") + 1] if "-o" in rest else None
    prog_args = [a for i, a in enumerate(rest[1:], 1) if a != "-o" and (i < 2 or rest[i - 1] != "-o")]
    try:
        if cmd == "emit":
            with open(path) as f:
                print(compile_source(f.read(), os.path.basename(path), path))
            return 0
        if cmd == "build":
            print(build(path, out))
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
