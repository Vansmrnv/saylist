"""Architecture rules from AGENTS.md, enforced. Each failure message says how to fix it.

Covers: module contracts (doors), the allowed dependency graph, layer direction,
table ownership, and the migration chain. Reads source with `ast`, so no database is needed.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.db import Base
from app.modules import load_all, module_names
from scripts.module_graph import AGENTS_MD, read_graph

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
MODULES = APP / "modules"


@dataclass(frozen=True)
class Ref:
    """One imported name, e.g. `app.modules.catalog` or `app.modules.catalog._models`."""

    file: Path
    line: int
    target: str
    private: bool  # reaches past a module's contract

    def where(self) -> str:
        return f"{self.file.relative_to(BACKEND)}:{self.line}"


def _py_files() -> Iterator[Path]:
    yield from sorted(APP.rglob("*.py"))


def _owner(path: Path) -> str | None:
    """The module a file belongs to, or None for app/core, app/main.py, etc."""
    parts = path.relative_to(APP).parts
    return parts[1] if parts[0] == "modules" and len(parts) > 2 else None


def _module_of(target: str) -> str | None:
    parts = target.split(".")
    return parts[2] if len(parts) > 2 and parts[:2] == ["app", "modules"] else None


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _refs(path: Path) -> Iterator[Ref]:
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                yield Ref(path, node.lineno, alias.name, len(parts) > 3)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            for alias in node.names:
                if node.module == "app.modules":
                    target = f"app.modules.{alias.name}"
                    yield Ref(path, node.lineno, target, _is_private(alias.name))
                else:
                    deep = len(parts) > 3 or (len(parts) == 3 and _is_private(alias.name))
                    yield Ref(path, node.lineno, node.module, deep)


def _report(problems: list[str], how_to_fix: str) -> str:
    return "\n  " + "\n  ".join(problems) + f"\n\nHow to fix: {how_to_fix}"


def test_imports_are_absolute() -> None:
    problems = [
        f"{path.relative_to(BACKEND)}:{node.lineno}"
        for path in _py_files()
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ImportFrom) and node.level > 0
    ]
    assert not problems, _report(problems, "use `from app.modules.x import ...`.")


def test_graph_in_agents_md_lists_exactly_the_modules_on_disk() -> None:
    graph, on_disk = read_graph(), set(module_names())
    unknown_deps = {d for deps in graph.values() for d in deps} - set(graph)
    problems = [f"on disk, missing from the graph: {m}" for m in sorted(on_disk - set(graph))]
    problems += [f"in the graph, missing on disk: {m}" for m in sorted(set(graph) - on_disk)]
    problems += [f"depended on, but not declared: {m}" for m in sorted(unknown_deps)]
    assert not problems, _report(
        problems, f"edit the module-graph block in {AGENTS_MD.name}, or run `make new-module`."
    )


def test_modules_are_reached_only_through_their_contract() -> None:
    problems = [
        f"{ref.where()} imports {ref.target} past its contract"
        for path in _py_files()
        for ref in _refs(path)
        if ref.private and _module_of(ref.target) not in (None, _owner(path))
    ]
    assert not problems, _report(
        problems,
        "import only what the module's __init__.py exports. Need more? Add it to that "
        "module's `__all__` and its README 'Contract' section.",
    )


def test_modules_depend_only_on_what_the_graph_allows() -> None:
    graph = read_graph()
    problems = []
    for path in _py_files():
        owner = _owner(path)
        if owner is None:
            continue
        for ref in _refs(path):
            target = _module_of(ref.target)
            if target not in (None, owner) and target not in graph.get(owner, set()):
                problems.append(f"{ref.where()}: {owner} -> {target} is not in the graph")
    assert not problems, _report(
        problems,
        f"if the dependency is intended, add it to the module-graph block in {AGENTS_MD.name} "
        "(cycles are not allowed); otherwise pass ids, not objects.",
    )


def test_module_graph_has_no_cycles() -> None:
    graph = read_graph()
    done: set[str] = set()

    def visit(node: str, path: list[str]) -> list[str] | None:
        if node in path:
            return [*path[path.index(node) :], node]
        if node in done:
            return None
        for dep in graph.get(node, set()):
            cycle = visit(dep, [*path, node])
            if cycle:
                return cycle
        done.add(node)
        return None

    cycles = [c for m in sorted(graph) if (c := visit(m, []))]
    assert not cycles, _report([" -> ".join(cycles[0])], "break the cycle; pass ids or events.")


def test_layers_point_inward() -> None:
    """core imports nothing from modules or entrypoints; modules never import entrypoints."""
    problems = []
    for path in _py_files():
        layer = path.relative_to(APP).parts[0]
        for ref in _refs(path):
            if layer == "core" and ref.target.startswith(("app.modules", "app.main")):
                problems.append(f"{ref.where()}: core imports {ref.target}")
            if layer == "modules" and ref.target.startswith("app.main"):
                problems.append(f"{ref.where()}: a module imports the entrypoint")
    assert not problems, _report(problems, "move shared code down into app/core.")


def test_every_module_has_a_contract_and_a_readme() -> None:
    problems = []
    for name in module_names():
        init, readme = MODULES / name / "__init__.py", MODULES / name / "README.md"
        tree = ast.parse(init.read_text())
        if not ast.get_docstring(tree):
            problems.append(f"{name}/__init__.py has no docstring (one sentence: its purpose)")
        targets = [
            t
            for n in tree.body
            for t in (n.targets if isinstance(n, ast.Assign) else [getattr(n, "target", None)])
        ]
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            problems.append(f"{name}/__init__.py defines no __all__")
        if not readme.exists():
            problems.append(f"{name}/README.md is missing")
    assert not problems, _report(problems, "see docs/templates/module-README.md.")


def _table_prefixes(module: str) -> tuple[str, ...]:
    if module.endswith("ies"):
        singular = module[:-3] + "y"
    elif module.endswith(("sses", "ses", "xes")):
        singular = module[:-2]
    elif module.endswith("s"):
        singular = module[:-1]
    else:
        singular = module
    return tuple(dict.fromkeys((module, singular)))


def _table_owners() -> dict[str, str | None]:
    load_all()
    owners: dict[str, str | None] = dict.fromkeys(Base.metadata.tables)
    for mapper in Base.registry.mappers:
        for table in mapper.tables:
            owners[table.name] = _module_of(mapper.class_.__module__)
    return owners


def test_every_table_is_owned_by_one_module_and_named_after_it() -> None:
    problems = []
    for table, owner in sorted(_table_owners().items()):
        if owner is None:
            problems.append(f"table {table} is not declared by a mapped class inside a module")
        elif not any(table == p or table.startswith(p + "_") for p in _table_prefixes(owner)):
            wanted = " or ".join(f"`{p}_*`" for p in _table_prefixes(owner))
            problems.append(f"table {table} (module {owner}) must be named {wanted}")
    assert not problems, _report(problems, "rename the table, or move it to its owning module.")


def test_module_readme_lists_the_tables_it_owns() -> None:
    problems = []
    for table, owner in sorted(_table_owners().items()):
        readme = MODULES / str(owner) / "README.md"
        if owner and readme.exists() and f"`{table}`" not in readme.read_text():
            problems.append(f"{owner}/README.md does not mention `{table}`")
    assert not problems, _report(problems, "list each table in the README 'Tables' section.")


def test_no_orm_relationships_across_modules() -> None:
    load_all()
    problems = [
        f"{mapper.class_.__name__}.{rel.key} -> {rel.mapper.class_.__name__}"
        for mapper in Base.registry.mappers
        for rel in mapper.relationships
        if _module_of(mapper.class_.__module__) != _module_of(rel.mapper.class_.__module__)
    ]
    assert not problems, _report(
        problems, "keep the foreign key column, drop the relationship(); see ADR 0001."
    )


def test_migrations_have_a_single_head() -> None:
    heads = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads()
    assert len(heads) <= 1, _report(
        [f"heads: {', '.join(heads)}"],
        "two branches added migrations in parallel; run `make migration-merge`.",
    )
