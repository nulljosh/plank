# 12. Inside the compiler

You can now write Plank. This last chapter is about how Plank works, because the point of the language is that you can understand all of it. Open `plank.py` next to this chapter. It reads top to bottom in the same order as the steps below.

## Four steps

1. **Lex.** One regular expression and a small loop cut your text into tokens: names, numbers, strings, symbols. `let x = 1 + 2` becomes `let`, `x`, `=`, `1`, `+`, `2`. String interpolation is handled here too, by lexing what is inside `\( )` as code.
2. **Parse.** A recursive-descent parser turns tokens into a tree. Each piece of syntax has a small method on `Parser`: `stmt`, `if_`, `match`, `struct`, `fn` and so on. Expressions use a Pratt parser, which gets operator precedence right with one small table instead of a function per level.
3. **Generate.** One walk over the tree emits LLVM IR, a portable assembly language, and checks types as it goes. This is the biggest part of the file. When it sees `a + b`, it looks at the types of both sides, refuses if they differ, and emits an integer add, a float add or a call to the string joiner.
4. **Link.** LLVM optimizes the IR and turns it into machine code for your processor. Your system's C compiler links that with a small runtime and the C library into a binary.

## See it for yourself

`plank tokens` prints what the lexer made of a file, one token per line with its line number:

```
plank tokens examples/fib.pk
```

`plank emit` prints the IR for any program:

```
plank emit examples/fib.pk
```

You will see `fib` as a function that compares, branches and calls itself, much like the source. Run it on a program with a list or a closure to see how those are built out of plain memory and function pointers.

## Where values live

Ints, floats and bools live in registers and on the stack, like in C. Strings, lists, dicts, structs, enums and closures live on the heap and are passed around as pointers, which is why they are shared.

Nothing is ever freed by hand. A garbage collector runs now and then: it finds every object the program can still reach, starting from the stack and globals, marks them, and frees the rest. It never moves anything, which keeps it short. The test suite runs everything a second time with the collector firing every 4KB, to shake out any place that forgets to tell it about a pointer.

## Why LLVM

Writing a code generator for every processor is the part of a compiler that takes years. LLVM already did it, and does register allocation and optimization better than a small project could. Plank's job ends at producing correct IR, which is a job one file can do. That is the whole trick: pick the one piece you can borrow without hiding how anything works.

## Where to go next

- `docs/SPEC.md` is the reference: every rule of the language on one page.
- `docs/ARCHITECTURE.md` maps the file, section by section.
- `apps/calc.pk` is a calculator with its own tokenizer and parser, written in Plank. It is the same four steps in miniature.
- `compiler/plank.pk` is Plank's compiler written in Plank. It starts with the lexer from this chapter and grows a step per release until it can compile itself.

Change something. Add a built-in, make an error message friendlier, add a case to `match`. Run `python3 test.py`. That is how every feature in this book got there.
