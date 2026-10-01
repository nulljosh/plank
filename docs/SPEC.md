# Plank language reference

Everything the compiler accepts, in one page.

## Program

A program is a list of functions. It needs a `fn main()` with no parameters and no return type. Statements end at the newline. Comments start with `#`.

```
fn add(a: int, b: int) -> int {
  return a + b
}

fn main() {
  print(add(2, 3))
}
```

Functions can be declared in any order. A function with a return type must return on every path; the compiler refuses one that can fall off the end.

## Types

| Type | Machine | Literals |
|---|---|---|
| `int` | signed 64-bit | `42`, `0` |
| `float` | 64-bit double | `3.14`, `2.0`, `1.5e3` |
| `bool` | 1 bit | `true`, `false` |
| `[T]` | list of any type, shared | `[1, 2, 3]`, `["a"]`, `[[1], [2, 3]]` |
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

Lists are shared, like Python's: pass one to a function and the function sees and changes the same list. `let` stops the name from pointing at a new list, not the list from changing. An index past either end stops the program with the line number. `print` and `str` show lists the way you would type them, strings in quotes. Lines can break freely inside `[ ]`.

## Operators

From loosest to tightest: `or`, `and`, `not`, comparisons (`== != < > <= >=`), `+ -`, `* / %`, unary `-`. `and` and `or` short-circuit. Integer `/` truncates toward zero and `%` follows the sign of the left operand. Floats support all of these too. Strings join with `+` and compare with all six comparisons, alphabetically by byte. Bools compare with `==` and `!=` only.

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

Floats print with 15 significant digits, so `0.1 + 0.2` shows `0.3` and `1.0 / 3.0` shows `0.333333333333333`. `print`, `str`, `int`, `float`, `len` and `input` are reserved. The math names are not: define your own `sqrt` and yours wins.

## Errors

Every error names the file and line:

```
fib.pk:3: 'x' is a let, use var to reassign it
```

Exit code 1 is a Plank error, at compile time or a runtime one like a bad `int("x")`, 2 is a missing file, anything else is what your program returned.
