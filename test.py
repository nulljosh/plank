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
    ("fn main() {\n  x = 1\n}\n", ":2: unknown variable 'x'"),
    ("fn main() {\n  let xs = [1, 2]\n  print(xs[2])\n}\n", ":3: index 2 is out of range for a list of 2"),
    ("fn main() {\n  print(int(\"4x\"))\n}\n", ":2: int() got text that is not a whole number"),
    ("fn main() {\n  let d = [\"a\": 1]\n  print(d[\"b\"])\n}\n", ':3: key "b" is not in this dict'),
    ("enum S {\n  a\n  b\n}\nfn main() {\n  match S.a {\n    .a { }\n  }\n}\n", ":6: match on S misses .b"),
    ("fn main() {\n  let x: int? = nil\n  print(x!)\n}\n", ":3: unwrapped nil with !"),
    ("struct P {\n  x: int\n}\nfn main() {\n  print(P().x)\n}\n", ":5: P is missing 'x'"),
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

# the landing demo must match the compiler's real output
fresh = subprocess.run([sys.executable, "tools/gen-demo.py", "--check"], capture_output=True, text=True)
print(("ok   " if fresh.returncode == 0 else "FAIL ") + "site/demo.js is current")
sys.exit(1 if fresh.returncode else 0)
