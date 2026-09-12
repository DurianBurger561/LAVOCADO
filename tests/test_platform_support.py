"""Tests for desktop platform adaptation."""

import unittest

from app.platform_support import (
    UnsupportedPlatformError,
    enable_windows_dpi_awareness,
    prepare_desktop_environment,
    screen_capture_help,
    tkinter_help,
)


class SuccessfulUser32:
    def __init__(self) -> None:
        self.context = None

    def SetProcessDpiAwarenessContext(self, context: object) -> int:
        self.context = context
        return 1


class LegacyUser32:
    def __init__(self) -> None:
        self.legacy_called = False

    def SetProcessDpiAwarenessContext(self, _context: object) -> int:
        return 0

    def SetProcessDPIAware(self) -> int:
        self.legacy_called = True
        return 1


class PlatformSupportTests(unittest.TestCase):
    def test_accepts_major_desktop_platforms(self) -> None:
        self.assertEqual(prepare_desktop_environment("Linux"), "Linux")
        self.assertEqual(prepare_desktop_environment("Darwin"), "Darwin")

    def test_rejects_unknown_platforms(self) -> None:
        with self.assertRaises(UnsupportedPlatformError):
            prepare_desktop_environment("Plan9")

    def test_enables_windows_per_monitor_dpi_awareness(self) -> None:
        user32 = SuccessfulUser32()

        self.assertTrue(enable_windows_dpi_awareness(user32))
        self.assertIsNotNone(user32.context)

    def test_falls_back_to_legacy_windows_dpi_awareness(self) -> None:
        user32 = LegacyUser32()

        self.assertTrue(enable_windows_dpi_awareness(user32))
        self.assertTrue(user32.legacy_called)

    def test_returns_platform_specific_setup_help(self) -> None:
        self.assertIn("python3-tk", tkinter_help("Linux"))
        self.assertIn("python.org", tkinter_help("Darwin"))
        self.assertIn("Tcl/Tk", tkinter_help("Windows"))
        self.assertIn("Privacy & Security", screen_capture_help("Darwin"))
        self.assertIn("Wayland", screen_capture_help("Linux"))


if __name__ == "__main__":
    unittest.main()
