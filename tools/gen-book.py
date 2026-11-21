"""The Plank book: book/*.md to site/book/index.html, with every program in it checked.

`python3 tools/gen-book.py` writes the page. `--check` compiles every ```plank block that has a fn main, runs it,
diffs it against the ```output block right under it, checks it is laid out the way plank fmt would, and fails if
site/book/index.html is stale. test.py runs the check, so a page and the compiler can never disagree.
"""
import glob, html, os, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
CHAPTERS = sorted(glob.glob("book/*.md"))
OUT = "site/book/index.html"

KW = r"\b(fn|tool|let|var|if|else|while|for|in|return|break|continue|true|false|and|or|not|struct|enum|match|nil|import|as|try|catch|throw|extern|self)\b"
TY = r"\b(int|float|bool|str|Result|Json|Set)\b|\b[A-Z]\w*\b"


def blocks(text):
    """(lang, body) for every fenced block, in order."""
    return [(m.group(1), m.group(2)) for m in re.finditer(r"^```(\w*)\n(.*?)^```$", text, re.M | re.S)]


def programs():
    """(chapter, index, source, expected output or None) for every runnable block."""
    found = []
    for path in CHAPTERS:
        bs = blocks(open(path).read())
        for i, (lang, body) in enumerate(bs):
            if lang == "plank" and re.search(r"^fn main\(\)", body, re.M):
                want = bs[i + 1][1] if i + 1 < len(bs) and bs[i + 1][0] == "output" else None
                found.append((path, i, body, want))
    return found


def check_one(job):
    path, i, body, want = job
    # the program sits at the repo root so `import "lib/ai.pk"` resolves; it runs in a scratch folder so files it writes vanish
    d = tempfile.mkdtemp()
    src = os.path.join(ROOT, f".book-{os.path.basename(path)[:-3]}-{i}.pk")
    open(src, "w").write(body)
    try:
        got = subprocess.run([os.path.join(ROOT, "plank"), "run", src], capture_output=True, text=True, cwd=d)
        fmt = subprocess.run([os.path.join(ROOT, "plank"), "fmt", "--check", src], capture_output=True, text=True)
    finally:
        for f in (src, src[:-3]):
            if os.path.exists(f):
                os.remove(f)
    where = f"{path} block {i + 1}"
    if got.returncode != 0:
        return f"{where}: did not run\n{body}\n{got.stderr}"
    if want is not None and got.stdout != want:
        return f"{where}: printed\n{got.stdout}but the book says\n{want}"
    if fmt.returncode != 0:
        return f"{where}: not laid out the way plank fmt would\n{fmt.stdout}{fmt.stderr}"
    return None


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", lambda m: "<code>" + m.group(1) + "</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def highlight(code):
    """Plank source to HTML: comments, strings (with their \\( ) holes), keywords, types and numbers."""
    out, i = [], 0
    tok = re.compile(r"(?P<c>#[^\n]*)|(?P<s>\"(?:\\.|[^\"\\])*\")|(?P<k>" + KW + ")|(?P<t>" + TY + r")|(?P<n>\b\d+(?:\.\d+)?(?:e\d+)?\b)")
    for m in tok.finditer(code):
        out.append(html.escape(code[i:m.start()], quote=False))
        t = html.escape(m.group(0), quote=False)
        out.append(f'<span class="{m.lastgroup}">{t}</span>')
        i = m.end()
    out.append(html.escape(code[i:], quote=False))
    return "".join(out)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def render(text, chapter_id):
    lines, out, i = text.split("\n"), [], 0
    para, title = [], None

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            lang = line[3:].strip()
            j = i + 1
            while not lines[j].startswith("```"):
                j += 1
            body = "\n".join(lines[i + 1:j])
            if lang == "plank":
                out.append(f'<pre class="code"><code>{highlight(body)}</code></pre>')
            elif lang == "output":
                out.append(f'<pre class="output" aria-label="Output"><code>{html.escape(body, quote=False)}</code></pre>')
            else:
                out.append(f'<pre class="shell"><code>{html.escape(body, quote=False)}</code></pre>')
            i = j + 1
            continue
        m = re.match(r"^(#{1,3}) (.*)", line)
        if m:
            flush()
            level, words = len(m.group(1)), m.group(2)
            if level == 1:
                title = words
                out.append(f'<h1 id="{chapter_id}">{inline(words)}</h1>')
            else:
                out.append(f'<h{level} id="{chapter_id}-{slug(words)}">{inline(words)}</h{level}>')
        elif re.match(r"^(- |\d+\. )", line):
            flush()
            ordered = not line.startswith("- ")
            items = []
            while i < len(lines) and re.match(r"^(- |\d+\. )", lines[i]):
                items.append(re.sub(r"^(- |\d+\. )", "", lines[i]))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join("<li>" + inline(x) + "</li>" for x in items) + f"</{tag}>")
            continue
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    return title, "\n".join(out)


def page():
    parts, toc = [], []
    for path in CHAPTERS:
        cid = slug(os.path.basename(path)[:-3])
        title, body = render(open(path).read(), cid)
        toc.append(f'<li><a href="#{cid}">{inline(title)}</a></li>')
        parts.append(f'<section class="chapter">\n{body}\n</section>')
    version = re.search(r'^VERSION = "([^"]+)"', open("plank.py").read(), re.M).group(1)
    tpl = open("book/page.html").read()
    return tpl.replace("{{toc}}", "\n".join(toc)).replace("{{chapters}}", "\n".join(parts)).replace("{{version}}", version)


if __name__ == "__main__":
    if "--check" in sys.argv:
        progs = programs()
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            fails = [f for f in pool.map(check_one, progs) if f]
        for f in fails:
            print("FAIL", f)
        stale = not os.path.exists(OUT) or open(OUT).read() != page()
        if stale:
            print(f"FAIL {OUT} is stale, run python3 tools/gen-book.py")
        print(f"{len(progs)} programs in the book, {len(fails)} wrong")
        sys.exit(1 if fails or stale else 0)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write(page())
    print(f"wrote {OUT}, {len(CHAPTERS)} chapters, {len(programs())} programs")
