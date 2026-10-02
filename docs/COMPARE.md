# Plank next to Python, Ruby and Swift

The goal: write the programs you would write in Python, Ruby or Swift, in Plank, and get a native binary. This page is the scorecard. Each row is something people reach for every day. A row turns to yes when it works, has an example in `examples/`, and is in `docs/SPEC.md`. The version in brackets is when it landed.

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
| Run a shell command | yes | yes | yes | yes (1.2) |
| JSON in and out | yes | yes | yes | yes (1.2) |
| HTTP requests | yes | yes | yes | yes (1.2) |
| Generic functions | duck typing | duck typing | yes | yes (1.3) |
| `if` as an expression | yes | yes | yes | yes (1.3) |
| Generic types, `Stack<T>` | duck typing | duck typing | yes | yes (1.4) |
| `match` as an expression | yes | yes | yes | yes (1.5) |
| Index or key in a `for` | enumerate, items | each_with_index | enumerated | yes (1.5) |
| `while let` | walrus | no | yes | yes (1.5) |
| A REPL | yes | irb | yes | yes (1.6) |
| One-line install | yes | yes | Xcode | `brew install` (1.6) |
| A formatter | black | rubocop | swift-format | `plank fmt` (1.7) |
| Tuples and multiple return values | yes | yes | yes | yes (1.8) |
| Regular expressions | re | built in | Regex | POSIX, on str (1.8) |
| sleep | yes | yes | yes | yes (1.8) |
| Call C directly | ctypes | fiddle | yes | `extern fn` (1.9) |
| Optional chaining `?.` | no | `&.` | yes | yes (1.9) |
| items, enumerate, zip | yes | yes | yes | yes (1.9) |
| Files and folders: list, exists, mkdir | os | Dir, File | FileManager | yes (2.1) |
| The clock as text | datetime | Time | Date | `clock(fmt)` (2.1) |
| URL encoding | urllib | CGI | yes | yes (2.1) |
| `==` that looks inside collections | yes | yes | Equatable | yes (2.2) |
| Modules with a name of their own | import x | require | import | `import as` (2.3) |
| Sets | set | Set | Set | `Set<T>` (2.4) |
| Dates: parse, format, add days | datetime | Time | Date | `parse_time`, `clock(fmt, at)` (2.5) |
| A binary to copy anywhere | PyInstaller | no | yes | `build --static` on Linux (2.6) |
| Errors in the type, `Result` and `?` | no | no | `throws`, `try?` | `Result<T>`, `?` (3.1) |
| Generic enums | no | no | yes | yes (3.1) |
| Tests in the language | unittest | minitest | XCTest | `assert` + `plank test` (1.3) |

Out of scope, on purpose: threads and async, a package manager, a JIT. Each is a project the size of Plank itself.

## Score

52 of 52. Every row is a yes. The next rows are on `roadmap.md`; when one lands it joins the table.
