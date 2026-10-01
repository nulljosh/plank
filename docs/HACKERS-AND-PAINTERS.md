# Hackers and Painters, and what it says about Plank

Paul Graham's 2004 essay collection, read as a design guide for this language. Fifteen essays; the ones that matter for a language are summarized here, each with the rule Plank takes from it.

## The book in one page

Graham's claim is that hacking is closer to painting than to science. Painters learn by doing and by copying good work, not from theory. They sketch, then fill in. They throw away and redo. The great ones had their own taste and trusted it. He thinks programmers should work the same way: start before you understand everything, keep the thing runnable the whole time, and judge your work by whether it is beautiful, because beautiful things tend to be the ones that work.

The essays that bear on building a language:

**Hackers and Painters.** Hackers are makers, like painters and architects, not scientists. The medium should let you sketch: a language that forces you to decide everything up front is like a painter who has to finish the sky before starting the trees. Good design is iterated design. Debugging is not a separate phase, it is how you find out what you meant.

**Taste for Makers.** Good design is simple, timeless, solves the right problem, is suggestive, is often slightly funny, is hard work, looks easy, uses symmetry, resembles nature, is redesign, can copy, is often strange, happens in chunks, is often daring. He makes the case that beauty is not decoration. The simple solution is usually the correct one, and ugliness is a sign something is wrong.

**The Hundred-Year Language.** Languages evolve toward fewer axioms and less cruft. The language of 2100 will be built from a small core with everything else as libraries, will not care about efficiency up front (hardware will), and will have the data structures that are most convenient, not the ones that are fastest. Strings are already lists. Pick the smallest set of ideas that generate the rest. Design for the people who will use it to write good programs, and let the implementation catch up.

**Beating the Averages.** The essay about Viaweb and Lisp. Languages are not equivalent in power, whatever the folklore says. The Blub paradox: a programmer who thinks in Blub cannot see what a more powerful language gives, because they look down at weaker languages and only see the strange parts of stronger ones. The practical point is to choose the most powerful language you can, and that power shows up as shorter programs.

**Succinctness is Power.** The best measure of a language is how short the programs are, counted in elements, not lines or characters. A language that lets you say what you mean in fewer elements is more powerful. Features that only add verbosity are wrong. Macros, higher-order functions and good defaults earn their place because programs shrink.

**Programming Bottom-Up** (from On Lisp, restated here). Write the language up toward the program while writing the program down toward the language. Good code builds its own small vocabulary and then says the program in it.

**Why Nerds Are Unpopular, What You Can't Say, Good Bad Attitude, How to Make Wealth, Mind the Gap, The Other Road Ahead, The Word "Hacker".** The rest of the book is about people and companies: why outsiders see more clearly, why you should question what everyone believes, how startups create wealth by making something people want. Worth reading, less about languages.

## The rules Plank takes from it

1. **Sketchable.** A Plank program should start as three lines and grow. No boilerplate, no header, no class to declare before `print` works. `fn main() { print("hi") }` is a program. Types are inferred so a sketch does not need them, and stated when the author wants them.

2. **Succinct in elements.** Every feature is judged by whether programs get shorter in elements. Interpolation, `map`, `?.`-style optionals, `match` with bound values, defaults and labels all earned a place that way. A feature that adds a keyword and saves nothing is not added.

3. **Few axioms.** Lists, dicts, structs, enums, closures, optionals. That is the whole vocabulary; everything else is a function over those. New built-ins are added only when a user program cannot express the thing at all (files, time, shell), never for convenience that a library in Plank could give.

4. **Convenient over fast.** Lists are shared, strings count characters, dicts keep order, and a collector frees memory. Each is the convenient choice. Where it costs speed, LLVM pays most of it back, and the rest is the price of a language you can sketch in.

5. **Bottom-up by default.** `apps/calc.pk` builds a tokenizer, then a parser, then an evaluator, and the program at the top is a few lines in that vocabulary. The examples are written that way on purpose, so the style spreads.

6. **Beauty is a signal.** When a Plank construct looks ugly, the design is wrong, not the user. The `plank fmt` on the roadmap is there to keep programs looking like the examples.

7. **The Blub test.** Whenever a feature from Python, Ruby or Swift seems strange or unnecessary, that is the moment to ask whether Plank is the Blub. `docs/COMPARE.md` exists so the question gets asked on purpose, row by row.

8. **Redesign is the work.** Plank went from 0.1 to 1.1 by rewriting the same file, not by adding files. The one-file rule is not a stunt; it keeps redesign cheap, because the whole thing fits in one head.

## What it argues against in Plank

Graham would push back on two things. He would want macros, or at least a way for programs to extend the syntax, and Plank has none; the answer for now is that closures and enums cover most of what people use macros for, and a macro system is a chapter the one-file rule cannot afford yet. He would also want a REPL, because sketching wants a conversation, not a compile step. `plank run` on a scratch file is the stand-in, and a REPL that compiles each line is on the long list.
