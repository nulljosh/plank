# Plank language reference

Everything the compiler accepts, in one page.

## Program

A program is a list of functions, structs and enums, and any number of `import "other.pk"` lines, which pull in everything another file defines. Paths are relative to the importing file, and a file is only read once however many times it is imported. Errors and runtime messages name the file they come from.

A program's top level is a list of functions. It needs a `fn main()` with no parameters and no return type. Statements end at the newline. Comments start with `#`.

```
fn add(a: int, b: int) -> int {
  return a + b
}

fn main() {
  print(add(2, 3))
}
```

Parameters can have defaults, and any call can name its arguments. Once one argument has a label, the ones after it need labels too.

```
fn greet(name: str, greeting: str = "hello", times: int = 1) { ... }

greet("plank")
greet("swift", times: 2, greeting: "hi")
```

A default is worked out fresh at every call, so `xs: [int] = []` gives each call its own list. It cannot use the caller's variables.

Functions and structs can be declared in any order. A function with a return type must return on every path; the compiler refuses one that can fall off the end.

## Types

| Type | Machine | Literals |
|---|---|---|
| `int` | signed 64-bit | `42`, `0` |
| `float` | 64-bit double | `3.14`, `2.0`, `1.5e3` |
| `bool` | 1 bit | `true`, `false` |
| `[T]` | list of any type, shared | `[1, 2, 3]`, `["a"]`, `[[1], [2, 3]]` |
| `[K: V]` | dict, int or str keys, shared | `["a": 1]`, `[1: "one"]`, `[:]` |
| `T?` | a `T` or `nil` | `nil`, or any `T` |
| `fn(A, B) -> R` | a function or closure | `fn(x: int) => x * 2`, `double` |
| `str` | C string, UTF-8 | `"hello\n"`, `"世界"`, `"n is \(n)"` |

String escapes are `\n`, `\t`, `\"`, `\\` and `\0`. Anything else after a backslash is an error, except `\(`, which starts an interpolation: `"\(name) has \(len(name)) letters"` drops the value of any expression into the string. Ints, floats and bools turn into text the same way `print` shows them. The expression inside can hold its own strings. A float literal needs digits on both sides of the dot.

There are no implicit conversions. `1 + 2.0` is an error. Use `int(x)`, `float(x)` and `str(x)`: float to int truncates, bool to int gives 0 or 1. `int("42")` and `float(" 2.5 ")` read numbers out of text and stop the program with the line number if the text is not one.

## Variables

`let` binds once. `var` can be reassigned. Both infer the type from the value; you can state it with a colon.

```
let name = "plank"
var count: int = 0
count = count + 1
```

`x += 1` is `x = x + 1`. The same goes for `-=`, `*=`, `/=` and `%=`, and `+=` joins strings.

Blocks open a scope. A name cannot be declared twice in the same scope, but an inner block can shadow an outer one.

## String tools

```
"a, b ,c".split(",")          # ["a", " b ", "c"]
"the  quick fox".split()      # ["the", "quick", "fox"], on runs of whitespace
["a", "b"].join(" & ")        # "a & b"
"  hi  ".trim()               # "hi"
"Plank".upper(), "Plank".lower()
"plank lang".replace("lang", "compiler")
"plank".find("an")            # 2, an int?, nil when it is not there
"plank".starts_with("pl"), "plank".ends_with("nk")
"héllo"[1]                    # "é", a one-character string
"héllo"[1..3], "héllo"[..2], "héllo"[-2..]
for c in "héllo" { ... }      # one character at a time
"héllo".chars()               # ["h", "é", "l", "l", "o"]
fixed(3.14159, 2)             # "3.14"
```

Indexes and lengths count characters, not bytes. Strings never change in place; every tool returns a new one. `upper` and `lower` change ASCII letters and leave the rest alone.

## Lists

A list holds one type. Write the type as `[int]`, `[str]`, `[[float]]`. An empty list needs its type spelled out once: `let xs: [int] = []`.

```
let xs = [3, 1, 4]
xs.append(1)        # [3, 1, 4, 1]
print(xs[0], xs[-1]) # 3 1, negative counts from the end
xs[1] += 10         # [3, 11, 4, 1]
let last = xs.pop() # 1
print(len(xs), xs)  # 3 [3, 11, 4]
for x in xs {
  print(x)
}
```

