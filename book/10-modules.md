# 10. Programs in more than one file

## import

`import` pulls in everything another file defines. Paths are relative to the file doing the importing:

```
import "lib/money.pk"
```

For bigger programs, give the file a name so its functions do not collide with yours:

```
import "lib/shapes.pk" as shapes

fn main() {
  print(shapes.area_of(shapes.Kind.square(3.0)))
}
```

Inside `shapes.pk` nothing changes; it uses its own names plainly. A file is read once, however many times it is imported.

## Packages

An import that starts with `github.com/` is a package. Plank fetches the file the first time, keeps it under `~/.plank/pkg`, and reads it from there after that:

```
import "github.com/nulljosh/plank@v3.1.0/examples/lib/money.pk" as money
```

`@v3.1.0` pins a tag. There is no registry and no lock file: a package is a file in a git repository, and the tag says which version of it you mean.

## Tests

A test in Plank is a program that prints `ok`. Put checks in it with `assert`:

```plank
fn add(a: int, b: int) -> int {
  return a + b
}

fn main() {
  assert(add(2, 2) == 4, "two and two")
  assert(add(-1, 1) == 0)
  print("ok")
}
```

```output
ok
```

`plank test` runs every `.pk` in `tests/` and reports any that did not print `ok`. Plank's own test suite works this way.

## Tidy code

`plank fmt` lays out your files the house way: two-space indents, one statement per line, blocks opened on the same line. `plank fmt --check` only reports, which is what you want in CI. Every program in this book passes it.

## Shipping

`plank build app.pk` makes a native binary. On Linux, `plank build app.pk --static` makes one with no shared libraries at all, which you can copy to any Linux machine and run.
