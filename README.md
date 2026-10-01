<img src="icon.svg" width="80" alt="Plank logo">

# Plank

Building a language sounds like a year of work. Real compilers are a hundred thousand lines. Most tutorials stop right before the part where it makes a binary.

Plank is a small compiled language whose whole compiler is one Python file. You write structs, enums with match, optionals, closures, lists and dicts, and it hands you a native binary. LLVM does the register allocation and the optimizer. The file does the rest, and you can read it in an evening.

```
fn fib(n: int) -> int {
  if n < 2 { return n }
  return fib(n - 1) + fib(n - 2)
}

fn main() {
  for i in 0..15 { print(fib(i)) }
}
```

```
$ plank fib.pk
0
1
1
2
3
...
```

Most language tutorials stop at a tree-walking interpreter. Plank skips the interpreter and goes straight to machine code, so what you build on day one is what a real compiler builds, just smaller.

v0 is what you see here: the core types, functions, control flow, one file, native binaries on macOS and Linux. v1 adds arrays, structs and a `len`, which is enough to write real programs in it. It is free and stays free. It exists to be read, forked and taught from.

## Run it

```
git clone https://github.com/nulljosh/plank && cd plank
./plank examples/fib.pk            # compile and run
./plank build examples/fib.pk      # native binary at examples/fib
./plank emit examples/fib.pk       # print the LLVM IR
python3 test.py                    # every example, diffed
```

Needs `uv` and a C compiler for linking (`cc`). The first run installs llvmlite on its own. The language reference is in `docs/SPEC.md`, the file map in `docs/ARCHITECTURE.md`, and how it stacks up against Python, Ruby and Swift in `docs/COMPARE.md`. Live at [plank.heyitsmejosh.com](https://plank.heyitsmejosh.com).
