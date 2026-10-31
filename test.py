import subprocess

SOURCE = """fn main() {
  let a = true
  let x = if a { 1 } else { 2 }
  print(x)
}
"""

result = subprocess.run(
    ["./plank", "run", "/dev/stdin"],
    input=SOURCE,
    text=True,
    capture_output=True,
)

assert result.returncode == 0, result.stderr
assert result.stdout == "1\n", result.stdout
print("ok")