Lists are shared, like Python's: pass one to a function and the function sees and changes the same list. `let` stops the name from pointing at a new list, not the list from changing. An index past either end stops the program with the line number. `print` and `str` show lists the way you would type them, strings in quotes. Lines can break freely inside `[ ]`. `xs[1..3]` is a new list of items 1 and 2; either end can be left off, negative ends count from the back, and ends past the list are clamped, so a slice never stops the program.

## Dicts

A dict maps int or str keys to values of one type, and remembers the order keys went in, like Python's.

```
let ages = ["ada": 36, "linus": 28]
ages["grace"] = 85              # add or replace
ages["linus"] += 1
print(ages["ada"])              # 36
print("bob" in ages)            # false
print(ages.get("bob", 0))       # 0, the default when the key is missing
ages.remove("ada")
for name in ages {              # keys, in the order they went in
  print(name, ages[name])
}
print(ages.keys(), ages.values(), len(ages))
```

Reading a key that is not there stops the program and names the key; use `in` or `get` when it might be missing. An empty dict is `[:]` and needs its type once: `let d: [str: int] = [:]`. Dicts are shared like lists.

`in` also works on lists, `3 in [1, 2, 3]`, and strings, `"lan" in "plank"`.

## Structs

A struct groups named fields and the functions that work on them. Names start with a capital letter.

```
struct Account {
  owner: str
  balance: int = 0

  fn deposit(amount: int) {
    self.balance += amount
  }
}

let a = Account(owner: "josh")  # or Account("josh", 0)
a.deposit(50)
print(a.balance, a)  # 50 Account(owner: "josh", balance: 50)
```

Build one by calling its name with the fields in order or by label; fields with a default can be left out. Methods get `self` without asking for it and reach fields through `self.x`. Like lists, structs are shared: a function that changes `p.x` changes it for everyone holding `p`, and `let` only fixes which struct the name points at. `print` and `str` show a struct the way you would build it.

## Enums and match

An enum is one of a fixed set of cases, and a case can carry values. Methods work the same as on structs.

```
enum Shape {
  circle(r: float)
  rect(w: float, h: float)
  dot

  fn area() -> float {
    match self {
      .circle(r) { return 3.14159 * r * r }
      .rect(w, h) { return w * h }
      .dot { return 0.0 }
    }
  }
}

let s = Shape.rect(w: 2.0, h: 3.0)   # a case with values is built like a struct
print(s, s.area())                    # rect(w: 2, h: 3) 6
let d = Shape.dot                     # a case without values needs no ()
```

`match` picks the first arm that fits. On an enum, each arm names cases with a leading dot and can bind the carried values to new names. The compiler refuses a match that forgets a case, and one with an `else` that can never run. On ints, floats, bools and strings, arms list constants, several to an arm with commas, and `else` catches the rest. `==` compares enums whose cases carry nothing; for the rest, use `match`. Enums are shared and print as their case.

## Optionals

`int?` is an int or `nil`. Any type can be optional, and a plain value goes wherever its optional is expected. Nothing else can be `nil`, so a plain `int` is always there.

```
fn find(xs: [str], want: str) -> int? {
  for i in 0..len(xs) {
    if xs[i] == want { return i }
  }
  return nil
}

if let i = find(names, "ada") {   # i is a plain int in here
  print(i)
} else {
  print("not found")
}
let i = find(names, "bob") ?? -1  # the value, or the fallback
let j = find(names, "ada")!       # the value, or stop the program with the line number
print(find(names, "x") == nil)    # true
```

You cannot do math on an `int?` until you take the value out, and the error says how. The fallback after `??` only runs when it is needed. `d.get(k)` with one argument gives a `V?`. Optionals print as their value or `nil`. A struct field like `next: Node? = nil` is how you build a linked list.

## Functions as values

A function is a value like any other. Write one inline with `fn`, with a block body, or with `=>` and a single expression whose type Plank works out.

```
let add = fn(a: int, b: int) => a + b
let shout = fn(s: str) -> str {
  return s + "!"
}
fn twice(f: fn(int) -> int, x: int) -> int {
  return f(f(x))
}
print(twice(fn(x) => x + 3, 1))   # 7; x is an int because twice says so
print(twice(double, 5))            # a named function works too
```

