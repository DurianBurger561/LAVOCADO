"""Read the focused macOS browser's address field through AXUIElement."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

from app.context.browser_registry import BrowserDefinition
from app.context.models import ApplicationContext
from app.context.website.accessibility import (
    TraversalLimitExceeded,
    find_address_hostname,
)
from app.context.website.normalization import normalize_hostname


AppleScriptRunner = Callable[..., subprocess.CompletedProcess[str]]

_BROWSER_APPLESCRIPTS = {
    "com.apple.safari": """
tell application "Safari"
    if not (exists front document) then return ""
    return URL of front document
end tell
""",
    "com.google.chrome": """
tell application "Google Chrome"
    if (count of windows) is 0 then return ""
    return URL of active tab of front window
end tell
""",
    "com.microsoft.edgemac": """
tell application "Microsoft Edge"
    if (count of windows) is 0 then return ""
    return URL of active tab of front window
end tell
""",
    "com.brave.browser": """
tell application "Brave Browser"
    if (count of windows) is 0 then return ""
    return URL of active tab of front window
end tell
""",
}


class MacOSAXWebsiteReader:
    source = "ax"

    def __init__(
        self,
        bridge_factory: Callable[[], Any] | None = None,
        script_runner: AppleScriptRunner | None = None,
    ) -> None:
        self._bridge_factory = bridge_factory or _NativeAXBridge
        self._script_runner = script_runner or subprocess.run

    def read_active_hostname(
        self,
        application: ApplicationContext,
        _browser: BrowserDefinition,
    ) -> str | None:
        if not application.identifier:
            return None
        if application.process_id is not None:
            try:
                bridge = self._bridge_factory()
                window = bridge.focused_window(
                    application.process_id,
                    application.identifier,
                )
                hostname = find_address_hostname(window, bridge)
                if hostname is not None:
                    return hostname
            except Exception:
                # AX errors can contain private attribute values. Do not log them.
                pass
        return self._read_hostname_via_browser_script(application.identifier)

    def _read_hostname_via_browser_script(self, identifier: str) -> str | None:
        script = _BROWSER_APPLESCRIPTS.get(identifier.casefold())
        if script is None:
            return None
        try:
            result = self._script_runner(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=0.8,
                check=False,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        # Normalize immediately so the full address never escapes this method.
        return normalize_hostname(result.stdout)


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
