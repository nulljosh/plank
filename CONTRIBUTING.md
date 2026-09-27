# Contributing

Plank stays one file. A change that needs a second source file is probably a change Plank does not want.

Run `python3 test.py` before you push. Every new language feature ships with an example in `examples/` and its `.out`, a paragraph in `docs/SPEC.md`, and a check that `docs/ARCHITECTURE.md` still tells the truth. Same commit.

Error messages name the line and say what to do instead. "expected ','" is a bad message. "'x' is a let, use var to reassign it" is a good one.

No em dashes. No emojis. Short PR notes.
