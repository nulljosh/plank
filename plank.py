#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["llvmlite>=0.44"]
# ///
"""Plank: a small compiled language. Lexer, parser, codegen, one file.

    plank run hello.pk      compile and run
    plank build hello.pk    native binary next to the source
    plank emit hello.pk     print the LLVM IR
"""
import os, platform, re, subprocess, sys, tempfile
from dataclasses import dataclass, field

from llvmlite import binding, ir

VERSION = "0.3.0"
TRIPLE = binding.get_default_triple()
if sys.platform == "darwin":  # the default triple names a darwin the linker has not heard of
    TRIPLE = f"{platform.machine()}-apple-macosx{platform.mac_ver()[0]}"


class PlankError(Exception):
    def __init__(self, line, msg):
        super().__init__(msg)
        self.line = line


# ---------------------------------------------------------------- lexer
KEYWORDS = {"fn", "let", "var", "if", "else", "while", "for", "in", "return",
            "break", "continue", "true", "false", "and", "or", "not"}
TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t\r]+) | (?P<comment>\#[^\n]*) | (?P<nl>\n) |
    (?P<float>\d+\.\d+(?:[eE][+-]?\d+)?) | (?P<int>\d+) |
    (?P<name>[A-Za-z_]\w*) |
    (?P<op>\+=|-=|\*=|/=|%=|->|\.\.|==|!=|<=|>=|[-+*/%<>=(){}\[\]:,.])
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


def lex(src):
    toks, line, pos, depth = [], 1, 0, 0
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
class Binary(Node): op: str; left: Node; right: Node
@dataclass
class Call(Node): name: str; args: list
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
class Index(Node): target: Node; index: Node
@dataclass
class Method(Node): target: Node; name: str; args: list
@dataclass
class Return(Node): expr: Node
@dataclass
class Break(Node): pass
@dataclass
class Continue(Node): pass
@dataclass
class ExprStmt(Node): expr: Node
@dataclass
class Fn(Node): name: str; params: list; ret: str; body: list


# ---------------------------------------------------------------- parser
PREC = {"or": 1, "and": 2, "==": 4, "!=": 4, "<": 4, ">": 4, "<=": 4, ">=": 4,
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
        fns = []
        self.skip_nl()
        while not self.at("eof"):
            fns.append(self.fn())
            self.skip_nl()
        return fns

    def fn(self):
        line = self.expect("fn").line
        name = self.expect("name").val
        self.expect("(")
        params = []
        while not self.at(")"):
            pname = self.expect("name").val
            self.expect(":")
            params.append((pname, self.type()))
            if not self.at(")"):
                self.expect(",")
        self.expect(")")
        ret = "void"
        if self.at("->"):
            self.next()
            ret = self.type()
        return Fn(line, name, params, ret, self.block())

    def type(self):
        if self.at("["):
            self.next()
            inner = self.type()
            self.expect("]")
            return f"[{inner}]"
        t = self.expect("name")
        if t.val not in TYPES:
            raise PlankError(t.line, f"unknown type {t.val!r}")
        return t.val

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
        if self.at("break"):
            self.next()
            return Break(t.line)
        if self.at("continue"):
            self.next()
            return Continue(t.line)
        e = self.expr()
        if self.at("=", "+=", "-=", "*=", "/=", "%="):
            if not isinstance(e, (Name, Index)):
                raise PlankError(t.line, "only a variable or xs[i] can go left of =")
            op = self.next().kind
            val = self.expr()
            # ponytail: xs[f()] += 1 evaluates f() twice; a temp slot if that ever matters
            return Assign(t.line, e, val if op == "=" else Binary(t.line, op[0], e, val))
        return ExprStmt(t.line, e)

    def if_(self):
        line = self.expect("if").line
        cond = self.expr()
        then = self.block()
        other = []
        mark = self.i
        self.skip_nl()
        if not self.at("else"):
            self.i = mark
        else:
            self.next()
            other = [self.if_()] if self.at("if") else self.block()
        return If(line, cond, then, other)

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
        while self.at("[", "."):
            line = self.next().line
            if self.toks[self.i - 1].kind == "[":
                e = Index(line, e, self.expr())
                self.expect("]")
                continue
            name = self.expect("name").val
            self.expect("(")
            e = Method(line, e, name, self.args(")"))
        return e

    def args(self, close):
        out = []
        while not self.at(close):
            out.append(self.expr())
            if not self.at(close):
                self.expect(",")
        self.expect(close)
        return out

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
        if t.kind in ("true", "false"):
            return Bool(t.line, t.kind == "true")
        if t.kind == "(":
            e = self.expr()
            self.expect(")")
            return e
        if t.kind == "[":
            return List(t.line, self.args("]"))
        if t.kind == "name":
            if self.at("("):
                self.next()
                return Call(t.line, t.val, self.args(")"))
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

void pk_panic(const char *file, long long line, const char *msg) {
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

void pk_index_panic(const char *file, long long line, long long i, long long len) {
    char msg[96];
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
I32 = ir.IntType(32)


def ll(ty):
    """The LLVM type for a Plank type. Every list is the same pointer; [int] vs [str] lives in the Plank type."""
    return LIST if ty.startswith("[") else LL[ty]


def size(ty):
    return 1 if ty == "bool" else 8  # ponytail: 64-bit targets only


def fits(got, want):
    return got == want or (got == "[]" and want.startswith("["))
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
    def __init__(self, name, file=None):
        self.file = file or name  # what runtime errors call the file: the path you typed
        self.module = ir.Module(name=name)
        self.module.triple = TRIPLE
        self.fns = {}       # name -> (ir func, param types, ret type)
        self.scopes = []
        self.loops = []     # (continue block, break block)
        self.strings = {}
        self.builder = self.fn_ret = None
        self.printf = self.c("printf", ir.IntType(32), LL["str"], var_arg=True)

    # -- helpers
    def c(self, name, ret, *args, var_arg=False):
        """A C function from libc, libm or RUNTIME, declared on first use."""
        if name in self.module.globals:
            return self.module.globals[name]
        return ir.Function(self.module, ir.FunctionType(ret, args, var_arg=var_arg), name)

    def call_c(self, name, ret, *args):
        return self.builder.call(self.c(name, LL[ret], *[a.type for a in args]), list(args))

    def where(self, line):
        return [self.cstr(self.file), ir.Constant(LL["int"], line)]

    def to_str(self, val, ty):
        if ty == "str":
            return val
        if ty == "bool":
            return self.builder.select(val, self.cstr("true"), self.cstr("false"))
        if ty == "[]":
            return self.cstr("[]")
        if ty.startswith("["):
            return self.builder.call(self.show_list(ty), [val])
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
        with self.builder.goto_entry_block():
            ptr = self.builder.alloca(ll(ty), name=name)
        self.scopes[-1][name] = Var(ptr, ty, mutable)
        return ptr

    # -- program
    def program(self, fns):
        for f in fns:
            if f.name in self.fns:
                raise PlankError(f.line, f"function {f.name!r} defined twice")
            if f.name in BUILTINS:  # math helpers like sqrt can be redefined, these cannot
                raise PlankError(f.line, f"{f.name!r} is a built-in, pick another name")
            fty = ir.FunctionType(ll(f.ret), [ll(t) for _, t in f.params])
            self.fns[f.name] = (ir.Function(self.module, fty, "pk_" + f.name),
                                [t for _, t in f.params], f.ret)
        if "main" not in self.fns or self.fns["main"][1] or self.fns["main"][2] != "void":
            raise PlankError(1, "need a `fn main()` with no parameters and no return type")
        for f in fns:
            self.function(f)
        main = ir.Function(self.module, ir.FunctionType(ir.IntType(32), []), "main")
        b = ir.IRBuilder(main.append_basic_block())
        b.call(self.fns["main"][0], [])
        b.ret(ir.Constant(ir.IntType(32), 0))
        return self.module

    def function(self, f):
        func, _, self.fn_ret = self.fns[f.name]
        self.builder = ir.IRBuilder(func.append_basic_block("entry"))
        self.scopes = [{}]
        for (name, ty), arg in zip(f.params, func.args):
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
        val, ty = self.expr(s.expr)
        if s.ty and not fits(ty, s.ty):
            raise PlankError(s.line, f"{s.name!r} is declared {s.ty} but assigned {ty}")
        if ty == "[]" and not s.ty:
            raise PlankError(s.line, f"an empty list needs its type: let {s.name}: [int] = []")
        self.builder.store(val, self.declare(s.name, s.ty or ty, s.mutable, s.line))

    def s_Assign(self, s):
        if isinstance(s.target, Index):
            ptr, want = self.index_ptr(s.target)
            what = "this list"
        else:
            var = self.lookup(s.target.name, s.line)
            if not var.mutable:
                raise PlankError(s.line, f"{s.target.name!r} is a let, use var to reassign it")
            ptr, want, what = var.ptr, var.ty, repr(s.target.name)
        val, ty = self.expr(s.expr)
        if not fits(ty, want):
            raise PlankError(s.line, f"cannot assign {ty} to {what} which holds {want}")
        self.builder.store(val, ptr)

    def s_ExprStmt(self, s):
        self.expr(s.expr, allow_void=True)

    def s_Return(self, s):
        if s.expr is None:
            if self.fn_ret != "void":
                raise PlankError(s.line, f"return needs a {self.fn_ret} value")
            self.builder.ret_void()
            return
        val, ty = self.expr(s.expr)
        if not fits(ty, self.fn_ret):
            raise PlankError(s.line, f"returning {ty} from a function that returns {self.fn_ret}")
        self.builder.ret(val)

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

    def s_While(self, s):
        cond_bb = self.builder.append_basic_block("while")
        body_bb = self.builder.append_basic_block("body")
        end_bb = self.builder.append_basic_block("endwhile")
        self.builder.branch(cond_bb)
        self.builder.position_at_end(cond_bb)
        self.builder.cbranch(self.cond(s.cond), body_bb, end_bb)
        self.builder.position_at_end(body_bb)
        self.loops.append([cond_bb, end_bb, False])
        self.stmts(s.body)
        _, _, broke = self.loops.pop()
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
        self.loops.append([step_bb, end_bb, False])
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
        if not ty.startswith("[") or ty == "[]":
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
        self.loops.append([step_bb, end_bb, False])
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
        self.builder.branch(self.loops[-1][1])

    def s_Continue(self, s):
        if not self.loops:
            raise PlankError(s.line, "continue outside a loop")
        self.builder.branch(self.loops[-1][0])

    # -- expressions: each returns (llvm value, plank type)
    def expr(self, e, allow_void=False):
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
        return self.builder.gep(self.builder.bitcast(data, ll(elem).as_pointer()), [i])

    def index_ptr(self, e):
        """Pointer to xs[i], bounds checked. Negative i counts from the end, like Python."""
        lst, ty = self.expr(e.target)
        if not ty.startswith("[") or ty == "[]":
            raise PlankError(e.line, f"cannot index {ty}, only lists")
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
        ptr, ty = self.index_ptr(e)
        return self.builder.load(ptr), ty

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

    def push(self, lst, val, elem):
        grow = self.c("pk_list_push", LL["str"], LIST, LL["int"])
        at = self.builder.call(grow, [lst, ir.Constant(LL["int"], size(elem))])
        self.builder.store(val, self.builder.bitcast(at, ll(elem).as_pointer()))

    def e_Method(self, e):
        target, ty = self.expr(e.target)
        args = [self.expr(a) for a in e.args]
        if ty.startswith("[") and ty != "[]":
            elem = ty[1:-1]
            if e.name == "append":
                if len(args) != 1 or not fits(args[0][1], elem):
                    raise PlankError(e.line, f"append() takes one {elem}")
                self.push(target, args[0][0], elem)
                return None, "void"
            if e.name == "pop" and not args:
                pop = self.c("pk_list_pop", LL["str"], LIST, LL["int"], LL["str"], LL["int"])
                at = self.builder.call(pop, [target, ir.Constant(LL["int"], size(elem))] + self.where(e.line))
                return self.builder.load(self.builder.bitcast(at, ll(elem).as_pointer())), elem
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

    def e_Bool(self, e):
        return ir.Constant(LL["bool"], int(e.val)), "bool"

    def e_Name(self, e):
        var = self.lookup(e.name, e.line)
        return self.builder.load(var.ptr, name=e.name), var.ty

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
        lhs, lt = self.expr(e.left)
        rhs, rt = self.expr(e.right)
        if lt != rt:
            fix = "str()" if "str" in (lt, rt) else "int() or float()"
            raise PlankError(e.line, f"{lt} {e.op} {rt}: types must match, use {fix}")
        b = self.builder
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
        if e.name in self.fns:
            func, ptypes, ret = self.fns[e.name]
            args = [self.expr(a) for a in e.args]
            if len(args) != len(ptypes):
                raise PlankError(e.line, f"{e.name}() takes {len(ptypes)} argument{'s' * (len(ptypes) != 1)}, got {len(args)}")
            for i, ((_, got), want) in enumerate(zip(args, ptypes)):
                if not fits(got, want):
                    raise PlankError(e.line, f"{e.name}() argument {i + 1} should be {want}, got {got}")
            return b.call(func, [v for v, _ in args]), ret
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
        if ty.startswith("["):
            return (self.list_len(val) if ty != "[]" else ir.Constant(LL["int"], 0)), "int"
        if ty != "str":
            raise PlankError(e.line, f"len() needs a str or a list, got {ty}")
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

    def b_pow(self, e, args):
        return self.libm(e, args, 2)


# ---------------------------------------------------------------- driver
def compile_source(src, name="plank", file=None):
    return Codegen(name, file).program(Parser(lex(src)).program())


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
        subprocess.run(["cc", "-O2", "-w", obj, rt, "-o", out, "-lm"], check=True)
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
    try:
        if cmd == "emit":
            with open(path) as f:
                print(compile_source(f.read(), os.path.basename(path)))
            return 0
        if cmd == "build":
            print(build(path, out))
            return 0
        exe = build(path, out or os.path.join(tempfile.mkdtemp(), "a.out"))
        code = subprocess.run([exe]).returncode
        if not out:
            os.unlink(exe)
        return code
    except PlankError as err:
        print(f"{path}:{err.line}: {err}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"plank: no such file {path}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