Parameter types can be left off whenever the place the function goes already says them: arguments, `let` with a type, `return`, and the list methods below. A closure keeps the variables it uses, shared, not copied: change the variable later and the closure sees it, and a closure returned from a function keeps its variables alive.

```
fn make_counter() -> fn() -> int {
  var n = 0
  return fn() -> int {
    n += 1
    return n
  }
}
```

Lists take functions: `xs.map(fn(x) => x * 2)`, `xs.filter(fn(x) => x > 0)`, `xs.reduce(0, fn(acc, x) => acc + x)`. `xs.sort()` sorts ints, floats and strings in place and `xs.sorted()` returns a sorted copy; both take `by: fn(a, b) => a.age < b.age` for anything else, where the function says whether `a` goes first. Sorting is stable.

## Operators

From loosest to tightest: `or`, `and`, `not`, comparisons (`== != < > <= >=` and `in`), `??`, `+ -`, `* / %`, unary `-`. `and` and `or` short-circuit. Integer `/` truncates toward zero and `%` follows the sign of the left operand. Floats support all of these too. Strings join with `+` and compare with all six comparisons, alphabetically by byte. Bools compare with `==` and `!=` only.

## Control flow

```
if x < 0 {
  print("negative")
} else if x == 0 {
  print("zero")
} else {
  print("positive")
}

while running {
  if done { break }
  if skip { continue }
}

for i in 0..10 {   # 0 through 9, the bounds are evaluated once
  print(i)
}
```

`for x in xs` walks a list from the front. Conditions must be `bool`. The `for` variable is an `int` and is a `let` inside the body. `else` can sit on the same line as the closing brace or on the next one. A `while true` with no `break` counts as never finishing, so a function can end with one and still satisfy the return check.

## Built-ins

| Call | Does |
|---|---|
| `print(a, b, ...)` | Prints its arguments separated by spaces, then a newline. `print()` is a blank line. |
| `str(x)`, `int(x)`, `float(x)` | Convert, see Types. |
| `len(x)` | Items in a list, or characters in a string, so `len("世界")` is 2. |
| `input(prompt)` | Prints the optional prompt, reads one line, drops the newline. Empty at end of input. |
| `min(a, b)`, `max(a, b)`, `abs(x)` | Two ints or two floats in, the same type out. |
| `sqrt`, `floor`, `ceil`, `round`, `pow(x, y)` | Float math from libm. |
| `fixed(x, digits)` | A float as text with that many digits after the point. |
| `args()` | The command-line arguments after the program: `plank run tool.pk a b` gives `["a", "b"]`. |
| `read_file(path)` | The whole file as a `str?`, `nil` if it cannot be read. |
| `write_file(path, text)` | Writes the file, `true` if it worked. |
| `read_stdin()` | Everything on standard input, as one string. |
| `env(name)` | An environment variable as a `str?`. |
| `random(lo, hi)`, `random()` | An int from `lo` to `hi` inclusive, or a float from 0 up to 1. |
| `time()` | Seconds since 1970 as a float, good for timing. |
| `exit(code)` | Stops the program with that exit code. |

Floats print with 15 significant digits, so `0.1 + 0.2` shows `0.3` and `1.0 / 3.0` shows `0.333333333333333`. `print`, `str`, `int`, `float`, `len` and `input` are reserved. The math names are not: define your own `sqrt` and yours wins.

## Catching errors

Anything that would stop the program at run time can be caught: an index out of range, a missing dict key, `int("x")`, `nil!`, `pop()` on an empty list, and your own `throw`.

```
fn parse_age(text: str) -> int {
  let n = int(text)
  if n < 0 { throw "\(n) is not an age" }
  return n
}

try {
  print(parse_age(input("age? ")))
} catch err {
  print("no good:", err)   # err is the message, a str
}
```

`throw` takes a str. A `try` can hold `return`, `break` and `continue`, and tries nest: a throw inside a `catch` goes to the next `try` out. An error nobody catches stops the program with the file, line and message, exit code 1.

## Errors

Every error names the file and line:

```
fib.pk:3: 'x' is a let, use var to reassign it
```

Exit code 1 is a Plank error, at compile time or a runtime one like a bad `int("x")`, 2 is a missing file, anything else is what your program returned.
