# Roadmap

## Next
- [ ] AI: a live Anthropic tool turn (run examples/toolfn.pk) once the API key has credit

## Ingested 2026-10-30

## Ingested 2026-11-14

## 5.0: its own compiler
Proven 2026-11-20: Apple `cc` compiles Plank's `plank emit` IR plus the C runtime with output identical to plank.py's build (fib, closures, structs, enums, optionals, collections, results), and recursive enums work, so an AST fits in Plank. A compiler written in Plank only has to print IR text and call `cc`: no Python, uv or llvmlite.
- [x] 4.8 `compiler/plank.pk` lexer: tokens match plank.py's `lex` on every example (test.py diffs them)
- [x] 4.9 parser: an AST that prints the same as plank.py's for every example
- [ ] 4.10 codegen subset: ints, strings, functions, if, while, for; hello, fib, fizzbuzz, primes match their `.out`
- [ ] 4.11 structs, enums, match, optionals, lists, dicts, closures, the collector
- [ ] 4.12 everything else, until every example and app matches under both compilers
- [ ] 5.0 fixed point: plank.py builds plank.pk (stage 1), stage 1 builds it (stage 2), stage 2 builds it (stage 3), stage 2 IR == stage 3 IR. Homebrew ships the native `plank`; the only dependency is a C compiler
- After 5.0: threads, channels, any-key dicts, fmt comments inside expressions, freestanding target

## Ingested 2026-11-16
- [ ] (Note "Plank") Make the color more of a clrs.cc brown (https://clrs.cc), not red or burgundy.
- [ ] (Plank) Next steps? /loop to the next major semver.
- [x] (Plank) Needs a starter's guide, book, documentation. Use No Starch programming books as inspiration: artwork, writing style and diagrams.

## Ingested 2026-11-23

- [ ] **Plank**: Add graphs gifs etc to book
  - Add benchmarks if we don’t have them
  - Or work on benchmarks
