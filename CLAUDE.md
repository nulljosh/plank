# plank

Small compiled language, one Python file on llvmlite. Public repo `nulljosh/plank`, landing at plank.heyitsmejosh.com, Homebrew tap `nulljosh/homebrew-plank` (formula `plank-lang`; core brew already has an unrelated `plank`).

- `plank.py` is the whole compiler. Keep it one file; a reader should get through it in a sitting
- New feature = example in `examples/` with a `.out`, a paragraph in `docs/SPEC.md`, a row in `docs/COMPARE.md`, a note in `docs/ARCHITECTURE.md`, usually a `tests/*.pk` with asserts, all in the same commit. Then `python3 tools/gen-demo.py` so the landing shows it
- `python3 test.py` before pushing: every example, app and test, 30 error messages, the REPL, `plank fmt --check`, and all of it again with the collector firing every 4KB. CI runs the same on macOS and Ubuntu
- Release with `tools/release.sh "title" "notes"`: it runs the suite, tags, publishes the GitHub release, bumps the tap formula and deploys the landing, and refuses on a red suite. Never hand-roll that chain
- Every `.pk` in the repo is formatted; run `./plank fmt` after editing one
- No em dashes anywhere
