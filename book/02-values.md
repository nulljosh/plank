# 2. Values and names

## Numbers, text and truth

Plank has four simple kinds of value:

- `int`, a whole number: `42`, `-7`, `0`
- `float`, a number with a fractional part: `3.14`, `2.0`, `1.5e3`
- `bool`, `true` or `false`
- `str`, a piece of text: `"hello"`, `"世界"`

Plank never turns one kind into another behind your back. `1 + 2.0` is an error, because one side is an `int` and the other a `float`. When you want a conversion, ask for it:

```plank
fn main() {
  print(1 + int(2.9))
  print(float(1) + 2.5)
  print("age " + str(36))
  print(int("42") * 2)
}
```

```output
3
3.5
age 36
84
```

`int` on a float drops the fraction. `int` on text reads a number out of it, and stops the program with the line number if the text is not a number. Chapter 7 shows how to catch that instead.

## let and var

Give a value a name with `let`:

```plank
fn main() {
  let name = "plank"
  let year = 2026
  print(name, year)
}
```

```output
plank 2026
```

A `let` name can never point at anything else. If you want a name you can change, use `var`:

```plank
fn main() {
  var count = 0
  count = count + 1
  count += 10
  print(count)
}
```

```output
11
```

Plank works out the type from the value. You can write it yourself when you want to be clear, or when there is no value to look at yet:

```plank
fn main() {
  var total: float = 0.0
  total += 1.5
  print(total)
}
```

```output
1.5
```

Prefer `let`. When a reader sees `let`, they know the name means one thing for the rest of the block, and that is one less thing to keep in their head.

## Text

Strings join with `+`. Better, drop values straight into a string with `\( )`:

```plank
fn main() {
  let lang = "plank"
  let n = len(lang)
  print("\(lang) has \(n) letters, \(n * 2) if you say it twice")
}
```

```output
plank has 5 letters, 10 if you say it twice
```

Anything can go inside `\( )`, even another call. Strings come with tools:

```plank
fn main() {
  let s = "  Hello, Plank  "
  print(s.trim())
  print(s.trim().upper(), s.trim().lower())
  print("a,b,c".split(","))
  print(["x", "y"].join(" and "))
  print("plank".starts_with("pl"), "lan" in "plank")
  print("plank"[0], "plank"[1..3], "plank"[-1])
}
```

```output
Hello, Plank
HELLO, PLANK hello, plank
["a", "b", "c"]
x and y
true true
p la k
```

Indexes count characters, not bytes, so `"héllo"[1]` is `"é"`. A slice like `[1..3]` takes characters 1 and 2: the start is included, the end is not. Negative numbers count from the end.

Strings never change in place. Every tool hands back a new string and leaves the old one alone.

## Doing arithmetic

`+ - * / %` work on ints and floats. Integer division drops the remainder, and `%` gives it to you:

```plank
fn main() {
  print(17 / 5, 17 % 5)
  print(17.0 / 5.0)
  print(sqrt(2.0), pow(2.0, 10.0), abs(-4))
  print(fixed(3.14159, 2))
}
```

```output
3 2
3.4
1.4142135623731 1024 4
3.14
```

Floats print with up to 15 significant digits, so `0.1 + 0.2` shows as `0.3`. `fixed` gives you exactly as many digits as you ask for.
