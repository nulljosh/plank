"""Compile every example, diff its output. `python3 test.py`."""
import glob, os, re, subprocess, sys

fails = 0
# every example and app, diffed against its .out; every tests/*.pk must print ok.
# Then all of it again with the collector running every 4KB, so a missed root shows up here and not in a user's program.
programs = sorted(glob.glob("examples/*.pk")) + sorted(glob.glob("apps/*.pk")) + sorted(glob.glob("tests/*.pk"))
jobs = [(src, env_name, env) for env_name, env in (("", {}), (" [gc every 4KB]", {"PLANK_GC": "4000"})) for src in programs]

def run_one(job):
    src, env_name, env = job
    want = open(src[:-3] + ".out").read() if not src.startswith("tests/") else "ok\n"
    got = subprocess.run(["./plank", "run", src], capture_output=True, text=True, env={**os.environ, **env})
    ok = got.returncode == 0 and got.stdout == want
    return ok, ("ok   " if ok else "FAIL ") + src + env_name + ("" if ok else "\n" + got.stdout + got.stderr)

# every program compiles and links on its own, so they run side by side; the output keeps the list's order
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
    for ok, line in pool.map(run_one, jobs):
        fails += not ok
        print(line)

# bad programs fail with a line number, not a traceback, at compile time and at run time
BAD = [
    # compile time
    ("fn main() {\n  x = 1\n}\n", ":2: unknown variable 'x'"),
    ("fn main() {\n  print(1 + \"a\")\n}\n", ":2: int + str: types must match, use str()"),
    ("fn main() {\n  let x = 1\n  x = 2\n}\n", ":3: 'x' is a let, use var to reassign it"),
    ("fn f() -> int {\n  print(1)\n}\nfn main() {\n}\n", ":1: function 'f' can reach its end without returning"),
    ("fn main() {\n  print(\"abc)\n}\n", ":2: this string never ends"),
    ("fn main() {\n  let xs = []\n}\n", ":2: an empty list needs its type"),
    ("fn main() {\n  let xs = [1, \"a\"]\n}\n", ":2: a list holds one type"),
    ("fn main() {\n  let d = [true: 1]\n}\n", ":2: dict keys are int or str"),
    ("struct P {\n  x: int\n}\nfn main() {\n  print(P().x)\n}\n", ":5: P is missing 'x'"),
    ("struct P {\n  x: int\n}\nfn main() {\n  print(P(1).y)\n}\n", ":5: P has no field 'y', it has x"),
    ("enum S {\n  a\n  b\n}\nfn main() {\n  match S.a {\n    .a { }\n  }\n}\n", ":6: match on S misses .b"),
    ("fn main() {\n  let x: int? = 1\n  print(x + 1)\n}\n", ":3: int? + int: types must match, use if let, ??"),
    ("fn main() {\n  let f = fn(x) => x\n}\n", ":2: say what type x is"),
    ("fn main() {\n  let f = fn(x: int) => x\n  print(f(\"a\"))\n}\n", ":3: f wants int, got str"),
    ("fn main() {\n  print(len(5))\n}\n", ":2: len() needs a str, a list or a dict, got int"),
    ("fn main() {\n  break\n}\n", ":2: break outside a loop"),
    ("fn main() {\n  print(1\n}\n", ":3: missing ) for the ( opened on line 2"),
    ("fn main() {\n  let s = \"abc\"\n  s[0] = \"x\"\n}\n", ":3: strings cannot be changed in place"),
    ("import \"nowhere.pk\"\nfn main() {\n}\n", ":1: cannot import 'nowhere.pk'"),
    ("fn main() {\n  throw \"nope\"\n}\n", ":2: nope"),
    ("fn main() {\n  throw 5\n}\n", ":2: throw takes a str message, got int"),
    ("fn main() {\n  assert(1)\n}\n", ":2: assert(cond) or assert(cond, message)"),
    ("fn main() {\n  let x: int? = 1\n  print(x == \"a\")\n}\n", ":3: int? == str: these can never be equal"),
    ("fn main() {\n  http(\"GET\")\n}\n", ":2: http(method, url, body?, headers?)"),
    ("fn f<T>(a: T, b: T) -> T {\n  return a\n}\nfn main() {\n  f(1, \"a\")\n}\n", ":5: f() got T as int and then as str"),
    ("struct S<T> {\n  x: T\n}\nfn main() {\n  let s = S<int, str>(1)\n}\n", ":5: S takes 1 type parameter, got 2"),
    ("struct S<T> {\n  xs: [T] = []\n}\nfn main() {\n  let s = S()\n}\n", ":5: cannot tell what T is from the arguments to S; say it: S<int>(...)"),
    ("struct P {\n  x: int\n}\nfn main() {\n  let p: P<int> = P(1)\n}\n", ":5: P is not generic, it takes no <>"),
    ("fn f<T>() -> T {\n  throw \"x\"\n}\nfn main() {\n  f()\n}\n", ":5: cannot tell what T is from the arguments to f()"),
    ("fn main() {\n  let x = if true { 1 } else { \"a\" }\n}\n", ":2: the two sides of this if are int and str"),
    ("fn main() {\n  let x = if true { 1 }\n}\n", ":2: an if used as a value needs an else"),
    ("fn main() {\n  while let x = 5 {\n  }\n}\n", ":2: while let unwraps an optional each time round, int is never nil"),
    ("fn main() {\n  for i, x in 0..3 {\n  }\n}\n", ":2: a range gives one number at a time"),
    ("fn main() {\n  print([\"a\"].sum())\n}\n", ":2: sum() needs a list of int or float, got [str]"),
    ("fn main() {\n  let f = fn(x: int) {\n    if x > 0 { return 1 }\n    return \"s\"\n  }\n}\n", ":4: returning str from a function that returns int"),
    ("fn main() {\n  let t = (1, 2)\n  print(t.5)\n}\n", ":3: this tuple has 2 parts, .0 to .1; there is no .5"),
    ("fn main() {\n  let (a, b) = 5\n}\n", ":2: let (a, b) needs a tuple on the right, got int"),
    ("fn main() {\n  let (a, b) = (1, 2, 3)\n}\n", ":2: this tuple has 3 parts, the let names 2"),
    ("extern fn f(xs: [int]) -> int\nfn main() {\n}\n", ":1: extern fn f can only pass int, float, bool and str, not [int]"),
    ("struct P {\n  x: int\n}\nfn main() {\n  print(P(1)?.x)\n}\n", ":5: ?. is for an optional, and P is never nil"),
    ("extern fn nope_not_real(x: int) -> int\nfn main() {\n  print(nope_not_real(1))\n}\n", ":0: the C library has no function called nope_not_real"),
    (f"import \"{os.path.abspath('examples/lib/money.pk')}\" as money\nfn main() {{\n  print(money.nope())\n}}\n", ":3: module money has nothing called nope"),
    ("fn main() {\n  print(clock(1, 2))\n}\n", ":2: clock() takes a format string and maybe a time as a float"),
    ("fn main() {\n  let x = 5?\n}\n", ":2: ? takes the value out of a Result, and int is not one"),
    ("fn f() -> int {\n  return Result.ok(1)?\n}\nfn main() {\n}\n", ":2: ? needs the function to return a Result"),
    # run time
    ("fn main() {\n  print(\"x\".matches(\"[\"))\n}\n", ":2: bad pattern"),
    ("fn main() {\n  let xs = [1]\n  xs.insert(5, 2)\n}\n", ":3: index 5 is out of range for a list of 1"),
    ("fn main() {\n  json_parse(\"[1,\")\n}\n", ":2: bad JSON: the text ends in the middle of a value"),
    ("fn main() {\n  json_parse(\"{}\").get(\"x\")\n}\n", "no key \"x\" in this JSON object"),
    ("fn main() {\n  assert(1 > 2, \"math broke\")\n}\n", ":2: assertion failed: math broke"),
    ("fn main() {\n  print(\"abc\"[5])\n}\n", ":2: index 5 is out of range for a string of 3"),
    ("fn main() {\n  let xs = [1, 2]\n  print(xs[2])\n}\n", ":3: index 2 is out of range for a list of 2"),
    ("fn main() {\n  let xs: [int] = []\n  print(xs.pop())\n}\n", ":3: pop() on an empty list"),
    ("fn main() {\n  print(int(\"4x\"))\n}\n", ":2: int() got text that is not a whole number"),
    ("fn main() {\n  let d = [\"a\": 1]\n  print(d[\"b\"])\n}\n", ':3: key "b" is not in this dict'),
    ("fn main() {\n  let x: int? = nil\n  print(x!)\n}\n", ":3: unwrapped nil with !"),
]
for src, want in BAD:
    bad = subprocess.run(["./plank", "run", "/dev/stdin"], input=src, capture_output=True, text=True)
    ok = bad.returncode == 1 and want in bad.stderr
    fails += not ok
    print(("ok   " if ok else "FAIL ") + "error" + want)
    if not ok:
        print(bad.stdout + bad.stderr)
