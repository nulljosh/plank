# 1. Your first program

Make a file called `hello.pk`:

```plank
fn main() {
  print("hello, plank")
}
```

Run it:

```
plank run hello.pk
```

```output
hello, plank
```

That one command did a lot. Plank read the file, checked it, turned it into LLVM's intermediate language, asked LLVM to optimize that into machine code, and asked your C compiler to link it into a program. Then it ran the program. Figure 1-1 shows the trip your one line of code takes.

![The four steps from a source file to a binary. Every Plank program takes this road.](art/pipeline.svg)

If you want to keep the program, build it instead:

```
plank build hello.pk
./hello
```

Now there is a file called `hello` next to your source. It is a native binary. It does not need Plank, Python or LLVM to run. You can copy it to another machine of the same kind and it will work.

## What the pieces mean

`fn main()` is where every program starts. `fn` starts a function, `main` is its name, and the empty parentheses say it takes nothing. The braces hold its body.

`print` writes its arguments to the terminal with spaces between them and a newline at the end:

```plank
fn main() {
  print("one", 2, 3.5, true)
  print()
  print("after a blank line")
}
```

```output
one 2 3.5 true

after a blank line
```

Statements end at the end of a line. There are no semicolons. Comments start with `#` and run to the end of the line.

## Trying things quickly

For small experiments, start the REPL:

```
plank repl
```

Type a line and Plank shows you what it does. A bare expression prints its value. Behind the scenes the REPL rebuilds a real binary after every line, so what you see there is exactly what a compiled program would print.

## When something is wrong

Make a mistake on purpose:

```
fn main() {
  print(1 + "two")
}
```

Plank refuses to compile it and tells you where and why:

```
hello.pk:2: int + str: types must match, use str()
```

> **Note** Plank checks types before anything runs. A mistake like this one never becomes a crash at 3 a.m.; it is a message at your desk.

Every error in Plank names the file and the line. Most of them also tell you what to do next. Read them; they were written to be read.

> **Try it yourself**
>
> 1. Make `print` say your name, then build the program and run the binary without `plank`.
> 2. Print three values of different kinds on one line. What separates them?
> 3. Open the REPL and type `2 + 3 * 4`. Is the answer what you expected?
> 4. Break the program on purpose three different ways and read each error. Which one helps the most?
