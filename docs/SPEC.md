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
| `str` | C string, UTF-8 | `"hello\n"`, `"世界"` |

String escapes are `\n`, `\t`, `\"`, `\\` and `\0`. Anything else after a backslash is an error. A float literal needs digits on both sides of the dot.

There are no implicit conversions. `1 + 2.0` is an error. Use `int(x)` and `float(x)`: float to int truncates, bool to int gives 0 or 1.

## Variables

`let` binds once. `var` can be reassigned. Both infer the type from the value; you can state it with a colon.

```
let name = "plank"
var count: int = 0
count = count + 1
```

Blocks open a scope. A name cannot be declared twice in the same scope, but an inner block can shadow an outer one.

## Operators

From loosest to tightest: `or`, `and`, `not`, comparisons (`== != < > <= >=`), `+ -`, `* / %`, unary `-`. `and` and `or` short-circuit. Integer `/` truncates toward zero and `%` follows the sign of the left operand. Floats support all of these too. Strings support only being printed and passed around, no `+` and no `==` yet. Bools compare with `==` and `!=` only.

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

Conditions must be `bool`. The `for` variable is an `int` and is a `let` inside the body. `else` can sit on the same line as the closing brace or on the next one. A `while true` with no `break` counts as never finishing, so a function can end with one and still satisfy the return check.

## Built-ins

`print(x)` prints any of the four types followed by a newline. Floats print with 15 significant digits, so `0.1 + 0.2` shows `0.3` and `1.0 / 3.0` shows `0.333333333333333`. You cannot define a function named `print`, `int` or `float`. `int(x)` and `float(x)` convert. That is the whole standard library for now.

## Errors

Every error names the file and line:

```
fib.pk:3: 'x' is a let, use var to reassign it
```

Exit code 1 is a Plank error, 2 is a missing file, anything else is what your program returned.
