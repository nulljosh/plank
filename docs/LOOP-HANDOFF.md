# Plank loop handoff (2026-10-01, night)

## What the loop is

A `/loop` that keeps Plank growing one release at a time, comparing it row by row with Python, Ruby and Swift in `docs/COMPARE.md`. Each pass picks the next thing a script for Joshua Tree or Samantha would reach for, builds it with an example, a `tests/*.pk`, a SPEC paragraph and a scorecard row, and ships it with `tools/release.sh`.

## Where things stand

3.0.0 is the milestone: modules with `import as`, `Set<T>`, dates, static builds, and everything from 2.x. The scorecard is 50 rows, every one a yes. The suite is 158 checks and also proves the docs name every built-in, keyword, method and command, that every file is formatted, that a static build runs, and that the REPL behaves. CI is green on macOS and Linux. Every tag has a GitHub release and the Homebrew formula `plank-lang` follows each one.

## Next, in order

1. `plank doc`: the SPEC's built-in table generated from the compiler, so the two can never drift
2. Threads: `spawn` and `join` on top of pthreads, with the collector stopping the world
5. Joshua Tree: a freestanding target with no libc, for scripts that run on the kernel

## Restart prompt

```
/loop Keep building Plank toward 4.0, one release per pass, following docs/LOOP-HANDOFF.md: pick the next item, build it with an example in examples/, a tests/*.pk, a docs/SPEC.md paragraph, a docs/ARCHITECTURE.md note and a docs/COMPARE.md row, run python3 test.py, then tools/release.sh "title" "notes". Keep comparing with Python, Ruby and Swift. Stop at 4.0, or when the session passes 85% usage, and rewrite docs/LOOP-HANDOFF.md either way.
```
