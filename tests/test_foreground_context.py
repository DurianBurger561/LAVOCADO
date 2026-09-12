"""Context discovery happens before policy and reads sites only for browsers."""

import unittest

from app.context.foreground_service import ForegroundContextService
from app.context.models import ApplicationContext, WebsiteContextState


def application(identifier: str, window_id: str = "one") -> ApplicationContext:
    return ApplicationContext(identifier, identifier, identifier, window_id, 10.0)


class FakeWebsiteReader:
    def __init__(self, values: list[str | None | Exception]) -> None:
        self.values = iter(values)
        self.calls = []

    def read_active_hostname(self, app, browser) -> str | None:
        self.calls.append((app.identifier, browser.family))
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


class ForegroundContextTests(unittest.TestCase):
    def test_non_browser_does_not_read_address_bar(self) -> None:
        reader = FakeWebsiteReader([])
        service = ForegroundContextService(
            lambda: application("steam.exe"), reader, clock=lambda: 20.0
        )

        context = service.discover()

        self.assertFalse(context.is_browser)
        self.assertIsNone(context.website)
        self.assertEqual(context.application.identifier, "steam.exe")
        self.assertEqual(reader.calls, [])

    def test_browser_gets_app_and_hostname_only(self) -> None:
        reader = FakeWebsiteReader(["https://trusted.example/private?q=secret"])
        service = ForegroundContextService(
            lambda: application("chrome.exe"), reader, clock=lambda: 20.0
        )

        context = service.discover()

        self.assertTrue(context.is_browser)
        self.assertEqual(context.website.state, WebsiteContextState.KNOWN)
        self.assertEqual(context.website.hostname, "trusted.example")
        self.assertEqual(context.website.browser, "chromium")
        self.assertEqual(reader.calls, [("chrome.exe", "chromium")])
        self.assertNotIn("private", repr(context))
        self.assertNotIn("secret", repr(context))

    def test_reader_failure_is_unknown_and_does_not_reuse_old_site(self) -> None:
        apps = iter([application("chrome.exe", "one"), application("chrome.exe", "two")])
        reader = FakeWebsiteReader([
            "https://trusted.example/",
            RuntimeError("https://private.example/secret"),
        ])
        service = ForegroundContextService(lambda: next(apps), reader)

        first = service.discover()
        second = service.discover()

        self.assertEqual(first.website.hostname, "trusted.example")
        self.assertEqual(second.website.state, WebsiteContextState.UNKNOWN)
        self.assertIsNone(second.website.hostname)
        self.assertNotIn("private.example", repr(second))

    def test_application_failure_is_unidentified_and_skips_website(self) -> None:
        reader = FakeWebsiteReader([])

        def failed_application():
            raise RuntimeError("private title")

        context = ForegroundContextService(failed_application, reader).discover()

        self.assertIsNone(context.application.identifier)
        self.assertIsNone(context.website)
        self.assertEqual(reader.calls, [])


if __name__ == "__main__":
    unittest.main()
