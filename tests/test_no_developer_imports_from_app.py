"""User product core must not import the Developer Benchmark Lab."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _imports_developer(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "developer" or alias.name.startswith("developer."):
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "developer" or module.startswith("developer."):
                found.append(module)
    return found


class DeveloperImportBoundaryTests(unittest.TestCase):
    def test_app_package_does_not_import_developer(self) -> None:
        violations: list[str] = []
        for path in APP_ROOT.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            imported = _imports_developer(tree)
            if imported:
                violations.append(f"{path}: {imported}")
        self.assertEqual(violations, [])

    def test_user_main_does_not_import_developer(self) -> None:
        source = (APP_ROOT.parent / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("developer", source)
