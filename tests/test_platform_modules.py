"""Tests for explicit per-platform adapter modules."""

import unittest
from unittest.mock import patch

from app.platforms import (
    UnsupportedPlatformError,
    platform_module,
    prepare_webview_environment,
)
from app.platforms import linux, macos, windows


class PlatformModuleTests(unittest.TestCase):
    def test_registry_returns_one_independent_module_per_system(self) -> None:
        self.assertIs(platform_module("Windows"), windows)
        self.assertIs(platform_module("Darwin"), macos)
        self.assertIs(platform_module("Linux"), linux)

    def test_registry_rejects_an_unknown_system(self) -> None:
        with self.assertRaises(UnsupportedPlatformError):
            platform_module("Plan9")

    def test_linux_explicitly_selects_the_qt_webview_backend(self) -> None:
        environment: dict[str, str] = {}

        with patch("app.platforms.linux.is_wsl", return_value=False):
            gui = prepare_webview_environment("Linux", environment)

        self.assertEqual(gui, "qt")
        self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", environment)

    def test_wsl_uses_software_rendering_without_overwriting_user_values(self) -> None:
        environment = {
            "WSL_DISTRO_NAME": "Ubuntu-24.04",
            "QT_OPENGL": "desktop",
        }

        gui = prepare_webview_environment("Linux", environment)

        self.assertEqual(gui, "qt")
        self.assertEqual(environment["QT_OPENGL"], "desktop")
        self.assertEqual(environment["LIBGL_ALWAYS_SOFTWARE"], "1")
        self.assertEqual(environment["QT_QUICK_BACKEND"], "software")
        self.assertIn("--disable-gpu", environment["QTWEBENGINE_CHROMIUM_FLAGS"])

    def test_native_platforms_keep_pywebviews_default_backend(self) -> None:
        self.assertIsNone(prepare_webview_environment("Windows", {}))
        self.assertIsNone(prepare_webview_environment("Darwin", {}))


if __name__ == "__main__":
    unittest.main()