if fails:
    sys.exit(1)

# a static build runs; on Linux it carries libc, on macOS it is a normal binary with a note
import tempfile
exe = os.path.join(tempfile.mkdtemp(), "hello")
built = subprocess.run(["./plank", "build", "examples/hello.pk", "--static", "-o", exe], capture_output=True, text=True)
ran = subprocess.run([exe], capture_output=True, text=True) if built.returncode == 0 else None
ok = ran is not None and ran.stdout == open("examples/hello.out").read()
if sys.platform != "darwin" and ok:
    ok = b"statically linked" in subprocess.run(["file", exe], capture_output=True).stdout or b"static-pie" in subprocess.run(["file", exe], capture_output=True).stdout
print(("ok   " if ok else "FAIL ") + "plank build --static")
if not ok:
    print(built.stdout + built.stderr + (ran.stdout + ran.stderr if ran else ""))
    sys.exit(1)

# the repl: only new output shows, a bad line is dropped, a bare expression prints itself
script = "let xs = [3, 1]\nxs.sorted()\nfn twice(n: int) -> int {\n  return n * 2\n}\ntwice(21)\nnope\nxs.append(9)\nlen(xs)\n"
got = subprocess.run(["./plank", "repl"], input=script, capture_output=True, text=True).stdout
want = "[1, 3]\n42\nerror: unknown variable 'nope'\n3\n"
ok = want in got.replace("> ", "").replace(". ", "")  # prompts are printed inline, strip them
print(("ok   " if ok else "FAIL ") + "plank repl")
if not ok:
    print(got)
    sys.exit(1)

