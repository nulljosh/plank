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

# one bad program must fail with a line number, not a traceback
bad = subprocess.run(["./plank", "run", "/dev/stdin"], input="fn main() {\n  x = 1\n}\n",
                     capture_output=True, text=True)
ok = bad.returncode == 1 and ":2: unknown variable 'x'" in bad.stderr
fails += not ok
print(("ok   " if ok else "FAIL ") + "error message")
sys.exit(1 if fails else 0)
