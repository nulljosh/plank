# Plank

Building a language always sounds like a year of work. You read about parsers and register allocators and you close the tab. Every real compiler is a hundred thousand lines you will never finish reading. Every tutorial stops right before the part where it makes a binary. That's the gap.

Plank is a small compiled language whose whole compiler is one Python file. You write functions, ints, floats, bools, strings, if, while, for, and it hands you a native binary. LLVM does the register allocation and the optimizer. The file does the rest, and you can read it in an evening.

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

That's it. That's the whole product.

Most language tutorials build a tree-walking interpreter and call it a day, which is like learning to drive in a golf cart. Plank goes the other way. It skips the interpreter and goes straight to machine code, so the thing you build on day one is the thing a real compiler builds, just smaller. Same road, smaller car.

v0 is what you see here: the core types, functions, control flow, one file, native binaries on macOS and Linux. v1 adds arrays, structs and a `len`, which is enough to write real programs in it. It is free and stays free. It exists to be read, forked and taught from.

## Run it

```
git clone https://github.com/nulljosh/plank && cd plank
./plank examples/fib.pk            # compile and run
./plank build examples/fib.pk      # native binary at examples/fib
./plank emit examples/fib.pk       # print the LLVM IR
python3 test.py                    # every example, diffed
```

Needs `uv` and a C compiler for linking (`cc`). The first run installs llvmlite on its own. The language reference is in `docs/SPEC.md`, the file map in `docs/ARCHITECTURE.md`. Live at [plank.heyitsmejosh.com](https://plank.heyitsmejosh.com).
