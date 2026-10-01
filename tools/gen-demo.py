"""Write site/demo.js from the real examples: source, output and LLVM IR.
The landing page demo never shows anything the compiler did not produce."""
import glob, json, os, subprocess, sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root)
order = ["hello", "fib", "fizzbuzz", "primes", "sqrt", "strings", "text", "lists", "structs", "loops"]
examples = []
for name in order:
    src = open(f"examples/{name}.pk").read()
    out = open(f"examples/{name}.out").read()
    ir = subprocess.run(["./plank", "emit", f"examples/{name}.pk"], capture_output=True, text=True, check=True).stdout
    # ponytail: the triple names the host, drop it so the demo is identical on Mac and Linux CI
    ir = "\n".join(l for l in ir.split("\n") if not l.startswith("target triple"))
    examples.append({"name": name, "src": src, "out": out, "ir": ir})
version = subprocess.run(["./plank", "--version"], capture_output=True, text=True).stdout.split()[-1]
js = "window.PLANK_DEMO = " + json.dumps({"version": version, "examples": examples}, ensure_ascii=False) + ";\n"
path = "site/demo.js"
if "--check" in sys.argv:
    sys.exit(0 if os.path.exists(path) and open(path).read() == js else "site/demo.js is stale, run tools/gen-demo.py")
open(path, "w").write(js)
print(path, len(js), "bytes")
