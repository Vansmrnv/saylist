"""The allowed module dependency graph. Its single source is a block in AGENTS.md.

Format, one module per line: `catalog -> businesses, media` or `businesses ->` (no dependencies).
"""

import re
from pathlib import Path

AGENTS_MD = Path(__file__).resolve().parents[2] / "AGENTS.md"
START = "<!-- module-graph:start -->"
END = "<!-- module-graph:end -->"
_LINE = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*->\s*(.*?)\s*$")


def _block(text: str) -> tuple[int, int]:
    start, end = text.find(START), text.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"{AGENTS_MD} must contain {START} ... {END}")
    return start + len(START), end


def read_graph(text: str | None = None) -> dict[str, set[str]]:
    text = AGENTS_MD.read_text() if text is None else text
    start, end = _block(text)
    graph: dict[str, set[str]] = {}
    for line in text[start:end].splitlines():
        match = _LINE.match(line)
        if match:
            name, deps = match.groups()
            graph[name] = {d.strip() for d in deps.split(",") if d.strip()}
    return graph


def add_module(name: str) -> None:
    text = AGENTS_MD.read_text()
    if name in read_graph(text):
        return
    _, end = _block(text)
    fence = text.rfind("```", 0, end)
    if fence == -1:
        raise ValueError("The module-graph block must hold a fenced ```text block.")
    AGENTS_MD.write_text(text[:fence] + f"{name} ->\n" + text[fence:])
