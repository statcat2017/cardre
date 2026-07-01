"""Service-layer boundary tests: cardre.services modules must produce correct
contracts without importing from sidecar."""

import ast
from pathlib import Path

def test_cardre_services_does_not_import_sidecar():
    """Keep the existing import boundary guard."""
    services_dir = Path("cardre/services")
    violations = []
    for py_file in sorted(services_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("sidecar"):
                    violations.append(f"{py_file} imports from {node.module}")
    if violations:
        import pytest
        pytest.fail("\n".join(violations))
