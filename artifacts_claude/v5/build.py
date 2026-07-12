"""Assemble v5 artifact HTML files: <title> + inlined _tokens.css + body.

Usage:  python build.py [name ...]     (no args = build every src/*.body.html)
Output: artifacts_claude/v5/<name>.html  (self-contained, CSP-safe)
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "src"
CSS = (SRC / "_tokens.css").read_text(encoding="utf-8")


def build(name: str) -> Path:
    body_path = SRC / f"{name}.body.html"
    body = body_path.read_text(encoding="utf-8")
    # first line of the body file may set the title:  <!-- title: ... -->
    title = "TCT Cockpit v5"
    first = body.split("\n", 1)[0].strip()
    if first.startswith("<!-- title:"):
        title = first[len("<!-- title:"):].rstrip("->").strip()
        body = body.split("\n", 1)[1]
    out = HERE / f"{name}.html"
    out.write_text(
        f"<title>{title}</title>\n<style>\n{CSS}\n</style>\n{body}",
        encoding="utf-8",
    )
    return out


names = sys.argv[1:] or sorted(
    p.name.removesuffix(".body.html") for p in SRC.glob("*.body.html")
)
for n in names:
    print(build(n))
