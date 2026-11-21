<img src="icon.svg" width="80" alt="Plank logo" style="border-radius:18px">

[![version](https://img.shields.io/github/v/release/nulljosh/plank?label=version&color=blue)](https://github.com/nulljosh/plank/releases) [![tests](https://img.shields.io/github/actions/workflow/status/nulljosh/plank/test.yml?label=tests)](https://github.com/nulljosh/plank/actions) ![license](https://img.shields.io/badge/license-MIT-green) ![one file](https://img.shields.io/badge/compiler-one%20file-black)

# Plank

A small compiled language whose whole compiler is one Python file. Write structs, enums, closures, lists and dicts; get a native binary. LLVM does the optimizing, the file does the rest, and you can read it in an evening.

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
}
```

```
$ plank run shapes.pk
1 of 2 are big: [rect(w: 2, h: 3)]
```

## Install

```
brew install nulljosh/tap/plank-lang
```

Or clone the repo and run `./plank`. You need a C compiler (`cc`) for linking; the first run fetches llvmlite through `uv`.

## Use

```
plank run file.pk [args]     compile and run
plank build file.pk          native binary (--static for a portable Linux one)
plank emit file.pk           print the LLVM IR
plank repl                   try it a line at a time
plank test [dir]             run every .pk in a folder; each passes by printing ok
plank fmt [--check]          lay out .pk files the house way
plank doc [name]             the built-ins
plank tokens file.pk         the tokens the lexer sees
```

## Learn

- **[The Plank Book](book/)**: thirteen short chapters, from hello world to how the compiler works. Every program in it is compiled and checked by the test suite.
- [`docs/SPEC.md`](docs/SPEC.md): the reference, every rule on one page.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): the compiler, file by file.
- [`docs/COMPARE.md`](docs/COMPARE.md): how it stacks up against Python, Ruby and Swift.

## Toward 5.0

Plank is learning to compile itself. `compiler/plank.pk` is the compiler written in Plank; today it lexes every file in the repo exactly as `plank.py` does, and `test.py` holds it to that. When it can build itself, Plank needs nothing but a C compiler. Steps in `roadmap.md`.

## Develop

```
python3 test.py          # every example, app, test and book program, then all of it again under GC stress
python3 tools/gen-book.py  # rebuild the book page after editing book/*.md
```

MIT licensed. Free, and it stays free.
