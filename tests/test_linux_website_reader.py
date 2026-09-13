"""Linux AT-SPI reader only inspects the unique active browser window."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.context.browser_registry import BrowserDefinition
from app.context.models import ApplicationContext
from app.platforms.website.linux_atspi import (
    LinuxAtspiWebsiteReader,
    _NativeAtspiBridge,
)
from tests.test_website_accessibility import FakeTree, Node


def application(process_id: int | None = 42) -> ApplicationContext:
    return ApplicationContext("firefox", "Firefox", "firefox", None, 1.0, process_id)


BROWSER = BrowserDefinition("firefox", "firefox")


class FakeBridge(FakeTree):
    def __init__(self, window: Node | None) -> None:
        super().__init__()
        self.window = window
        self.process_ids = []

    def active_window(self, process_id):
        self.process_ids.append(process_id)
        return self.window


class Accessible:
    def __init__(self, *, role="OTHER", name="", identifier="", text=None,
                 children=(), active=False, process_id=0):
        self._role = role
        self._name = name
        self._identifier = identifier
        self._text = text
        self._children = list(children)
        self._active = active
        self._process_id = process_id
        self.text_reads = 0

    def get_role(self):
        return self._role

    def get_accessible_id(self):
        return self._identifier

    def get_name(self):
        return self._name

    def get_description(self):
        return ""

    def get_text_iface(self):
        return self if self._text is not None else None

    def get_character_count(self):
        return len(self._text)

    def get_text(self, start, end):
        self.text_reads += 1
        return self._text[start:end]

    def get_child_count(self):
        return len(self._children)

    def get_child_at_index(self, index):
        return self._children[index]

    def get_state_set(self):
        return SimpleNamespace(contains=lambda state: self._active and state == "ACTIVE")

    def get_process_id(self):
        return self._process_id


def native_bridge(desktop: Accessible) -> _NativeAtspiBridge:
    atspi = SimpleNamespace(
        init=lambda: None,
        get_desktop=lambda index: desktop if index == 0 else None,
        StateType=SimpleNamespace(ACTIVE="ACTIVE"),
        Role=SimpleNamespace(DOCUMENT_FRAME="DOCUMENT_FRAME", DOCUMENT_WEB="DOCUMENT_WEB",
                             ENTRY="ENTRY", EDITBAR="EDITBAR"),
    )
    gi = SimpleNamespace(require_version=lambda name, version: None)
    with patch.dict("sys.modules", {"gi": gi, "gi.repository": SimpleNamespace(Atspi=atspi)}):
        return _NativeAtspiBridge()


class LinuxWebsiteReaderTests(unittest.TestCase):
    def test_reads_browser_chrome_not_page_content(self) -> None:
        bridge = FakeBridge(Node(children=[
            Node(role="edit", identifier="urlbar-input", value="https://example.org/private?q=secret"),
            Node(role="document", children=[
                Node(role="edit", name="Address bar", value="https://evil.example/")
            ]),
        ]))
        reader = LinuxAtspiWebsiteReader(bridge_factory=lambda: bridge)

        self.assertEqual(reader.read_active_hostname(application(), BROWSER), "example.org")
        self.assertEqual(bridge.process_ids, [42])
        self.assertEqual(bridge.values_read, 1)

    def test_missing_pid_and_native_errors_are_unknown(self) -> None:
        calls = []
        reader = LinuxAtspiWebsiteReader(bridge_factory=lambda: calls.append(1))
        self.assertIsNone(reader.read_active_hostname(application(None), BROWSER))
        self.assertEqual(calls, [])

        def failed_bridge():
            raise RuntimeError("https://private.example/path")

        self.assertIsNone(
            LinuxAtspiWebsiteReader(bridge_factory=failed_bridge).read_active_hostname(
                application(), BROWSER
            )
        )

    def test_native_bridge_requires_unique_matching_active_window(self) -> None:
        address = Accessible(role="ENTRY", name="Address bar", text="https://safe.example/path")
        page = Accessible(role="DOCUMENT_WEB", children=[
            Accessible(role="ENTRY", name="Address bar", text="https://evil.example/")
        ])
        browser_window = Accessible(children=[address, page], active=True)
        other_window = Accessible(active=False)
        browser = Accessible(children=[browser_window], process_id=42)
        other = Accessible(children=[other_window], process_id=99)
        bridge = native_bridge(Accessible(children=[browser, other]))

        self.assertIs(bridge.active_window(42), browser_window)
        self.assertEqual(bridge.active_process_id(), 42)
        self.assertIsNone(bridge.active_window(99))
        self.assertEqual(find_host(bridge, browser_window), "safe.example")
        self.assertEqual(address.text_reads, 1)
        self.assertEqual(page._children[0].text_reads, 0)

        other_window._active = True
        self.assertIsNone(bridge.active_window(42))
        self.assertIsNone(bridge.active_process_id())

    def test_native_bridge_rejects_truncated_tree_and_oversized_value(self) -> None:
        oversized = Accessible(role="ENTRY", identifier="urlbar-input", text="a" * 2049)
        bridge = native_bridge(Accessible(children=[]))
        self.assertIsNone(bridge.value(oversized))
        self.assertEqual(oversized.text_reads, 0)

        many_apps = Accessible(children=[Accessible() for _ in range(129)])
        self.assertIsNone(native_bridge(many_apps).active_window(42))


def find_host(bridge: _NativeAtspiBridge, window: Accessible) -> str | None:
    from app.context.website.accessibility import find_address_hostname

    return find_address_hostname(window, bridge)


if __name__ == "__main__":
    unittest.main()
