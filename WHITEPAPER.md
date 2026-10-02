# Why Plank is shaped this way

The short version comes from Paul Graham's Hackers and Painters: a language is a medium for sketching, its power is measured in how short programs get, and it should be built from a few ideas that generate the rest. `docs/HACKERS-AND-PAINTERS.md` has the summary and the rules. The rest of this paper is how those rules became decisions.

Plank is a compiled language whose only goal is to be understood in full by one person in one sitting. Every design choice below falls out of that.

## One file

A compiler split across twenty modules asks you to hold a map in your head before you can read a line. One file reads top to bottom: tokens, then trees, then machine code. The order of the file is the order of the pipeline. That is the whole architecture document, and it is also the reason there is no plugin system, no intermediate representation of our own, and no separate type checker.

## No separate type checker

Each expression's code generator returns two things, the LLVM value and the Plank type. The type rules live next to the code that needs them, so the check for "int plus float" sits in the same six lines that emit `add` or `fadd`. A separate pass would be more textbook and twice as long.

## No implicit conversions

`1 + 2.0` is an error. This is the single decision that keeps the type rules small enough to fit on one page of the spec. Three conversion functions, `int()`, `float()` and `str()`, cover every case a beginner hits, and the error message tells them which one to use.

## Straight to native code

Most first languages are tree-walking interpreters because an interpreter is easy to write. But an interpreter teaches you about interpreters. Plank hands its tree to LLVM, and LLVM does register allocation, constant folding, inlining, and the last mile to Mach-O or ELF. The student writes the front end, which is the part that makes a language a language, and gets a real binary that runs fib(35) in tens of milliseconds. The cost is one dependency, llvmlite, which the script installs for itself.

## Python

The compiler is Python because Python is the language most people can already read. Speed of the compiler does not matter at this size; speed of the output does, and LLVM handles that.

## A small runtime

LLVM gives you arithmetic and branches. It does not give you a string that grows or a list you can append to. Real languages ship a runtime for that, and so does Plank: a few dozen lines of C, kept as a string inside plank.py and compiled next to every program. Joining strings, counting characters, growing a list. Anything that can be plain IR, like a bounds check, stays IR so LLVM can see through it.

## Lists share, like Python

A list is a pointer to one struct. Pass it to a function and the function changes the same list. Swift copies instead, which is safer and needs copy-on-write machinery Plank would have to explain. Sharing is one sentence in the spec.

## Errors jump

A runtime error in Plank goes through one C function. Without a `try` open it prints the file and line and exits. With one open it jumps back to the `try` with `longjmp`, and the catch block gets the message. One mechanism serves bounds checks, missing keys, bad numbers and your own `throw`. The price is that a function holding a `try` keeps its variables in memory instead of registers, so the jump cannot lose a value.

## Memory is collected, conservatively

A precise collector needs the compiler to tell it where every pointer lives, in every stack frame and every register, which means a whole extra layer of bookkeeping in the code generator. Plank does what Boehm's collector does instead: it treats any word that happens to point into a block as a pointer. Once in a while it keeps something alive by accident. It never frees something alive. That trade bought a collector in about 120 lines of C, and LLVM never had to know.

## Generics by copying

A generic function is kept as a tree, not compiled. Each call works out the type parameters from its arguments, copies the tree with the names filled in, and compiles that copy once. Swift does the same under the name specialization; Plank does only that, and skips the shared generic code path Swift also keeps. The cost is a copy per distinct type, which for a teaching compiler is nothing, and the reward is that generics are forty lines, and a generic function runs exactly as fast as one written by hand.

## The formatter is the parser run backwards

`plank fmt` does not pattern-match text. It parses the file, then prints the tree in the house layout. Comments would be lost, so the lexer hands them over with their line numbers and the printer puts each one back before the first statement past it. A blank line survives where the source had one, by the same arithmetic. The formatter refuses any file it cannot print twice to the same text, which is how it checks itself.

## Where it stands

4.0 does what Python, Ruby and Swift programs do every day: modules and packages from GitHub, Result and ?, sets, dates, files, regular expressions, generics over functions, structs and enums, C by name, and errors you can catch, compiled to a native binary that can carry its libc with it. It frees its memory while running and ships with a REPL, a formatter, a test runner and its own built-in help. `docs/COMPARE.md` is the scorecard, 54 of 54. Each feature still has to earn its lines, and the file still has to read in a sitting.
