"""Tests for cross-platform local data paths."""

import unittest
from pathlib import Path

from app.paths import default_data_dir, default_database_path


class DataPathTests(unittest.TestCase):
    def test_windows_uses_local_app_data(self) -> None:
        path = default_data_dir(
            system_name="Windows",
            environ={"LOCALAPPDATA": "C:/Users/test/AppData/Local"},
            home=Path("C:/Users/test"),
        )

        self.assertEqual(path, Path("C:/Users/test/AppData/Local/LAVOCADO"))

    def test_macos_uses_application_support(self) -> None:
        path = default_data_dir(
            system_name="Darwin",
            environ={},
            home=Path("/Users/test"),
        )

        self.assertEqual(
            path,
            Path("/Users/test/Library/Application Support/LAVOCADO"),
        )

    def test_linux_honours_xdg_data_home(self) -> None:
        path = default_data_dir(
            system_name="Linux",
            environ={"XDG_DATA_HOME": "/tmp/xdg-data"},
            home=Path("/home/test"),
        )

        self.assertEqual(path, Path("/tmp/xdg-data/lavocado"))

    def test_explicit_override_has_priority(self) -> None:
        path = default_database_path(
            system_name="Linux",
            environ={"LAVOCADO_DATA_DIR": "/tmp/private-lavocado"},
            home=Path("/home/test"),
        )

        self.assertEqual(path, Path("/tmp/private-lavocado/events.db"))


if __name__ == "__main__":
    unittest.main()
