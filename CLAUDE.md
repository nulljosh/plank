# plank

Small compiled language, one Python file on llvmlite. Public repo `nulljosh/plank`, landing at plank.jaybulb.com, Homebrew tap `nulljosh/homebrew-plank` (formula `plank-lang`; core brew already has an unrelated `plank`).

- `plank.py` is the whole compiler. Keep it one file; a reader should get through it in a sitting
- New feature = example in `examples/` with a `.out`, a paragraph in `docs/SPEC.md`, a row in `docs/COMPARE.md`, a note in `docs/ARCHITECTURE.md`, usually a `tests/*.pk` with asserts, all in the same commit. Then `python3 tools/gen-demo.py` so the landing shows it
- `python3 test.py` before pushing: every example, app and test, 30 error messages, the REPL, `plank fmt --check`, and all of it again with the collector firing every 4KB. CI runs the same on macOS and Ubuntu
- Release with `tools/release.sh "title" "notes"`: it runs the suite, tags, publishes the GitHub release, bumps the tap formula and deploys the landing, and refuses on a red suite. Never hand-roll that chain
- The book (`book/*.md`) is the human-readable docs; a feature that changes how people write Plank gets a paragraph there too, then `python3 tools/gen-book.py`. Every program in it is compiled and diffed by `test.py`. SPEC.md and ARCHITECTURE.md are its appendices, so editing them also needs a regen. Style is No Starch: `> **Note**` boxes, a `> **Try it yourself**` at each chapter end, numbered figures from `book/art/*.svg`
- Every `.pk` in the repo is formatted; run `./plank fmt` after editing one
- No em dashes anywhere

## The loop

A `/loop` grows Plank toward 5.0. State and the restart prompt live in `docs/LOOP-HANDOFF.md`; rewrite it whenever the loop pauses.
