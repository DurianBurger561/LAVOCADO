"""User and Developer specs stay separate and exclude the wrong tree."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackagingSpecTests(unittest.TestCase):
    def test_project_build_helpers_do_not_shadow_pypi_packaging(self) -> None:
        output = subprocess.check_output(
            [
                sys.executable,
                "-c",
                (
                    "import packaging; "
                    "from packaging.version import parse; "
                    "print(packaging.__file__); print(parse('1.2.3'))"
                ),
            ],
            cwd=ROOT,
            text=True,
        ).splitlines()

        self.assertFalse((ROOT / "packaging").exists())
        self.assertIn(
            Path(output[0]).resolve().parent.parent.name,
            {"site-packages", "dist-packages"},
        )
        self.assertEqual(output[1], "1.2.3")

    def test_user_spec_excludes_developer_and_uses_main(self) -> None:
        text = (ROOT / "lavocado.spec").read_text(encoding="utf-8")
        self.assertIn("from lavocado_packaging.spec_common import", text)
        self.assertNotIn("from packaging.spec_common import", text)
        self.assertIn('["main.py"]', text)
        self.assertIn("USER_EXCLUDES", text)
        self.assertNotIn("developer_main.py", text)
        self.assertNotIn("lab.js", text)

    def test_developer_spec_includes_lab_and_uses_developer_main(self) -> None:
        text = (ROOT / "lavocado-developer.spec").read_text(encoding="utf-8")
        self.assertIn("from lavocado_packaging.spec_common import", text)
        self.assertNotIn("from packaging.spec_common import", text)
        self.assertIn("developer_main.py", text)
        self.assertIn("developer_datas", text)
        self.assertIn("developer_hiddenimports", text)
        self.assertNotIn("USER_EXCLUDES", text)
