# 8. Functions as values

A function is a value like a number or a string. You can store one in a name, pass it to another function, or return it:

```plank
fn twice(f: fn(int) -> int, x: int) -> int {
  return f(f(x))
}

fn double(n: int) -> int {
  return n * 2
}

fn main() {
  print(twice(double, 5))
  print(twice(fn(x) => x + 3, 1))
}
```

```output
20
7
```

`fn(x) => x + 3` is a closure, a function with no name written right where it is used. `=>` with one expression is the short form. Plank works out the type of `x` from where the closure goes: `twice` says it takes `fn(int) -> int`, so `x` is an `int`.

For more than one line, use a block:

```plank
fn main() {
  let shout = fn(s: str) -> str {
    let loud = s.upper()
    return loud + "!"
  }
  print(shout("plank"))
}
```

```output
PLANK!
```

## Closures remember

A closure keeps the variables it uses. They are shared, not copied, so the closure sees later changes, and a closure handed out of a function keeps its variables alive:

```plank
fn make_counter() -> fn() -> int {
  var n = 0
  return fn() -> int {
    n += 1
    return n
  }
}

fn main() {
  let next = make_counter()
  next()
  next()
  print(next())
}
```

```output
3
```

How can `n` still exist after `make_counter` has returned? Plank noticed that a closure uses it and put it on the heap instead of the stack. Figure 8-1 shows what `next` really holds.

![A closure is two words: where its code is, and an environment that points at the variables it uses.](art/closure.svg)

## Sorting by anything

Closures are how you tell library functions what you want. Sort people by age:

```plank
struct Person {
  name: str
  age: int
}

fn main() {
  let people = [Person("ada", 36), Person("linus", 28), Person("grace", 85)]
  people.sort(by: fn(a, b) => a.age < b.age)
  print(people.map(fn(p) => p.name))
}
```

```output
["linus", "ada", "grace"]
```

## Summary

Functions are values you can store, pass and return. A closure is a function written in place that keeps the variables it uses, even after the function that made it has returned. Closures are how you tell `sort`, `map` and friends what you want. Next you will talk to files, the shell and the web.

> **Try it yourself**
>
> 1. Write `make_adder(n)` that returns a function adding `n` to its argument.
> 2. Sort a list of words by their length, longest first.
> 3. Make a counter closure that returns 1, 2, 3 on each call.
