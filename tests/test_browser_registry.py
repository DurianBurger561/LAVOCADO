"""Supported-browser identity must not be inferred from mutable titles."""

import unittest

from app.context.browser_registry import BrowserRegistry
from app.context.models import ApplicationContext


def application(identifier: str | None, display_name: str = "Browser") -> ApplicationContext:
    return ApplicationContext(identifier, display_name, None, "window", 1.0)


class BrowserRegistryTests(unittest.TestCase):
    def test_windows_macos_and_linux_identifiers(self) -> None:
        registry = BrowserRegistry()
        for identifier, family in (
            ("CHROME.EXE", "chromium"),
            ("msedge.exe", "chromium"),
            ("firefox.exe", "firefox"),
            ("com.apple.Safari", "safari"),
            ("com.google.Chrome", "chromium"),
            ("org.mozilla.firefox", "firefox"),
            ("google-chrome-stable", "chromium"),
            ("chromium", "chromium"),
        ):
            with self.subTest(identifier=identifier):
                self.assertEqual(registry.identify(application(identifier)).family, family)

    def test_display_name_does_not_create_browser_identity(self) -> None:
        registry = BrowserRegistry()
        self.assertIsNone(registry.identify(application("steam.exe", "Chrome")))
        self.assertIsNone(registry.identify(application(None, "Safari")))


if __name__ == "__main__":
    unittest.main()
