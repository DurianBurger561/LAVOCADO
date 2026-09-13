"""Read the focused macOS browser's address field through AXUIElement."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.context.browser_registry import BrowserDefinition
from app.context.models import ApplicationContext
from app.context.website.accessibility import (
    TraversalLimitExceeded,
    find_address_hostname,
)


class MacOSAXWebsiteReader:
    source = "ax"

    def __init__(self, bridge_factory: Callable[[], Any] | None = None) -> None:
        self._bridge_factory = bridge_factory or _NativeAXBridge

    def read_active_hostname(
        self,
        application: ApplicationContext,
        _browser: BrowserDefinition,
    ) -> str | None:
        if application.process_id is None or not application.identifier:
            return None
        try:
            bridge = self._bridge_factory()
            window = bridge.focused_window(
                application.process_id,
                application.identifier,
            )
            return find_address_hostname(window, bridge)
        except Exception:
            # AX errors can contain private attribute values. Do not log them.
            return None


class _NativeAXBridge:
    """Bounded, read-only accessibility traversal; never prompts for access."""

    def __init__(self) -> None:
        import AppKit
        import ApplicationServices

        self._appkit = AppKit
        self._ax = ApplicationServices

    def focused_window(self, process_id: int, bundle_id: str) -> Any | None:
        if not self._ax.AXIsProcessTrusted():
            return None
        frontmost = self._appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if (
            frontmost is None
            or int(frontmost.processIdentifier()) != process_id
            or not frontmost.bundleIdentifier()
            or str(frontmost.bundleIdentifier()).casefold() != bundle_id.casefold()
        ):
            return None
        app = self._ax.AXUIElementCreateApplication(process_id)
        self._ax.AXUIElementSetMessagingTimeout(app, 0.4)
        return self._attribute(app, "AXFocusedWindow")

    def _attribute(self, node: Any, name: str) -> Any | None:
        error, value = self._ax.AXUIElementCopyAttributeValue(node, name, None)
        return value if error == 0 else None

    def role(self, node: Any) -> str:
        role = self._attribute(node, "AXRole")
        if role in {"AXWebArea", "AXDocument"}:
            return "document"
        if role in {"AXTextField", "AXComboBox", "AXSearchField"}:
            return "edit"
        return "other"

    def identifier(self, node: Any) -> str | None:
        value = self._attribute(node, "AXIdentifier")
        return value if isinstance(value, str) else None

    def name(self, node: Any) -> str | None:
        for attribute in ("AXDescription", "AXTitle", "AXPlaceholderValue"):
            value = self._attribute(node, attribute)
            if isinstance(value, str) and value:
                return value
        return None

    def value(self, node: Any) -> str | None:
        value = self._attribute(node, "AXValue")
        return value if isinstance(value, str) else None

    def children(self, node: Any, limit: int) -> list[Any]:
        children = self._attribute(node, "AXChildren")
        if children is None or isinstance(children, (str, bytes)):
            return []
        try:
            count = len(children)
        except TypeError:
            return []
        if count > limit:
            raise TraversalLimitExceeded()
        return list(children)
