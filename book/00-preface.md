# Preface

This book teaches Plank from the first line to the last stage of the compiler. You do not need to have written a compiler before. You need to have written a little code in something, Python or JavaScript or Swift, and to be curious about what happens after you press run.

Plank is a small language that compiles to real machine code. Its whole compiler is one Python file, `plank.py`. That fact shapes the book. The first half teaches you to write Plank. The second half opens the compiler and shows you how it turns your programs into binaries, so that by the end there is nothing about the language you have to take on trust.

Every program in this book is real. The test suite pulls each one out, compiles it, runs it and checks that it prints exactly what the book says it prints. If a page and the compiler ever disagree, the build goes red.

## How to read it

Read the chapters in order the first time. Each one builds on the last and ends with something you can run. Type the programs in yourself rather than copying them; you learn a language through your fingers.

When you see a block like this one, it is a program:

```plank
fn main() {
  print("hello, reader")
}
```

and the block under it is what it prints:

```output
hello, reader
```

## Getting Plank

On a Mac with Homebrew:

```
brew install nulljosh/tap/plank-lang
```

Or clone the repository and run `./plank` from inside it. Either way you need a C compiler on the machine, because Plank hands its object files to your system linker. On a Mac that comes with the Xcode command line tools; on Linux, install `gcc` or `clang`. The first run fetches LLVM's Python bindings by itself.

Check it worked:

```
plank --version
```