# every .pk in the repo is laid out the way plank fmt would lay it out
fmt = subprocess.run(["./plank", "fmt", "--check"], capture_output=True, text=True)
print(("ok   " if fmt.returncode == 0 else "FAIL ") + "plank fmt --check")
if fmt.returncode:
    print(fmt.stdout + fmt.stderr)
    sys.exit(1)

# every built-in, keyword and method the compiler knows is in docs/SPEC.md, and every CLI command in README.md
src = open("plank.py").read()
spec = open("docs/SPEC.md").read()
names = sorted(set(re.findall(r"def b_(\w+)\(", src)) | set(re.findall(r'"(\w+)": \("pk_\w+"', src)))
names += sorted(set(re.findall(r'KEYWORDS = \{([^}]*)\}', src)[0].replace('"', "").replace("\n", "").replace(" ", "").split(",")))
names += ["append", "pop", "map", "filter", "reduce", "sort", "sorted", "first", "last", "index_of", "insert", "remove_at",
          "reverse", "reversed", "sum", "min", "max", "enumerate", "join", "keys", "values", "get", "remove", "items"]
undocumented = [n for n in names if n and not re.search(r"\b" + re.escape(n) + r"\b", spec)]
readme = open("README.md").read()
undocumented += ["plank " + c for c in ("run", "build", "emit", "test", "repl", "fmt") if "plank " + c not in readme]
print(("ok   " if not undocumented else "FAIL ") + f"docs cover the language ({len(names)} names)")
if undocumented:
    print("not in the docs:", ", ".join(undocumented))
    sys.exit(1)

# the score typed on the landing page must match the scorecard
import re
score = re.search(r"(\d+) of (\d+)\.", open("docs/COMPARE.md").read()).groups()
ok = f"<b>{score[0]}/{score[1]}</b>" in open("site/index.html").read()
print(("ok   " if ok else "FAIL ") + f"landing shows the {score[0]}/{score[1]} scorecard")
if not ok:
    sys.exit(1)

# the landing demo must match the compiler's real output
fresh = subprocess.run([sys.executable, "tools/gen-demo.py", "--check"], capture_output=True, text=True)
print(("ok   " if fresh.returncode == 0 else "FAIL ") + "site/demo.js is current")
sys.exit(1 if fresh.returncode else 0)
