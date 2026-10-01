"""Compile every example, diff its output. `python3 test.py`."""
import glob, subprocess, sys

fails = 0
for src in sorted(glob.glob("examples/*.pk")):
    want = open(src[:-3] + ".out").read()
    got = subprocess.run(["./plank", "run", src], capture_output=True, text=True)
    ok = got.returncode == 0 and got.stdout == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + src)
    if not ok:
        print(got.stdout + got.stderr)

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
    # run time
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
