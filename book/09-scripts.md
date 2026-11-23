# 9. Talking to the world

Plank is meant for real scripts, so files, folders, the shell, JSON and HTTP are built in.

## Files

```plank
fn main() {
  write_file("notes.txt", "milk\neggs\n")
  append_file("notes.txt", "bread\n")
  let text = read_file("notes.txt") ?? ""
  for line in text.trim().split("\n") {
    print("-", line)
  }
  print(exists("notes.txt"), remove_file("notes.txt"), exists("notes.txt"))
}
```

```output
- milk
- eggs
- bread
true true false
```

`read_file` gives a `str?`: `nil` when the file cannot be read, so you decide what that means. `list_dir`, `mkdir`, `is_dir` and `cwd` cover folders.

## Arguments and input

`args()` is the list of words after the program's name: `plank run greet.pk ada grace` gives `["ada", "grace"]`. `input("name? ")` asks for a line. `read_stdin()` takes everything piped in, so a Plank program fits in a shell pipeline.

## The shell

`run` runs a command and gives back what it printed. `status()` is its exit code. `quote` makes any text safe to pass as one argument:

```plank
fn main() {
  let name = "two words"
  let out = run("echo " + quote(name)).trim()
  print(out, status())
}
```

```output
two words 0
```

## JSON

`json_parse` reads JSON into a `Json` value. The helpers pull typed values out of it, and `.text()` writes it back:

```plank
fn main() {
  let doc = json_parse("{\"name\": \"plank\", \"tags\": [\"small\", \"fast\"], \"stars\": 42}")
  print(doc.get("name").str(), doc.get("stars").int())
  for t in doc.get("tags").items() {
    print("tag:", t.str())
  }
  print(Json.object(["ok": Json.bool(true)]).text())
}
```

```output
plank 42
tag: small
tag: fast
{"ok":true}
```

## HTTP

`http("GET", url)` sends a request and gives back the body; `status()` has the HTTP code afterwards. With a body and headers it posts:

```
let reply = http("POST", "https://example.com/api", "{\"q\": 1}", ["content-type": "application/json"])
if status() != 200 {
  print("failed:", status())
}
```

Together these cover most of what people reach for Python to do: read some files, call a command, hit an API, write a report.

> **Try it yourself**
>
> 1. Write a script that counts the lines in a file named on the command line.
> 2. Run `ls` from Plank and print how many entries it found.
> 3. Read a JSON file and print one field from it.
