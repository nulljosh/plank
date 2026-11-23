# 6. Your own types

## Structs

A struct gives a name to a group of fields, and can carry the functions that work on them. Struct names start with a capital letter:

```plank
struct Account {
  owner: str
  balance: int = 0

  fn deposit(amount: int) {
    self.balance += amount
  }

  fn can_pay(amount: int) -> bool {
    return amount <= self.balance
  }
}

fn main() {
  let a = Account(owner: "ada")
  a.deposit(50)
  print(a.balance, a.can_pay(80))
  print(a)
}
```

```output
50 false
Account(owner: "ada", balance: 50)
```

Build one by calling its name, with fields in order or by label. Fields with a default can be left out. Inside a method, `self` is the struct the method was called on; you never list it as a parameter.

`print` shows a struct the way you would build it. That one detail saves a lot of debugging.

## Enums

An enum is a value that is exactly one of a fixed set of cases. Cases can carry values of their own:

```plank
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

fn main() {
  let shapes = [Shape.circle(1.0), Shape.rect(w: 2.0, h: 3.0), Shape.dot]
  for s in shapes {
    print(s, s.area())
  }
}
```

```output
circle(r: 1) 3.14159
rect(w: 2, h: 3) 6
dot 0
```

## match

`match` picks the arm that fits the value and can pull out what a case carries. The part that matters most: Plank checks that you covered every case. Add a `triangle` to `Shape` and forget to handle it, and the program will not compile:

```
shapes.pk:7: match on Shape misses .triangle
```

That is the difference between finding a bug when you write it and finding it when a user does.

`match` also works on numbers and strings, with `else` for the rest, and it can produce a value:

```plank
fn main() {
  for code in [200, 404, 500] {
    let word = match code {
      200 { "ok" }
      404 { "not found" }
      else { "trouble" }
    }
    print(code, word)
  }
}
```

```output
200 ok
404 not found
500 trouble
```

## Types with parameters

A struct or function can work for any type, written as a parameter in angle brackets:

```plank
struct Stack<T> {
  items: [T] = []

  fn push(x: T) {
    self.items.append(x)
  }

  fn top() -> T? {
    return self.items.last()
  }
}

fn main() {
  let s = Stack<str>()
  s.push("a")
  s.push("b")
  print(s.top() ?? "empty", len(s.items))
}
```

```output
b 2
```

Plank compiles a separate version for each type you use, so a `Stack<str>` runs as fast as one written by hand for strings.

> **Try it yourself**
>
> 1. Add a `withdraw` method to `Account` that refuses to go below zero.
> 2. Add a `triangle` case to `Shape` and watch `match` refuse to compile until you handle it.
> 3. Give `Stack` a `pop` method, push three numbers and pop them all.
