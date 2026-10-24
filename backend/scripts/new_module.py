"""Scaffold a module: `make new-module NAME=catalog`.

Creates app/modules/<name>/ with a contract, README, models and service files,
and registers the module in the AGENTS.md graph (with no dependencies).
"""

import re
import sys
from pathlib import Path

from scripts.module_graph import add_module

BACKEND = Path(__file__).resolve().parents[1]
TEMPLATE = BACKEND.parent / "docs" / "templates" / "module-README.md"

FILES = {
    "__init__.py": '''"""TODO: one sentence, no "and": what this module is for."""

from app.modules.{name} import _models  # noqa: F401  (registers the tables)

__all__: list[str] = []
''',
    "_models.py": '''"""Tables of this module (`{name}_*` or singular). See AGENTS.md."""

from app.core.db import Base  # noqa: F401
''',
    "_service.py": '''"""Business logic. Takes an AsyncSession, flushes, never commits."""
''',
}


def main(name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        sys.exit(f"Module name must be snake_case, got {name!r}")
    target = BACKEND / "app" / "modules" / name
    if target.exists():
        sys.exit(f"{target} already exists")
    target.mkdir(parents=True)
    for filename, body in FILES.items():
        (target / filename).write_text(body.format(name=name))
    (target / "README.md").write_text(TEMPLATE.read_text().replace("<module>", name))
    add_module(name)
    print(f"Created {target.relative_to(BACKEND.parent)} and added `{name} ->` to AGENTS.md.")
    print("Next: fill in the README, then run `make check`.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m scripts.new_module <name>")
    main(sys.argv[1])
