<img src="icon.svg" width="80" alt="Plank logo">

# Plank

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

1.0 has what you reach for in Python, Ruby or Swift: strings with interpolation, lists, dicts, structs with methods, enums with an exhaustive `match`, optionals, closures with `map` and `filter`, imports, files, and `try` and `catch` for every runtime error. `docs/COMPARE.md` keeps score: 22 of 23. The one missing piece is freeing memory while a program runs, so Plank suits tools and scripts that run and finish.

## What you can build

`apps/` holds real programs, each run by the test suite on every push:

- `calc.pk`, a calculator with its own tokenizer and recursive-descent parser. A language written in Plank.
- `todo.pk`, a to-do list for the command line that saves to a file.
- `wordfreq.pk`, the most common words in any text file.
- `ledger.pk`, budget CSV in, totals by category out, bad lines skipped.
- `maze.pk`, the shortest path through a maze, drawn back onto the map.
- `life.pk`, Conway's Game of Life.

It is free and stays free. It exists to be read, forked and taught from.

## Run it

```
git clone https://github.com/nulljosh/plank && cd plank
./plank examples/fib.pk            # compile and run
./plank build examples/fib.pk      # native binary at examples/fib
./plank emit examples/fib.pk       # print the LLVM IR
./plank apps/todo.pk add "milk"    # arguments go to the program
python3 test.py                    # every example and app, diffed, plus the error messages
```

Needs `uv` and a C compiler for linking (`cc`). The first run installs llvmlite on its own. The language reference is in `docs/SPEC.md`, the file map in `docs/ARCHITECTURE.md`, and how it stacks up against Python, Ruby and Swift in `docs/COMPARE.md`. Live at [plank.heyitsmejosh.com](https://plank.heyitsmejosh.com).
