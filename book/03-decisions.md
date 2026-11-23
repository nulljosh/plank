# 3. Making decisions and repeating

## if

```plank
fn main() {
  let temp = 18
  if temp > 25 {
    print("hot")
  } else if temp > 15 {
    print("mild")
  } else {
    print("cold")
  }
}
```

```output
mild
```

The condition must be a `bool`. Plank will not treat `0` or an empty string as false; say what you mean with `n == 0` or `s == ""`.

`if` can also produce a value. Each branch holds one expression, and both sides must have the same type:

```plank
fn main() {
  let n = 140
  let size = if n > 100 { "big" } else if n > 5 { "medium" } else { "small" }
  print(size)
}
```

```output
big
```

Combine conditions with `and`, `or` and `not`. They are words, not symbols, so they read out loud the way they work.

## for

`for` walks over a range of numbers, a list, the keys of a dict or the characters of a string:

```plank
fn main() {
  for i in 0..3 {
    print("lap", i)
  }
  for name in ["ada", "grace"] {
    print("hi", name)
  }
  for i, c in "abc" {
    print(i, c)
  }
}
```

```output
lap 0
lap 1
lap 2
hi ada
hi grace
0 a
1 b
2 c
```

`0..3` counts 0, 1 and 2. It stops before the end, the same as a slice, so `0..len(xs)` visits every index of `xs`. Figure 3-1 draws it.

![A range includes its start and stops just before its end.](art/range.svg)

## while

`while` repeats as long as its condition holds. `break` leaves the loop early, `continue` skips to the next time round:

```plank
fn main() {
  var n = 27
  var steps = 0
  while n != 1 {
    if n % 2 == 0 {
      n = n / 2
    } else {
      n = 3 * n + 1
    }
    steps += 1
  }
  print("27 reaches 1 in", steps, "steps")
}
```

```output
27 reaches 1 in 111 steps
```

## A whole program

Here is FizzBuzz, the program every language has to be able to write:

```plank
fn main() {
  for i in 1..16 {
    if i % 15 == 0 {
      print("FizzBuzz")
    } else if i % 3 == 0 {
      print("Fizz")
    } else if i % 5 == 0 {
      print("Buzz")
    } else {
      print(i)
    }
  }
}
```

```output
1
2
Fizz
4
Buzz
Fizz
7
8
Fizz
Buzz
11
Fizz
13
14
FizzBuzz
```

## Summary

`if` takes a real `bool` and can produce a value. `for` walks ranges, lists, dict keys and strings, and a range stops just before its end. `while` repeats with `break` and `continue` for the exits. That was enough to write FizzBuzz. Next you will package code into functions.

> **Try it yourself**
>
> 1. Print the numbers 1 to 20, but print `even` in place of every even one.
> 2. Write a `while` loop that halves 1000 until it drops below 1 and counts the steps.
> 3. Change the whole program at the end of the chapter so it stops early with `break`.
