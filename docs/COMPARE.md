# Plank next to Python, Ruby and Swift

The goal: write the programs you would write in Python, Ruby or Swift, in Plank, and get a native binary. This page is the scorecard. Each row is something people reach for every day. A row turns to yes when it works, has an example in `examples/`, and is in `docs/SPEC.md`.

| Feature | Python 3.14 | Ruby 3.4 | Swift 6 | Plank |
|---|---|---|---|---|
| Native binary | no | no | yes | yes |
| Static types, inferred | hints only | no | yes | yes |
| Functions, recursion | yes | yes | yes | yes |
| if, while, for, break, continue | yes | yes | yes | yes |
| Compound assignment `+=` | yes | yes | yes | yes (0.2) |
| String join, compare, length | yes | yes | yes | yes (0.2) |
| String interpolation | f-strings | `#{}` | `\()` | yes, `\()` (0.2) |
| Read input, parse numbers | yes | yes | yes | yes (0.2) |
| Math library | yes | yes | yes | yes (0.2) |
| Lists, indexing, append | yes | yes | yes | yes (0.3) |
| for-in over a collection | yes | yes | yes | yes (0.3) |
| Structs or classes with methods | yes | yes | yes | yes (0.4) |
| Default and named arguments | yes | yes | yes | yes (0.4) |
| Dicts | yes | yes | yes | yes (0.5) |
| Enums and pattern matching | `match` | `case/in` | `switch` | yes (0.6) |
| Optionals or nil | None | nil | `?` | yes (0.7) |
| Closures, first-class functions | yes | blocks | yes | yes (0.8) |
| map, filter, reduce, sort | yes | yes | yes | yes (0.8) |
| String methods: split, join, contains, slices | yes | yes | yes | yes (0.9) |
| Errors you can catch | try | rescue | try | yes (1.0) |
| Multiple files, imports | yes | yes | yes | yes (0.10) |
| Files and command-line args | yes | yes | yes | yes (0.10) |
| Memory reclaimed | GC | GC | ARC | yes, GC (1.1) |

Out of scope for now, on purpose: threads and async, a package manager, a REPL, a JIT. Each is a project the size of Plank itself.

## Score

23 of 23. Every row is a yes. The table grows from here: see the Next section.

## Next rows

| Feature | Python 3.14 | Ruby 3.4 | Swift 6 | Plank |
|---|---|---|---|---|
| Run a shell command | yes | yes | yes | yes (1.2) |
| JSON in and out | yes | yes | yes | yes (1.2) |
| HTTP requests | yes | yes | yes | yes (1.2) |
| Generic functions | duck typing | duck typing | yes | yes (1.3) |
| `if` as an expression | yes | yes | yes | yes (1.3) |
| Tests in the language | unittest | minitest | XCTest | `assert` + `plank test` (1.3) |
