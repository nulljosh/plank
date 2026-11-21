# 4. Functions

A function takes values in and may hand one back. Every parameter has a type, and so does the result:

```plank
fn area(w: float, h: float) -> float {
  return w * h
}

fn main() {
  print(area(3.0, 4.0))
}
```

```output
12
```

A function with a result type must return on every path. If one branch could fall off the end, Plank refuses to compile it and tells you which function. That rules out a whole family of bugs where a function quietly returns nothing.

Functions can be declared in any order. `main` can call a function written below it.

## Defaults and labels

Parameters can have default values, and any call can name its arguments:

```plank
fn greet(name: str, greeting: str = "hello", times: int = 1) {
  for i in 0..times {
    print(greeting + ", " + name)
  }
}

fn main() {
  greet("ada")
  greet("grace", times: 2, greeting: "hi")
}
```

```output
hello, ada
hi, grace
hi, grace
```

Labels make a call read like a sentence and let you skip the defaults you are happy with. Once one argument has a label, the ones after it need labels too.

## More than one result

Return a tuple to hand back several values, and take it apart where you call:

```plank
fn divmod(a: int, b: int) -> (int, int) {
  return (a / b, a % b)
}

fn main() {
  let (q, r) = divmod(17, 5)
  print(q, r)
}
```

```output
3 2
```

## Recursion

A function can call itself. This is the Fibonacci function, the one the landing page times:

```plank
fn fib(n: int) -> int {
  if n < 2 {
    return n
  }
  return fib(n - 1) + fib(n - 2)
}

fn main() {
  print(fib(20))
}
```

```output
6765
```

Because Plank compiles to machine code, `fib(35)` takes a few hundredths of a second. The same function in a tree-walking interpreter takes seconds.
