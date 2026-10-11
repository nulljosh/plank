# Plank loop handoff (2026-10-11, small hours)

## What the loop is

A `/loop` that keeps Plank growing one release at a time, comparing it row by row with Python, Ruby and Swift in `docs/COMPARE.md`. Each pass picks the next thing a script for Joshua Tree or Samantha would reach for, builds it with an example, a `tests/*.pk`, a SPEC paragraph and a scorecard row, and ships it with `tools/release.sh`.

## Where things stand

4.6.1 put the AI story on the README, landing and whitepaper. 4.6.0 added `ask_json` (JSON back, fence stripped, one retry). 4.5.0 added `keep` on `ai.agent` (memory capped at a turn boundary). 4.4.0 added `ai.turing()`, the model for Turing's own server (port 8127, OpenAI-compatible). 4.3.0 made agents work with local OpenAI-compatible models (oMLX, Ollama, Turing). 4.2.0 added `tool fn` (schema from the signature, description from the comment above). 4.1.1 made integer `/` and `%` by zero stop with a line number (catchable). 4.1.0 added `lib/ai.pk` (model, prompt, ask, tool, agent with file memory; mock model for tests). 4.0.0 was the milestone: `Result<T>` and `?` on generic enums, packages fetched from GitHub, `plank doc`, on top of 3.0's modules, sets, dates and static builds. The scorecard is 60 rows, every one a yes. The suite is 170 checks and proves the docs name every built-in, keyword, method and command, that `plank doc` matches the built-ins exactly, that every file is formatted, that a static build runs, and that the REPL behaves. CI is green on macOS and Linux. Every tag has a GitHub release and the Homebrew formula `plank-lang` follows each one.

## Next, in order

0. AI: a live Anthropic tool turn once the key has credit (the loop is stopped on this; see below).
1. Threads: `spawn` and `join` on pthreads, with the collector stopping the world; the biggest piece left, do it first with a fresh session
2. Joshua Tree: a freestanding target with no libc, for scripts that run on the kernel
3. `plank fmt` for comments inside expressions, the one place it still moves them
4. A `Map<K, V>` with any key type, on top of a hash function per type
5. `async`-free concurrency the other way: a `channel<T>` once threads exist

## AI layer, where it stopped (2026-10-11)

Shipped 4.1 to 4.6.1: `lib/ai.pk` (model, local, turing, mock, prompt, ask, ask_json, tool, agent with file memory and `keep`), `tool fn` in the compiler, OpenAI-format tools for local models, divide-by-zero fix. Stopped on purpose: the rest needs something outside this repo. Open items: (1) the Anthropic tool path has never run live, no API key was available, so run `examples/toolfn.pk` with a real `ANTHROPIC_API_KEY` and `ai.model("claude-haiku-5-5")` first; (2) closed by design: Turing's server on port 8127 is a fixed answer pipeline that runs its own tools and ignores the caller's system prompt and tool list, so `ai.turing()` is for `ask` and an agent should use another model; (1b) the API key in `~/.config/joshuatree/anthropic.key` returned "credit balance is too low" on 2026-10-11, which proves the request and error path but not a full tool turn, so top up and rerun; (3) `ask` as a built-in was skipped, the library call is the same length.

## Restart prompt

```
/loop Keep building Plank toward 5.0, one release per pass, following docs/LOOP-HANDOFF.md: pick the next item, build it with an example in examples/, a tests/*.pk, a docs/SPEC.md paragraph, a docs/ARCHITECTURE.md note and a docs/COMPARE.md row, run python3 test.py, then tools/release.sh "title" "notes". Keep comparing with Python, Ruby and Swift. Stop at 5.0, or when the session passes 85% usage, and rewrite docs/LOOP-HANDOFF.md either way.
```
