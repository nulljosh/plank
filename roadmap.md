# Roadmap

## Next
- [ ] AI: a live Anthropic tool turn (run examples/toolfn.pk) once the API key has credit

## Ingested 2026-10-30

## Ingested 2026-11-14

## 5.0: its own compiler
- [ ] Self-hosting: `plank.pk`, the compiler written in Plank, emitting LLVM IR as text and handing it to `llc` and `cc`. Bootstrap: `plank.py` compiles `plank.pk`, then `plank.pk` compiles itself and the two outputs must match. Start from `apps/calc.pk` (tokenizer and parser already in Plank)
