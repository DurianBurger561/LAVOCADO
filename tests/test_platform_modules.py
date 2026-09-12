"""Tests for the process-scoped PlatformAdapter implementations."""

import unittest
from pathlib import Path
from unittest.mock import Mock

from app.platforms import (
    UnsupportedPlatformError,
    WindowInfo,
    create_platform_adapter,
)
from app.platforms.linux import LinuxPlatform
from app.platforms.macos import MacOSPlatform
from app.platforms.windows import WindowsPlatform


class PlatformModuleTests(unittest.TestCase):
    def test_factory_returns_one_adapter_for_the_requested_system(self) -> None:
        self.assertIsInstance(create_platform_adapter("Windows"), WindowsPlatform)
        self.assertIsInstance(create_platform_adapter("Darwin"), MacOSPlatform)
        self.assertIsInstance(create_platform_adapter("Linux"), LinuxPlatform)

    def test_factory_rejects_an_unknown_system(self) -> None:
        with self.assertRaises(UnsupportedPlatformError):
            create_platform_adapter("Plan9")

    def test_each_adapter_owns_its_data_directory_policy(self) -> None:
        home = Path("/users/test")
        windows = WindowsPlatform(environ={}, home=home)
        macos = MacOSPlatform(environ={}, home=home)
        linux = LinuxPlatform(environ={}, home=home, release="generic-linux")

        self.assertEqual(
            windows.default_data_dir(),
            home / "AppData" / "Local" / "LAVOCADO",
        )
        self.assertEqual(
            macos.default_data_dir(),
            home / "Library" / "Application Support" / "LAVOCADO",
        )
        self.assertEqual(
            linux.default_data_dir(),
            home / ".local" / "share" / "lavocado",
        )

    def test_explicit_data_directory_override_has_priority(self) -> None:
        platform = LinuxPlatform(
            environ={"LAVOCADO_DATA_DIR": "/tmp/private-lavocado"},
            home=Path("/users/test"),
            release="generic-linux",
        )

        self.assertEqual(
            platform.default_data_dir(),
            Path("/tmp/private-lavocado"),
        )

    def test_adapter_delegates_foreground_window_access(self) -> None:
        window = WindowInfo(title="Example", app_name="Browser")
        provider = Mock()
        provider.active_window.return_value = window
        platform = LinuxPlatform(
            environ={},
            release="generic-linux",
            window_provider=provider,
        )

        self.assertIs(platform.get_foreground_window(), window)
        provider.active_window.assert_called_once_with()

    def test_linux_explicitly_selects_the_qt_webview_backend(self) -> None:
        environment: dict[str, str] = {}
        platform = LinuxPlatform(
            environ=environment,
            release="generic-linux",
        )

        gui = platform.prepare_webview_environment()

        self.assertEqual(gui, "qt")
        self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", environment)

    def test_wsl_uses_software_rendering_without_overwriting_user_values(self) -> None:
        environment = {
            "WSL_DISTRO_NAME": "Ubuntu-24.04",
            "QT_OPENGL": "desktop",
        }
        platform = LinuxPlatform(environ=environment, release="microsoft-standard")

        gui = platform.prepare_webview_environment()

        self.assertEqual(gui, "qt")
        self.assertEqual(environment["QT_OPENGL"], "desktop")
        self.assertEqual(environment["LIBGL_ALWAYS_SOFTWARE"], "1")
        self.assertEqual(environment["QT_QUICK_BACKEND"], "software")
        self.assertIn("--disable-gpu", environment["QTWEBENGINE_CHROMIUM_FLAGS"])

    def test_native_platforms_keep_pywebviews_default_backend(self) -> None:
        self.assertIsNone(WindowsPlatform(environ={}).prepare_webview_environment())
        self.assertIsNone(MacOSPlatform(environ={}).prepare_webview_environment())


if __name__ == "__main__":
    unittest.main()
