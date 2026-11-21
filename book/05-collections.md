# 5. Lists, dicts and sets

## Lists

A list holds any number of values of one type, in order:

```plank
fn main() {
  let xs = [3, 1, 4]
  xs.append(1)
  print(xs, len(xs))
  print(xs[0], xs[-1])
  xs[1] += 10
  print(xs.pop(), xs)
  print(xs.sorted(), xs.sum(), xs.max())
  print(xs[1..], 4 in xs)
}
```

```output
[3, 1, 4, 1] 4
3 1
1 [3, 11, 4]
[3, 4, 11] 18 11
[11, 4] true
```

`max()` gives an `int?`, an int that might be missing, because an empty list has no largest item. Chapter 7 is about those. Here it prints as the number.

An empty list needs its type written once, because there is nothing in it to look at:

```plank
fn main() {
  var names: [str] = []
  names.append("ada")
  print(names)
}
```

```output
["ada"]
```

Lists are shared. Hand one to a function and the function sees and changes the same list, not a copy. `let` stops the name from pointing at a different list; it does not freeze the list.

## Doing something to every item

`map` makes a new list by running a function on each item. `filter` keeps the items a function says yes to. `reduce` folds them into one value:

```plank
fn main() {
  let xs = [1, 2, 3, 4, 5, 6]
  let evens = xs.filter(fn(x) => x % 2 == 0)
  let squares = evens.map(fn(x) => x * x)
  let total = squares.reduce(0, fn(acc, x) => acc + x)
  print(evens, squares, total)
}
```

```output
[2, 4, 6] [4, 16, 36] 56
```

`fn(x) => x % 2 == 0` is a function written in place. Chapter 8 covers them properly; for now, read `=>` as "gives".

## Dicts

A dict maps keys to values. Keys are ints or strings, and the dict remembers the order they went in:

```plank
fn main() {
  let ages = ["ada": 36, "linus": 28]
  ages["grace"] = 85
  ages["linus"] += 1
  print(ages["ada"], "bob" in ages, ages.get("bob", 0))
  for name, age in ages {
    print(name, age)
  }
  print(ages.keys(), len(ages))
}
```

```output
36 false 0
ada 36
linus 29
grace 85
["ada", "linus", "grace"] 3
```

Reading a key that is not there stops the program and names the key. When a key might be missing, check with `in` or use `get` with a fallback.

## Counting words

Lists and dicts together cover a surprising amount of everyday work. This counts words and prints the most common:

```plank
fn main() {
  let text = "the cat and the hat and the bat"
  let counts: [str: int] = [:]
  for w in text.split() {
    counts[w] = counts.get(w, 0) + 1
  }
  let words = counts.keys()
  words.sort(by: fn(a, b) => counts[a] > counts[b])
  for w in words[..2] {
    print(w, counts[w])
  }
}
```

```output
the 3
and 2
```

`sort(by:)` takes a function that says whether `a` goes before `b`. Sorting is stable, so ties keep their original order.

## Sets

A `Set` holds each value once:

```plank
fn main() {
  let seen = set_of(["a", "b", "a", "c", "b"])
  seen.add("d")
  print(len(seen), "a" in seen, seen.items())
}
```

```output
4 true ["a", "b", "c", "d"]
```
