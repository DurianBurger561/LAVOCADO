"""macOS-specific Tk window integration for the overlay backend."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def prepare_macos_overlay_window(root: Any) -> None:
    """Create a borderless, keyboard-capable window across macOS Spaces."""

    # Aqua's overrideredirect sets Tk's internal noActivates flag. Clearing
    # NSWindow style bits cannot undo it. A managed plain window is borderless
    # too, but keeps Tk's keyboard and input-method handling enabled.
    root.tk.call(
        "::tk::unsupported::MacWindowStyle",
        "style",
        root._w,
        "plain",
        "canJoinAllSpaces",
    )

    try:
        import AppKit

        application = AppKit.NSApplication.sharedApplication()
        application.setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory
        )
    except ImportError:
        LOGGER.debug("AppKit is unavailable for the macOS overlay", exc_info=True)
        return

    def configure_native_window(event: Any = None) -> None:
        # Child widgets emit Map events too; only configure the top-level.
        if event is None or event.widget is root:
            _configure_native_overlay_window(root, application, AppKit)
            if event is not None:
                root.after_idle(
                    lambda: _configure_native_overlay_window(root, application, AppKit)
                )

    configure_native_window()
    root.bind("<Map>", configure_native_window, add="+")


def activate_macos_overlay_window(root: Any) -> None:
    """Activate the overlay before focusing its Tk text input."""

    try:
        import AppKit
    except ImportError:
        return

    try:
        application = AppKit.NSApplication.sharedApplication()
        window = _native_window(root, application)
        if window is None:
            return
        application.activateIgnoringOtherApps_(True)
        window.makeKeyAndOrderFront_(None)
        _configure_native_overlay_window(root, application, AppKit)
    except Exception:
        LOGGER.warning("Could not activate the macOS overlay window", exc_info=True)


def _native_window(root: Any, application: Any) -> Any:
    title = root.title()
    return next(
        (window for window in application.windows() if window.title() == title),
        None,
    )


def _configure_native_overlay_window(root: Any, application: Any, appkit: Any) -> None:
    """Allow the Tk overlay to participate in other apps' full-screen Spaces."""

    try:
        window = _native_window(root, application)
        if window is None:
            return
        # Tk 9 can restore a title bar while mapping a managed window. Remove
        # only the Cocoa decorations; leave Tk's activation state managed.
        window.setStyleMask_(appkit.NSWindowStyleMaskBorderless)
        window.setMovable_(False)
        collection_behavior = int(window.collectionBehavior())
        collection_behavior |= (
            appkit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | getattr(appkit, "NSWindowCollectionBehaviorCanJoinAllApplications", 0)
            | appkit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        window.setCollectionBehavior_(collection_behavior)
    except Exception:
        LOGGER.warning(
            "Could not enable macOS full-screen Space participation for the overlay",
            exc_info=True,
        )
