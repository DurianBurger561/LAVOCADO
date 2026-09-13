"""Windows UIA reader uses the active HWND/PID and returns hostnames only."""

import unittest

from app.context.browser_registry import BrowserDefinition
from app.context.models import ApplicationContext
from app.platforms.website.windows_uia import WindowsUIAWebsiteReader
from tests.test_website_accessibility import FakeTree, Node


class FakeBridge(FakeTree):
    def __init__(self, root: Node | None) -> None:
        super().__init__()
        self.root = root
        self.root_calls = []
        self.closed = False

    def root_for_window(self, window_handle, process_id):
        self.root_calls.append((window_handle, process_id))
        return self.root

    def close(self):
        self.closed = True


def application(window_id: str | None = "123", process_id: int | None = 42) -> ApplicationContext:
    return ApplicationContext("chrome.exe", "Chrome", "chrome", window_id, 1.0, process_id)


class WindowsWebsiteReaderTests(unittest.TestCase):
    def test_reads_only_hostname_from_matching_browser_window(self) -> None:
        root = Node(children=[
            Node(role="edit", name="Address and search bar", value="https://example.com/private?q=secret")
        ])
        bridge = FakeBridge(root)
        reader = WindowsUIAWebsiteReader(bridge_factory=lambda: bridge)

        host = reader.read_active_hostname(application(), BrowserDefinition("chrome.exe", "chromium"))

        self.assertEqual(host, "example.com")
        self.assertEqual(bridge.root_calls, [(123, 42)])
        self.assertTrue(bridge.closed)

    def test_missing_identity_does_not_initialize_uia(self) -> None:
        calls = []
        reader = WindowsUIAWebsiteReader(bridge_factory=lambda: calls.append(1))

        self.assertIsNone(reader.read_active_hostname(application(None), BrowserDefinition("chrome.exe", "chromium")))
        self.assertIsNone(reader.read_active_hostname(application("bad"), BrowserDefinition("chrome.exe", "chromium")))
        self.assertIsNone(reader.read_active_hostname(application(process_id=None), BrowserDefinition("chrome.exe", "chromium")))
        self.assertEqual(calls, [])

    def test_unavailable_window_or_reader_error_is_unknown(self) -> None:
        missing = FakeBridge(None)
        reader = WindowsUIAWebsiteReader(bridge_factory=lambda: missing)
        self.assertIsNone(reader.read_active_hostname(application(), BrowserDefinition("chrome.exe", "chromium")))
        self.assertTrue(missing.closed)

        def failed_bridge():
            raise RuntimeError("https://private.example/secret")

        failed = WindowsUIAWebsiteReader(bridge_factory=failed_bridge)
        self.assertIsNone(failed.read_active_hostname(application(), BrowserDefinition("chrome.exe", "chromium")))


if __name__ == "__main__":
    unittest.main()
