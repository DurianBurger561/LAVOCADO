"""Read an active Linux browser address field using AT-SPI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.context.browser_registry import BrowserDefinition
from app.context.models import ApplicationContext
from app.context.website.accessibility import (
    TraversalLimitExceeded,
    find_address_hostname,
)

_MAX_APPLICATIONS = 128
_MAX_WINDOWS_PER_APPLICATION = 32
_MAX_ADDRESS_CHARACTERS = 2048


class LinuxAtspiWebsiteReader:
    source = "at-spi"

    def __init__(self, bridge_factory: Callable[[], Any] | None = None) -> None:
        self._bridge_factory = bridge_factory or _NativeAtspiBridge

    def read_active_hostname(
        self,
        application: ApplicationContext,
        _browser: BrowserDefinition,
    ) -> str | None:
        if application.process_id is None or application.process_id <= 0:
            return None
        try:
            bridge = self._bridge_factory()
            window = bridge.active_window(application.process_id)
            return find_address_hostname(window, bridge)
        except Exception:
            # AT-SPI exceptions can contain private text; never log them.
            return None


class _NativeAtspiBridge:
    """One bounded, read-only view of the desktop accessibility tree."""

    def __init__(self) -> None:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        self._atspi = Atspi
        Atspi.init()

    def active_window(self, process_id: int) -> Any | None:
        active = self._active_window_with_pid()
        return active[1] if active is not None and active[0] == process_id else None

    def active_process_id(self) -> int | None:
        active = self._active_window_with_pid()
        return active[0] if active is not None else None

    def _active_window_with_pid(self) -> tuple[int, Any] | None:
        desktop = self._atspi.get_desktop(0)
        if desktop is None:
            return None
        application_count = desktop.get_child_count()
        if application_count < 0 or application_count > _MAX_APPLICATIONS:
            return None

        active_windows: list[tuple[int, Any]] = []
        for app_index in range(application_count):
            app = desktop.get_child_at_index(app_index)
            if app is None:
                return None
            window_count = app.get_child_count()
            if window_count < 0 or window_count > _MAX_WINDOWS_PER_APPLICATION:
                return None
            for window_index in range(window_count):
                window = app.get_child_at_index(window_index)
                if window is None:
                    return None
                states = window.get_state_set()
                if states is not None and states.contains(self._atspi.StateType.ACTIVE):
                    active_windows.append((int(app.get_process_id()), window))
                    if len(active_windows) > 1:
                        return None

        return active_windows[0] if len(active_windows) == 1 else None

    def role(self, node: Any) -> str:
        role = node.get_role()
        if role in {self._atspi.Role.DOCUMENT_FRAME, self._atspi.Role.DOCUMENT_WEB}:
            return "document"
        if role in {self._atspi.Role.ENTRY, self._atspi.Role.EDITBAR}:
            return "edit"
        return "other"

    def identifier(self, node: Any) -> str | None:
        value = node.get_accessible_id()
        return value if isinstance(value, str) else None

    def name(self, node: Any) -> str | None:
        for value in (node.get_name(), node.get_description()):
            if isinstance(value, str) and value:
                return value
        return None

    def value(self, node: Any) -> str | None:
        text = node.get_text_iface()
        if text is None:
            return None
        length = text.get_character_count()
        if length < 1 or length > _MAX_ADDRESS_CHARACTERS:
            return None
        value = text.get_text(0, length)
        return value if isinstance(value, str) else None

    def children(self, node: Any, limit: int) -> list[Any]:
        count = node.get_child_count()
        if count < 0 or count > limit:
            raise TraversalLimitExceeded()
        children = [node.get_child_at_index(index) for index in range(count)]
        if any(child is None for child in children):
            raise TraversalLimitExceeded()
        return children
