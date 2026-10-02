# Plank loop handoff (2026-10-01, late evening)

## What the loop is

A `/loop` that keeps Plank growing one release at a time toward 5.0, comparing it row by row with Python, Ruby and Swift in `docs/COMPARE.md`. Each pass picks the next thing a script for Joshua Tree or Samantha would reach for, builds it with an example, a `tests/*.pk`, a SPEC paragraph and a scorecard row, and ships it with `tools/release.sh`.

## Where things stand

2.2.0 is live and CI is green on macOS and Linux. The scorecard is 46 rows, every one a yes. The suite is 143 checks in about 20 seconds, and runs everything again with the collector firing every 4KB. The landing sits on the Jaybulb tokens, passes a phone-width QA with 44px tap targets, and `brew install nulljosh/plank/plank-lang` works. Hackers and Painters is summarized in `docs/HACKERS-AND-PAINTERS.md` and its rules shape every decision.

## Next, in order

1. Sets, `Set<T>`, on top of dicts
3. `plank doc`: the SPEC generated from the compiler, so it can never drift
4. Dates beyond `clock`: parse and add days
5. A `--static` build for Linux, so a Joshua Tree script is one file

## Restart prompt

```
/loop Keep building Plank toward 5.0, one release per pass, following docs/LOOP-HANDOFF.md: pick the next item, build it with an example in examples/, a tests/*.pk, a docs/SPEC.md paragraph, a docs/ARCHITECTURE.md note and a docs/COMPARE.md row, run python3 test.py, then tools/release.sh "title" "notes". Keep comparing with Python, Ruby and Swift. Stop and rewrite this file when the session passes 70% usage.
```
