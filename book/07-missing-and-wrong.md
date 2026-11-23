# 7. When things are missing or wrong

## Optionals

Some answers might not exist: the position of a word that is not in a list, the value of a key that is not in a dict. Plank writes that as an optional. `int?` means an int or `nil`.

```plank
fn find(xs: [str], want: str) -> int? {
  for i, x in xs {
    if x == want {
      return i
    }
  }
  return nil
}

fn main() {
  let langs = ["swift", "ruby", "plank"]
  if let i = find(langs, "plank") {
    print("found at", i)
  }
  print(find(langs, "cobol") ?? -1)
}
```

```output
found at 2
-1
```

You cannot do arithmetic on an `int?` directly; you have to say what happens when it is `nil`. There are three ways:

- `if let i = maybe { ... }` runs the block only when there is a value, with `i` as a plain `int` inside
- `maybe ?? fallback` gives the value, or the fallback
- `maybe!` gives the value, or stops the program with the line number if there is none

Nothing that is not marked with `?` can ever be `nil`. When you see a plain `int`, it is always there. Figure 7-1 shows what an optional is in memory, and the three ways to open one.

![An int? is a pointer to a box holding the int, or no box at all.](art/optional.svg)

## Errors that stop the program

Some mistakes only show up when the program runs: reading past the end of a list, a missing dict key, `int("forty")`. Plank stops and tells you exactly where:

```
prog.pk:3: int() got text that is not a whole number
```

## try and catch

Any of those can be caught. `throw` raises your own:

```plank
fn parse_age(text: str) -> int {
  let n = int(text)
  if n < 0 {
    throw "\(n) is not an age"
  }
  return n
}

fn main() {
  for t in ["36", "-4", "forty"] {
    try {
      print(parse_age(t))
    } catch err {
      print("no good:", err)
    }
  }
}
```

```output
36
no good: -4 is not an age
no good: int() got text that is not a whole number
```

## Result

Sometimes failing is a normal answer, not a surprise. Then return a `Result<T>`: `ok(value)` or `err(message)`. A `?` after a call takes the value out, or hands the error straight back to whoever called you:

```plank
fn half(n: int) -> Result<int> {
  if n % 2 != 0 {
    return Result.err("\(n) is odd")
  }
  return Result.ok(n / 2)
}

fn quarter(n: int) -> Result<int> {
  return Result.ok(half(half(n)?)?)
}

fn main() {
  print(quarter(8).value())
  print(quarter(6).error() ?? "fine")
  print(quarter(6).or_else(0))
}
```

```output
2
3 is odd
0
```

> **Note** A rule of thumb: throw for bugs and broken input, return a `Result` when the caller is expected to handle the failure.

## Summary

An optional `T?` is either a value or `nil`, and you must say what happens in both cases. Run-time errors stop the program with a line number unless you catch them with `try`. `Result` makes failure an ordinary answer, and `?` passes it up. Next you will pass functions around as values.

> **Try it yourself**
>
> 1. Write `find(xs, x) -> int?` that returns the index or `nil`.
> 2. Use `??` to print `none` when it finds nothing.
> 3. Wrap a division by zero in `try` and print the message you catch.
