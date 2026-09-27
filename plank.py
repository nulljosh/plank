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

VERSION = "0.1.0"
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
    (?P<ws>[ \t]+) | (?P<comment>\#[^\n]*) | (?P<nl>\n) |
    (?P<float>\d+\.\d+) | (?P<int>\d+) | (?P<str>"(?:[^"\\]|\\.)*") |
    (?P<name>[A-Za-z_]\w*) |
    (?P<op>->|\.\.|==|!=|<=|>=|[-+*/%<>=(){}:,])
""", re.X)


@dataclass
class Tok:
    kind: str
    val: object
    line: int


def lex(src):
    toks, line, pos, depth = [], 1, 0, 0
    while pos < len(src):
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
        elif kind == "str":
            toks.append(Tok("str", bytes(text[1:-1], "utf-8").decode("unicode_escape"), line))
        elif kind == "name":
            toks.append(Tok(text if text in KEYWORDS else "name", text, line))
        else:
            depth += text in "(" and 1 or text in ")" and -1 or 0
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
class Assign(Node): name: str; expr: Node
@dataclass
class If(Node): cond: Node; then: list; other: list
@dataclass
class While(Node): cond: Node; body: list
@dataclass
class For(Node): name: str; start: Node; stop: Node; body: list
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
            self.expect("..")
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
        if self.at("name") and self.toks[self.i + 1].kind == "=":
            self.next(); self.next()
            return Assign(t.line, t.val, self.expr())
        return ExprStmt(t.line, self.expr())

    def if_(self):
        line = self.expect("if").line
        cond = self.expr()
        then = self.block()
        other = []
        if self.at("else"):
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
        t = self.next()
        if t.kind == "int":
            return Num(t.line, t.val, "int")
        if t.kind == "float":
            return Num(t.line, t.val, "float")
        if t.kind == "str":
            return Str(t.line, t.val)
        if t.kind in ("true", "false"):
            return Bool(t.line, t.kind == "true")
        if t.kind == "(":
            e = self.expr()
            self.expect(")")
            return e
        if t.kind == "name":
            if self.at("("):
                self.next()
                args = []
                while not self.at(")"):
                    args.append(self.expr())
                    if not self.at(")"):
                        self.expect(",")
                self.expect(")")
                return Call(t.line, t.val, args)
            return Name(t.line, t.val)
        got = t.kind if t.val is None else repr(t.val)
        raise PlankError(t.line, f"unexpected {got}")


# ---------------------------------------------------------------- codegen
LL = {"int": ir.IntType(64), "float": ir.DoubleType(), "bool": ir.IntType(1),
      "str": ir.IntType(8).as_pointer(), "void": ir.VoidType()}
INT_OPS = {"+": "add", "-": "sub", "*": "mul", "/": "sdiv", "%": "srem"}
FLOAT_OPS = {"+": "fadd", "-": "fsub", "*": "fmul", "/": "fdiv", "%": "frem"}
CMP = {"==", "!=", "<", ">", "<=", ">="}


@dataclass
class Var:
    ptr: object
    ty: str
    mutable: bool


class Codegen:
    def __init__(self, name):
        self.module = ir.Module(name=name)
        self.module.triple = TRIPLE
        self.fns = {}       # name -> (ir func, param types, ret type)
        self.scopes = []
        self.loops = []     # (continue block, break block)
        self.strings = {}
        self.builder = self.fn_ret = None
        printf_ty = ir.FunctionType(ir.IntType(32), [LL["str"]], var_arg=True)
        self.printf = ir.Function(self.module, printf_ty, "printf")

    # -- helpers
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
            ptr = self.builder.alloca(LL[ty], name=name)
        self.scopes[-1][name] = Var(ptr, ty, mutable)
        return ptr

    # -- program
    def program(self, fns):
        for f in fns:
            if f.name in self.fns:
                raise PlankError(f.line, f"function {f.name!r} defined twice")
            fty = ir.FunctionType(LL[f.ret], [LL[t] for _, t in f.params])
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
        if s.ty and s.ty != ty:
            raise PlankError(s.line, f"{s.name!r} is declared {s.ty} but assigned {ty}")
        self.builder.store(val, self.declare(s.name, ty, s.mutable, s.line))

    def s_Assign(self, s):
        var = self.lookup(s.name, s.line)
        if not var.mutable:
            raise PlankError(s.line, f"{s.name!r} is a let, use var to reassign it")
        val, ty = self.expr(s.expr)
        if ty != var.ty:
            raise PlankError(s.line, f"cannot assign {ty} to {s.name!r} which is {var.ty}")
        self.builder.store(val, var.ptr)

    def s_ExprStmt(self, s):
        self.expr(s.expr, allow_void=True)

    def s_Return(self, s):
        if s.expr is None:
            if self.fn_ret != "void":
                raise PlankError(s.line, f"return needs a {self.fn_ret} value")
            self.builder.ret_void()
            return
        val, ty = self.expr(s.expr)
        if ty != self.fn_ret:
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
        self.loops.append((cond_bb, end_bb))
        self.stmts(s.body)
        self.loops.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_bb)
        self.builder.position_at_end(end_bb)

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
        self.loops.append((step_bb, end_bb))
        self.stmts(s.body)
        self.loops.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(step_bb)
        self.builder.position_at_end(step_bb)
        self.builder.store(self.builder.add(self.builder.load(i), ir.Constant(LL["int"], 1)), i)
        self.builder.branch(cond_bb)
        self.builder.position_at_end(end_bb)
        self.scopes.pop()

    def s_Break(self, s):
        if not self.loops:
            raise PlankError(s.line, "break outside a loop")
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
            raise PlankError(e.line, f"{lt} {e.op} {rt}: types must match, use int() or float()")
        b = self.builder
        if e.op in CMP:
            if lt == "float":
                return b.fcmp_ordered(e.op, lhs, rhs), "bool"
            if lt == "str" or (lt == "bool" and e.op not in ("==", "!=")):
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
        args = [self.expr(a) for a in e.args]
        if e.name == "print":
            if len(args) != 1:
                raise PlankError(e.line, "print takes one argument")
            val, ty = args[0]
            fmt = {"int": "%lld\n", "float": "%g\n", "str": "%s\n", "bool": "%s\n"}[ty]
            if ty == "bool":
                val = b.select(val, self.cstr("true"), self.cstr("false"))
            b.call(self.printf, [self.cstr(fmt), val])
            return None, "void"
        if e.name in ("int", "float"):
            if len(args) != 1:
                raise PlankError(e.line, f"{e.name}() takes one argument")
            val, ty = args[0]
            if ty == e.name:
                return val, ty
            if e.name == "int" and ty == "float":
                return b.fptosi(val, LL["int"]), "int"
            if e.name == "int" and ty == "bool":
                return b.zext(val, LL["int"]), "int"
            if e.name == "float" and ty == "int":
                return b.sitofp(val, LL["float"]), "float"
            raise PlankError(e.line, f"cannot convert {ty} to {e.name}")
        if e.name not in self.fns:
            raise PlankError(e.line, f"unknown function {e.name!r}")
        func, ptypes, ret = self.fns[e.name]
        if len(args) != len(ptypes):
            raise PlankError(e.line, f"{e.name}() takes {len(ptypes)} arguments, got {len(args)}")
        for i, ((_, got), want) in enumerate(zip(args, ptypes)):
            if got != want:
                raise PlankError(e.line, f"{e.name}() argument {i + 1} should be {want}, got {got}")
        return b.call(func, [v for v, _ in args]), ret


# ---------------------------------------------------------------- driver
def compile_source(src, name="plank"):
    return Codegen(name).program(Parser(lex(src)).program())


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
    module = compile_source(src, os.path.basename(path))
    tm, mod = optimize(str(module))
    out = out or os.path.splitext(path)[0]
    with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as obj:
        obj.write(tm.emit_object(mod))
    try:
        subprocess.run(["cc", obj.name, "-o", out], check=True)
    finally:
        os.unlink(obj.name)
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
