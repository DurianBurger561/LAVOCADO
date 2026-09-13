"""User and Developer specs stay separate and exclude the wrong tree."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackagingSpecTests(unittest.TestCase):
    def test_user_spec_excludes_developer_and_uses_main(self) -> None:
        text = (ROOT / "lavocado.spec").read_text(encoding="utf-8")
        self.assertIn('["main.py"]', text)
        self.assertIn("USER_EXCLUDES", text)
        self.assertNotIn("developer_main.py", text)
        self.assertNotIn("lab.js", text)

    def test_developer_spec_includes_lab_and_uses_developer_main(self) -> None:
        text = (ROOT / "lavocado-developer.spec").read_text(encoding="utf-8")
        self.assertIn("developer_main.py", text)
        self.assertIn("developer_datas", text)
        self.assertIn("developer_hiddenimports", text)
        self.assertNotIn("USER_EXCLUDES", text)
