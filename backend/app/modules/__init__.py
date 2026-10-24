"""Business modules. Each subpackage is one module; its `__init__.py` is its contract.

Rules live in AGENTS.md ("Modules") and are enforced by tests/architecture.
"""

import importlib
import pkgutil
from pathlib import Path


def module_names() -> list[str]:
    return sorted(
        info.name
        for info in pkgutil.iter_modules([str(Path(__file__).parent)])
        if info.ispkg and not info.name.startswith("_")
    )


def load_all() -> None:
    """Import every module's contract, which registers its ORM models on `Base.metadata`."""
    for name in module_names():
        importlib.import_module(f"{__name__}.{name}")
