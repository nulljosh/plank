# Why Plank is shaped this way

Plank is a compiled language whose only goal is to be understood in full by one person in one sitting. Every design choice below falls out of that.

## One file

A compiler split across twenty modules asks you to hold a map in your head before you can read a line. One file reads top to bottom: tokens, then trees, then machine code. The order of the file is the order of the pipeline. That is the whole architecture document, and it is also the reason there is no plugin system, no intermediate representation of our own, and no separate type checker.

## No separate type checker

Each expression's code generator returns two things, the LLVM value and the Plank type. The type rules live next to the code that needs them, so the check for "int plus float" sits in the same six lines that emit `add` or `fadd`. A separate pass would be more textbook and twice as long.

## No implicit conversions

`1 + 2.0` is an error. This is the single decision that keeps the type rules small enough to fit on one page of the spec. Two conversion functions, `int()` and `float()`, cover every case a beginner hits, and the error message tells them which one to use.

## Straight to native code

Most first languages are tree-walking interpreters because an interpreter is easy to write. But an interpreter teaches you about interpreters. Plank hands its tree to LLVM, and LLVM does register allocation, constant folding, inlining, and the last mile to Mach-O or ELF. The student writes the front end, which is the part that makes a language a language, and gets a real binary that runs fib(35) in tens of milliseconds. The cost is one dependency, llvmlite, which the script installs for itself.

## Python

The compiler is Python because Python is the language most people can already read. Speed of the compiler does not matter at this size; speed of the output does, and LLVM handles that.

## What is deliberately missing

Arrays, structs, string operations, a module system, generics, a garbage collector. Each one is a real feature with a real place in the roadmap, and each one is also a chapter a reader would have to get through. Version 0 is the smallest thing that is honestly a compiled language. Everything after it has to earn its lines.
