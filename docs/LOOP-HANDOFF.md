# Plank loop handoff (2026-11-27, afternoon)

## What the loop is

A `/loop` that keeps Plank growing one release at a time toward 5.0, comparing it row by row with Python, Ruby and Swift in `docs/COMPARE.md`. Each pass picks the next thing a script for Joshua Tree or Samantha would reach for, builds it with an example, a `tests/*.pk`, a SPEC paragraph and a scorecard row, and ships it with `tools/release.sh`.

## Where things stand

The latest tag is 4.9.0. The 5.0 self-hosting work is underway: the lexer and parser are done, so `compiler/plank.pk` matches plank.py on all 64 files. The AI layer from 4.1 to 4.6.1 is shipped, including `ask_json`, `keep` on agents, and `ai.turing()`. The book got a pass on 2026-11-27: its chapter plates are now eight generated wood plates from `tools/gen-wood.py`, the book check passes on 41 programs, and the live book shows them. The loop is not running right now.

## Next, in order

4.10 codegen subset (ints, strings, functions, if, while, for; hello, fib, fizzbuzz and primes match their `.out`), then 4.11 structs, enums, match, optionals, lists, dicts, closures and the collector, then 4.12 everything else, then the 5.0 fixed point. Book items sit in `roadmap.md` under "Next": deepen the thin chapters, add a project chapter, and add an index. The live Anthropic tool turn in `examples/toolfn.pk` still waits on API credit.

## Restart prompt

```
/loop Keep building Plank toward 5.0, one release per pass, following docs/LOOP-HANDOFF.md: pick the next item, build it with an example in examples/, a tests/*.pk, a docs/SPEC.md paragraph, a docs/ARCHITECTURE.md note and a docs/COMPARE.md row, run python3 test.py, then tools/release.sh "title" "notes". Keep comparing with Python, Ruby and Swift. Stop at 5.0, or when the session passes 85% usage, and rewrite docs/LOOP-HANDOFF.md either way.
```
