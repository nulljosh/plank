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
| Dicts | yes | yes | yes | no |
| Enums and pattern matching | `match` | `case/in` | `switch` | no |
| Optionals or nil | None | nil | `?` | no |
| Closures, first-class functions | yes | blocks | yes | no |
| map, filter, reduce | yes | yes | yes | no |
| String methods: split, join, contains, slices | yes | yes | yes | no |
| Errors you can catch | try | rescue | try | no |
| Multiple files, imports | yes | yes | yes | no |
| Files and command-line args | yes | yes | yes | no |
| Memory reclaimed | GC | GC | ARC | no, freed at exit |

Out of scope for now, on purpose: threads and async, a package manager, a REPL, a JIT. Each is a project the size of Plank itself.

## Score

13 of 23. The loop that builds Plank works down this table one release at a time.
