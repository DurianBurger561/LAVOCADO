"""macOS AX reader stays read-only and discards private URL components."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.context.browser_registry import BrowserDefinition
from app.context.models import ApplicationContext
from app.platforms.website.macos_ax import MacOSAXWebsiteReader, _NativeAXBridge
from tests.test_website_accessibility import FakeTree, Node


class FakeBridge(FakeTree):
    def __init__(self, window: Node | None) -> None:
        super().__init__()
        self.window = window
        self.calls = []

    def focused_window(self, process_id, identifier):
        self.calls.append((process_id, identifier))
        return self.window


def application(process_id: int | None = 42, identifier: str | None = "com.apple.Safari"):
    return ApplicationContext(identifier, "Safari", "Safari", None, 1.0, process_id)


class MacOSWebsiteReaderTests(unittest.TestCase):
    def test_reads_focused_browser_address_only(self) -> None:
        bridge = FakeBridge(Node(children=[
            Node(role="edit", name="Smart Search Field", value="https://example.com/private?q=secret"),
            Node(role="document", children=[
                Node(role="edit", name="Address bar", value="https://evil.example/")
            ]),
        ]))
        reader = MacOSAXWebsiteReader(bridge_factory=lambda: bridge)

        host = reader.read_active_hostname(application(), BrowserDefinition("com.apple.Safari", "safari"))

        self.assertEqual(host, "example.com")
        self.assertEqual(bridge.calls, [(42, "com.apple.Safari")])
        self.assertEqual(bridge.values_read, 1)

    def test_falls_back_to_browser_script_when_ax_is_unavailable(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(
                returncode=0,
                stdout="https://www.example.com/private?q=secret\n",
            )

        reader = MacOSAXWebsiteReader(
            bridge_factory=lambda: None,
            script_runner=run,
        )

        host = reader.read_active_hostname(
            application(),
            BrowserDefinition("com.apple.Safari", "safari"),
        )

        self.assertEqual(host, "www.example.com")
        self.assertEqual(calls[0][0][0:2], ["osascript", "-e"])
        self.assertEqual(calls[0][1]["timeout"], 0.8)

    def test_script_fallback_is_limited_to_known_macos_browsers(self) -> None:
        calls = []
        reader = MacOSAXWebsiteReader(
            bridge_factory=lambda: None,
            script_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        host = reader.read_active_hostname(
            ApplicationContext("com.example.viewer", "Viewer", "Viewer", None, 1.0, 42),
            BrowserDefinition("com.example.viewer", "viewer"),
        )

        self.assertIsNone(host)
        self.assertEqual(calls, [])

    def test_script_fallback_does_not_require_process_id(self) -> None:
        reader = MacOSAXWebsiteReader(
            bridge_factory=lambda: (_ for _ in ()).throw(AssertionError("AX should be skipped")),
            script_runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0,
                stdout="https://example.com/secret",
            ),
        )

        host = reader.read_active_hostname(
            application(process_id=None),
            BrowserDefinition("com.apple.Safari", "safari"),
        )

        self.assertEqual(host, "example.com")

    def test_missing_pid_or_bundle_and_ax_errors_are_unknown(self) -> None:
        calls = []
        reader = MacOSAXWebsiteReader(bridge_factory=lambda: calls.append(1))
        browser = BrowserDefinition("com.apple.Safari", "safari")

        self.assertIsNone(reader.read_active_hostname(application(process_id=None), browser))
        self.assertIsNone(reader.read_active_hostname(application(identifier=None), browser))
        self.assertEqual(calls, [])

        def failed_bridge():
            raise RuntimeError("https://private.example/path")

        self.assertIsNone(
            MacOSAXWebsiteReader(bridge_factory=failed_bridge).read_active_hostname(
                application(), browser
            )
        )

    def test_native_bridge_requires_trust_and_matching_frontmost_app(self) -> None:
        fake_app = SimpleNamespace(
            processIdentifier=lambda: 42,
            bundleIdentifier=lambda: "com.apple.Safari",
        )
        fake_workspace = SimpleNamespace(frontmostApplication=lambda: fake_app)
        fake_appkit = SimpleNamespace(
            NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: fake_workspace)
        )
        calls = []
        fake_ax = SimpleNamespace(
            AXIsProcessTrusted=lambda: True,
            AXUIElementCreateApplication=lambda pid: calls.append(("create", pid)) or "app",
            AXUIElementSetMessagingTimeout=lambda app, seconds: calls.append(("timeout", seconds)),
            AXUIElementCopyAttributeValue=lambda _app, _name, _out: (0, "window"),
        )

        with patch.dict("sys.modules", {"AppKit": fake_appkit, "ApplicationServices": fake_ax}):
            bridge = _NativeAXBridge()

        self.assertIsNone(bridge.focused_window(99, "com.apple.Safari"))
        self.assertIsNone(bridge.focused_window(42, "com.google.Chrome"))
        self.assertEqual(bridge.focused_window(42, "com.apple.Safari"), "window")
        self.assertEqual(calls, [("create", 42), ("timeout", 0.4)])

        fake_ax.AXIsProcessTrusted = lambda: False
        self.assertIsNone(bridge.focused_window(42, "com.apple.Safari"))

    def test_ax_children_accepts_native_sequence_objects(self) -> None:
        class NativeSequence:
            def __len__(self):
                return 2

            def __iter__(self):
                return iter(("first", "second"))

        bridge = object.__new__(_NativeAXBridge)
        bridge._ax = SimpleNamespace(
            AXUIElementCopyAttributeValue=lambda _node, _name, _out: (0, NativeSequence())
        )
        self.assertEqual(bridge.children("window", 2), ["first", "second"])


if __name__ == "__main__":
    unittest.main()
