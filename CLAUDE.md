# plank

Small compiled language, one Python file on llvmlite. Public repo `nulljosh/plank`, landing at plank.heyitsmejosh.com.

- `plank.py` is the whole compiler. Keep it one file; a reader should get through it in a sitting
- Test before pushing: `python3 test.py`. CI runs the same on macOS and Ubuntu
- New feature = example in `examples/` with a `.out`, a line in `docs/SPEC.md`, a row check in `docs/ARCHITECTURE.md`, all in the same commit
- Landing lives in `site/`. `python3 tools/gen-demo.py` refreshes the demo data from the examples (test.py enforces it), then `npx wrangler deploy`. A push deploys nothing
- No em dashes anywhere
