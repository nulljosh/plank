# Architecture

One file does the work. Everything else is examples, tests and docs.

| File | What it does |
|---|---|
| `plank.py` | The compiler. `lex` turns source into tokens (`string_end` and `unescape` handle strings and `\(...)` interpolation), `Parser` builds the AST (dataclasses near the top), `Codegen` walks the AST once and emits LLVM IR through llvmlite, `optimize` runs the O2 pipeline, `build` links the object with `cc`. `RUNTIME` is a short C string, compiled next to every program, holding what libc does not: joining strings, counting characters, number to text and back, reading a line. `main` is the CLI. |
| `plank` | Symlink to `plank.py` so `./plank file.pk` works. The `uv run --script` shebang installs llvmlite on first use. |
| `examples/*.pk` | One program per feature: hello, fib, fizzbuzz, primes, sqrt, strings, text, loops. Each has a `.out` with its expected output. |
| `test.py` | Compiles every example, diffs the output, and checks one bad program fails with a line number. CI runs it on macOS and Ubuntu. |
| `docs/SPEC.md` | The language reference. |
| `docs/COMPARE.md` | The scorecard against Python, Ruby and Swift. The roadmap works down it. |
| `site/index.html`, `site/icon.svg`, `wrangler.toml` | The landing page at plank.heyitsmejosh.com, deployed as Cloudflare static assets. Drifting-plank canvas, hero, and a demo window that plays the real examples. |
| `tools/gen-demo.py`, `site/demo.js` | The generator reads every example, its `.out`, and `plank emit` output into `demo.js`. `test.py` fails if `demo.js` is stale, so the landing can never show output the compiler did not produce. |
| `roadmap.md`, `MONEY.md`, `CLAUDE.md` | What is next, what it earns (nothing, on purpose), and notes for the agent. |

## The pipeline

Source goes through four steps, each a plain function or class:

1. **Lex.** One regex, a loop, a list of tokens. Strings get a small hand scanner instead, because `\(...)` can hold strings of its own. `unescape` decodes escapes, keeps UTF-8 intact, and hands interpolations back as source for the parser. Newlines are tokens so statements can end without semicolons; inside parentheses they are dropped.
2. **Parse.** Recursive descent for statements, Pratt for expressions. Precedence lives in one dict.
3. **Codegen.** There is no separate type checker. Every expression returns a pair of LLVM value and Plank type, and the operator and call rules check the types as they go. Variables are `alloca` slots; LLVM's mem2reg turns them into registers at O2.
4. **Optimize and link.** llvmlite's new pass manager at O2, then the target machine emits a Mach-O or ELF object, and the system `cc` links it with `RUNTIME`, libc and libm. Nothing is freed yet: programs run and exit, and the OS takes the memory back.

User functions are prefixed `pk_` in the IR so they never collide with libc. A generated C `main` calls `pk_main` and returns 0.
