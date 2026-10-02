<img src="icon.svg" width="80" alt="Plank logo" style="border-radius:18px">

# Plank

[![version](https://img.shields.io/github/v/release/nulljosh/plank?label=version&color=blue)](https://github.com/nulljosh/plank/releases) [![tests](https://img.shields.io/github/actions/workflow/status/nulljosh/plank/test.yml?label=tests)](https://github.com/nulljosh/plank/actions) ![license](https://img.shields.io/badge/license-MIT-green) ![one file](https://img.shields.io/badge/compiler-one%20file-black) [![scorecard](https://img.shields.io/badge/vs%20Python%2FRuby%2FSwift-23%2F23-brightgreen)](docs/COMPARE.md) [![GitHub](https://img.shields.io/badge/GitHub-nulljosh%2Fplank-black?logo=github)](https://github.com/nulljosh/plank)

**[plank.heyitsmejosh.com →](https://plank.heyitsmejosh.com)**

Building a language sounds like a year of work. Real compilers are a hundred thousand lines. Most tutorials stop right before the part where it makes a binary.

Plank is a small compiled language whose whole compiler is one Python file. You write structs, enums with match, optionals, closures, lists and dicts, and it hands you a native binary. LLVM does the register allocation and the optimizer. The file does the rest, and you can read it in an evening.

```
enum Shape {
  circle(r: float)
  rect(w: float, h: float)

  fn area() -> float {
    match self {
      .circle(r) { return 3.14159 * r * r }
      .rect(w, h) { return w * h }
    }
  }
}

fn main() {
  let shapes = [Shape.circle(1.0), Shape.rect(w: 2.0, h: 3.0)]
  let big = shapes.filter(fn(s) => s.area() > 4.0)
  print("\(len(big)) of \(len(shapes)) are big:", big)

  try {
    print(int("forty-two"))
  } catch err {
    print("caught:", err)
  }
}
```

```
$ plank shapes.pk
1 of 2 are big: [rect(w: 2, h: 3)]
caught: int() got text that is not a whole number
```

Most language tutorials stop at a tree-walking interpreter. Plank skips the interpreter and goes straight to machine code, so what you build on day one is what a real compiler builds, just smaller.

2.0 has what you reach for in Python, Ruby or Swift: strings with interpolation and regular expressions, lists, dicts and tuples, structs and enums with methods, an exhaustive `match`, optionals with `if let` and `?.`, closures with `map` and `filter`, generics, imports, files, shell, JSON and HTTP, C functions by name, and `try` and `catch` for every runtime error. A garbage collector frees what you stop using. A REPL, a formatter and a test runner come with it. `docs/COMPARE.md` keeps score: 42 of 42, every row a yes.

## What you can build

`apps/` holds real programs, each run by the test suite on every push:

- `agent.pk`, a tool-using agent loop: ask a model over HTTP, run the tool it names, feed the result back. The shape of a Samantha or Joshua Tree script.
- `calc.pk`, a calculator with its own tokenizer and recursive-descent parser. A language written in Plank.
- `todo.pk`, a to-do list for the command line that saves to a file.
- `wordfreq.pk`, the most common words in any text file.
- `ledger.pk`, budget CSV in, totals by category out, bad lines skipped.
- `maze.pk`, the shortest path through a maze, drawn back onto the map.
- `life.pk`, Conway's Game of Life.

It is free and stays free. It exists to be read, forked and taught from.

## Install

```
brew install nulljosh/plank/plank
```

Or clone the repo and run `./plank` straight from it. Either way you need a C compiler for linking (`cc`), and the first run fetches llvmlite by itself through `uv`.

## Usage

```
plank repl                     type Plank a line at a time and see what it does
plank run file.pk [args...]    compile and run; args() sees the arguments
plank build file.pk [-o out]   native binary, next to the source by default
plank build file.pk --static   a binary with no shared libraries, to copy to any Linux box
plank emit file.pk             print the LLVM IR
plank test [dir]               run every .pk in a folder; each passes by printing ok
plank fmt [--check] [files]    lay out .pk files the house way; --check only reports
plank --version
```

`PLANK_GC=4000` collects every 4KB, for shaking out bugs. The REPL rebuilds the whole program after every line and shows only the new output, so what you see is always what a real binary printed.

## The language in a minute

```
import "lib/money.pk"            # pulls in another file, once

struct Account {                 # fields, defaults, methods, implicit self
  owner: str
  balance: int = 0
  fn deposit(n: int) { self.balance += n }
}

enum Shape {                     # cases carry values; match must cover them all
  circle(r: float)
  dot
}

fn area(s: Shape) -> float {
  match s {
    .circle(r) { return 3.14 * r * r }
    .dot { return 0.0 }
  }
}

fn main() {
  let a = Account(owner: "ada")              # labels, or by position
  a.deposit(5)
  let xs = [3, 1, 2].sorted().map(fn(x) => x * 10)
  let d = ["k": 1]
  d["j"] = 2
  print("\(a.owner) has \(a.balance), \(xs), \(d.keys())")
  if let n = d.get("zzz") { print(n) } else { print("no zzz") }
  try {
    print(int("x"))
  } catch err {
    print("caught:", err)
  }
  let out = run("echo hi").trim()            # shell, JSON and HTTP are built in
  let j = json_parse("{\"n\": 1}")
  print(out, j.get("n").int(), status())
}
```

Everything here is in `docs/SPEC.md`, one page. `let` binds once, `var` can change. Types are inferred and never converted behind your back. Lists and dicts are shared; strings count characters. Every runtime error names the file and line and can be caught.

## Run it

```
git clone https://github.com/nulljosh/plank && cd plank
./plank examples/fib.pk            # compile and run
./plank build examples/fib.pk      # native binary at examples/fib
./plank emit examples/fib.pk       # print the LLVM IR
./plank apps/todo.pk add "milk"    # arguments go to the program
python3 test.py                    # every example, app and tests/*.pk, the error messages, then all of it under GC stress
```

The language reference is in `docs/SPEC.md`, the file map in `docs/ARCHITECTURE.md`, how it stacks up against Python, Ruby and Swift in `docs/COMPARE.md`, and the design philosophy, taken from Hackers and Painters, in `docs/HACKERS-AND-PAINTERS.md`. Live at [plank.heyitsmejosh.com](https://plank.heyitsmejosh.com).
