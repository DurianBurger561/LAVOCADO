"""Read a Windows browser's address bar using Microsoft UI Automation."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from typing import Any

from app.context.browser_registry import BrowserDefinition
from app.context.models import ApplicationContext
from app.context.website.accessibility import (
    TraversalLimitExceeded,
    find_address_hostname,
)

_EDIT_CONTROL_TYPE = 50004
_DOCUMENT_CONTROL_TYPE = 50030
_MAX_CHILDREN = 40


class WindowsUIAWebsiteReader:
    source = "uia"

    def __init__(self, bridge_factory: Callable[[], Any] | None = None) -> None:
        self._bridge_factory = bridge_factory or _NativeUIABridge

    def read_active_hostname(
        self,
        application: ApplicationContext,
        _browser: BrowserDefinition,
    ) -> str | None:
        """Never return a raw URL or allow native exception text to escape."""

        if not application.window_id or application.process_id is None:
            return None
        try:
            window_handle = int(application.window_id, 10)
            if window_handle <= 0:
                return None
        except ValueError:
            return None

        bridge = None
        try:
            bridge = self._bridge_factory()
            root = bridge.root_for_window(window_handle, application.process_id)
            hostname = find_address_hostname(root, bridge)
            del root
            return hostname
        except Exception:
            return None
        finally:
            if bridge is not None:
                close = getattr(bridge, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass


class _NativeUIABridge:
    """One thread-bound COM connection, created only on the context worker."""

    def __init__(self) -> None:
        import comtypes
        from comtypes.client import CreateObject, GetModule

        comtypes.CoInitialize()
        try:
            GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as uia

            self._uia = uia
            self._automation = CreateObject(
                uia.CUIAutomation,
                interface=uia.IUIAutomation,
            )
            self._walker = self._automation.ControlViewWalker
            self._comtypes = comtypes
        except Exception:
            comtypes.CoUninitialize()
            raise

    def root_for_window(self, window_handle: int, process_id: int) -> Any | None:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        if user32.GetForegroundWindow() != window_handle:
            return None
        root = self._automation.ElementFromHandle(window_handle)
        if root is None or int(root.CurrentProcessId) != process_id:
            return None
        return root

    def role(self, node: Any) -> str:
        control_type = int(node.CurrentControlType)
        if control_type == _DOCUMENT_CONTROL_TYPE:
            return "document"
        if control_type == _EDIT_CONTROL_TYPE:
            return "edit"
        return "other"

    def identifier(self, node: Any) -> str | None:
        return node.CurrentAutomationId

    def name(self, node: Any) -> str | None:
        return node.CurrentName

    def value(self, node: Any) -> str | None:
        pattern = node.GetCurrentPattern(self._uia.UIA_ValuePatternId)
        if pattern is None:
            return None
        value_pattern = pattern.QueryInterface(self._uia.IUIAutomationValuePattern)
        return value_pattern.CurrentValue

    def children(self, node: Any, limit: int) -> list[Any]:
        children = []
        current = self._walker.GetFirstChildElement(node)
        while current is not None and len(children) < min(limit, _MAX_CHILDREN):
            children.append(current)
            current = self._walker.GetNextSiblingElement(current)
        if current is not None:
            raise TraversalLimitExceeded()
        return children

    def close(self) -> None:
        self._walker = None
        self._automation = None
        self._comtypes.CoUninitialize()
