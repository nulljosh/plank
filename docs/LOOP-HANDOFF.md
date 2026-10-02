# Plank loop handoff (2026-10-02, small hours)

## What the loop is

A `/loop` that keeps Plank growing one release at a time, comparing it row by row with Python, Ruby and Swift in `docs/COMPARE.md`. Each pass picks the next thing a script for Joshua Tree or Samantha would reach for, builds it with an example, a `tests/*.pk`, a SPEC paragraph and a scorecard row, and ships it with `tools/release.sh`.

## Where things stand

4.0.0 is the milestone: `Result<T>` and `?` on generic enums, packages fetched from GitHub, `plank doc`, on top of 3.0's modules, sets, dates and static builds. The scorecard is 54 rows, every one a yes. The suite is 170 checks and proves the docs name every built-in, keyword, method and command, that `plank doc` matches the built-ins exactly, that every file is formatted, that a static build runs, and that the REPL behaves. CI is green on macOS and Linux. Every tag has a GitHub release and the Homebrew formula `plank-lang` follows each one.

## Next, in order

1. Threads: `spawn` and `join` on pthreads, with the collector stopping the world; the biggest piece left, do it first with a fresh session
2. Joshua Tree: a freestanding target with no libc, for scripts that run on the kernel
3. `plank fmt` for comments inside expressions, the one place it still moves them
4. A `Map<K, V>` with any key type, on top of a hash function per type
5. `async`-free concurrency the other way: a `channel<T>` once threads exist

## Restart prompt

```
/loop Keep building Plank toward 5.0, one release per pass, following docs/LOOP-HANDOFF.md: pick the next item, build it with an example in examples/, a tests/*.pk, a docs/SPEC.md paragraph, a docs/ARCHITECTURE.md note and a docs/COMPARE.md row, run python3 test.py, then tools/release.sh "title" "notes". Keep comparing with Python, Ruby and Swift. Stop at 5.0, or when the session passes 85% usage, and rewrite docs/LOOP-HANDOFF.md either way.
```
