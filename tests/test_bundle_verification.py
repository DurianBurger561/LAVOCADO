"""Bundle verification helpers used by CI."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import importlib.util
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


verify_developer_bundle = _load_script("verify_developer_bundle").verify_developer_bundle
verify_user_bundle = _load_script("verify_user_bundle").verify_user_bundle


class BundleVerificationTests(unittest.TestCase):
    def test_user_bundle_rejects_lab_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app" / "ui" / "web").mkdir(parents=True)
            (root / "app" / "ui" / "web" / "index.html").write_text("<html></html>", encoding="utf-8")
            (root / "developer" / "benchmark" / "ui").mkdir(parents=True)
            (root / "developer" / "benchmark" / "ui" / "lab.js").write_text("lab", encoding="utf-8")
            errors = verify_user_bundle(root)
            self.assertTrue(errors)

    def test_user_bundle_accepts_clean_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app" / "ui" / "web").mkdir(parents=True)
            (root / "app" / "ui" / "web" / "index.html").write_text("<html>LAVOCADO</html>", encoding="utf-8")
            errors = verify_user_bundle(root)
            self.assertEqual(errors, [])

    def test_developer_bundle_requires_lab(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app" / "ui" / "web").mkdir(parents=True)
            (root / "app" / "ui" / "web" / "index.html").write_text("x", encoding="utf-8")
            (root / "app" / "ui" / "web" / "app.js").write_text("x", encoding="utf-8")
            errors = verify_developer_bundle(root)
            self.assertTrue(errors)
            (root / "developer" / "benchmark" / "ui").mkdir(parents=True)
            (root / "developer" / "benchmark" / "ui" / "lab.js").write_text("lab", encoding="utf-8")
            (root / "developer" / "benchmark" / "dataset.py").write_text("x", encoding="utf-8")
            errors = verify_developer_bundle(root)
            self.assertEqual(errors, [])
