"""The Plank book: book/*.md plus docs/SPEC.md and docs/ARCHITECTURE.md as appendices, to site/book/index.html, with
every program in it checked. The appendices are read from docs/ at build time, so the book and the docs cannot drift.

Markdown it knows beyond paragraphs, headings and lists: ```plank and ```output blocks, `> **Note**` and
`> **Try it yourself**` boxes, `![caption](art/name.svg)` figures (inlined so they take the page's colours, numbered
Figure <chapter>-<n>) and `|` tables.

`python3 tools/gen-book.py` writes the page. `--pdf` also prints site/book/plank-book.pdf with headless Chrome
(gitignored, release.sh makes it before deploying). `--check` compiles every ```plank block that has a fn main, runs it,
diffs it against the ```output block right under it, checks it is laid out the way plank fmt would, and fails if
site/book/index.html is stale. test.py runs the check, so a page and the compiler can never disagree.
"""
import glob, html, os, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
CHAPTERS = sorted(glob.glob("book/*.md"))
OUT = "site/book/index.html"
PDF = "site/book/plank-book.pdf"
APPENDICES = [("docs/SPEC.md", "A", "The language reference"), ("docs/ARCHITECTURE.md", "B", "A map of plank.py")]
ART = ["wood-cabin", "wood-endgrain", "wood-stack", "wood-planks", "wood-burl", "wood-logs", "wood-hatch", "wood-cathedral"]  # halftone plates from site/art (tools/gen-wood.py), one per chapter opener in turn

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


def figure(caption, src, fig):
    svg = open(os.path.join("book", src)).read().strip()
    return f'<figure class="fig">{svg}<figcaption><b>Figure {fig}:</b> {inline(caption)}</figcaption></figure>'


def table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not re.match(r"^\|[\s:|-]+\|$", r.strip())]
    head, body = cells[0], cells[1:]
    th = "".join(f"<th>{inline(c)}</th>" for c in head)
    tb = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
    return f'<div class="table"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


def render(text, chapter_id, label=None, plain="shell", figs=None):
    """One chapter to HTML. `label` overrides the opener ("Appendix A"); `plain` is how an unlabelled ``` block is
    shown, so the docs' examples get highlighted like the book's. Returns (title, number label, html)."""
    lines, out, i = text.split("\n"), [], 0
    para, title, number = [], None, label
    figs = figs if figs is not None else [0]

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            lang = line[3:].strip() or plain
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
        f = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", line)
        if m:
            flush()
            level, words = len(m.group(1)), m.group(2)
            if level == 1:
                n = re.match(r"^(\d+)\. (.*)", words)
                if n and not label:
                    number, words = "Chapter " + n.group(1), n.group(2)
                    figs[0] = int(n.group(1))
                title = words
                out.append(f'<h1 id="{chapter_id}">{inline(words)}</h1>')
            else:
                out.append(f'<h{level} id="{chapter_id}-{slug(words)}">{inline(words)}</h{level}>')
        elif f:
            flush()
            figs.append(None)
            out.append(figure(f.group(1), f.group(2), f"{figs[0] or chapter_id[-1].upper()}-{len(figs) - 1}"))
        elif line.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].removeprefix(" "))
                i += 1
            head = re.match(r"^\*\*([^*]+)\*\*\s*", quote[0])
            kind = head.group(1) if head else "Note"
            if head:
                quote[0] = quote[0][head.end():]
            _, _, inner = render("\n".join(quote), chapter_id, label="box", plain=plain, figs=figs)
            out.append(f'<aside class="box {slug(kind).split("-")[0]}"><p class="box-h">{inline(kind)}</p>{inner}</aside>')
            continue
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(table(rows))
            continue
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
    return title, number, "\n".join(out)


def section(cid, number, title, body, n):
    """A chapter opener in the No Starch way: a big number, the title, a halftone plate; then the text."""
    big = number.split()[-1] if number else ""
    plate = ART[n % len(ART)]
    head = f'<header class="opener"><div class="plate" style="--img: url(../art/{plate}.png)" aria-hidden="true"></div>'
    head += f'<p class="chap-no"><span>{number or ""}</span><b>{big}</b></p></header>' if number else "</header>"
    edit = f'<a class="edit" href="https://github.com/nulljosh/plank/edit/main/{cid}">Edit this page</a>'
    return f'<section class="chapter" data-src="{cid}">\n{head}\n{body}\n{edit}\n</section>'


def page():
    parts, toc = [], []
    for n, path in enumerate(CHAPTERS):
        cid = slug(os.path.basename(path)[:-3])
        title, number, body = render(open(path).read(), cid)
        toc.append(f'<li><a href="#{cid}"><small>{(number or "").removeprefix("Chapter ")}</small>{inline(title)}</a></li>')
        parts.append(section(path, number, title, body, n))
    for n, (path, letter, name) in enumerate(APPENDICES):
        cid = "appendix-" + letter.lower()
        text = re.sub(r"^# .*", "# " + name, open(path).read(), count=1)
        title, number, body = render(text, cid, label="Appendix " + letter, plain="plank")
        toc.append(f'<li><a href="#{cid}"><small>{letter}</small>{inline(title)}</a></li>')
        parts.append(section(path, number, title, body, n + len(CHAPTERS)))
    version = re.search(r'^VERSION = "([^"]+)"', open("plank.py").read(), re.M).group(1)
    tpl = open("book/page.html").read()
    return tpl.replace("{{toc}}", "\n".join(toc)).replace("{{chapters}}", "\n".join(parts)).replace("{{version}}", version)


def pdf():
    """Print the page to a PDF the way a reader's browser would, with the print styles in book.css."""
    chrome = os.environ.get("CHROME") or next((c for c in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium"]
                                              if os.path.exists(c) or subprocess.run(["which", c], capture_output=True).returncode == 0), None)
    if not chrome:
        sys.exit("no Chrome found for --pdf; set CHROME=/path/to/chrome")
    # served over http, not file://: Chrome refuses CSS masks (the halftone plates) from file URLs
    import functools, http.server, threading
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory="site"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=4000",
                        f"--print-to-pdf={os.path.join(ROOT, PDF)}", f"http://127.0.0.1:{srv.server_port}/book/"], check=True, capture_output=True)
    finally:
        srv.shutdown()
    print(f"wrote {PDF}, {os.path.getsize(PDF) // 1024} KB")


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
    print(f"wrote {OUT}, {len(CHAPTERS)} chapters, {len(APPENDICES)} appendices, {len(programs())} programs")
    if "--pdf" in sys.argv:
        pdf()
