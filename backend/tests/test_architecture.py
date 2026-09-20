"""The layering is enforced here, not left to convention: dependencies may only point inward."""

import ast
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
PROJECT_PACKAGES = {"api", "config", "domain", "infrastructure", "services", "tasks"}

# layer -> project packages it may import. Third-party imports are governed by STDLIB_ONLY.
ALLOWED = {
    "domain": {"domain"},
    "services": {"domain", "services"},
    "infrastructure": {"domain", "infrastructure"},
    "api": {"api", "config", "domain", "services"},
    # The worker's entry points follow the same rule as the API's: go through a service.
    "tasks": {"tasks", "config", "domain", "services"},
}
STDLIB_ONLY = {"domain", "services"}


def _imported_packages(path: Path) -> set[str]:
    packages = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            packages.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            packages.add(node.module.split(".")[0])
    return packages


@pytest.mark.parametrize("layer", ALLOWED)
def test_layer_only_imports_what_it_may(layer):
    violations = []
    for path in (BACKEND / layer).rglob("*.py"):
        for package in _imported_packages(path):
            if package in PROJECT_PACKAGES:
                allowed = package in ALLOWED[layer]
            else:
                allowed = layer not in STDLIB_ONLY or package in sys.stdlib_module_names
            if not allowed:
                violations.append(f"{path.relative_to(BACKEND)} imports {package}")
    assert not violations, violations
