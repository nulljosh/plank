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

That one command did a lot. Plank read the file, checked it, turned it into LLVM's intermediate language, asked LLVM to optimize that into machine code, and asked your C compiler to link it into a program. Then it ran the program. If you want to keep the program, build it instead:

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

Every error in Plank names the file and the line. Most of them also tell you what to do next. Read them; they were written to be read.
