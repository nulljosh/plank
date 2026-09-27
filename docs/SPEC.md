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
| `float` | 64-bit double | `3.14`, `2.0` |
| `bool` | 1 bit | `true`, `false` |
| `str` | C string | `"hello\n"` |

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

Conditions must be `bool`. The `for` variable is an `int` and is a `let` inside the body.

## Built-ins

`print(x)` prints any of the four types followed by a newline. `int(x)` and `float(x)` convert. That is the whole standard library for now.

## Errors

Every error names the file and line:

```
fib.pk:3: 'x' is a let, use var to reassign it
```

Exit code 1 is a Plank error, 2 is a missing file, anything else is what your program returned.
