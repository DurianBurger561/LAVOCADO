"""macOS-specific Tk window integration for the overlay backend."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def prepare_macos_overlay_window(root: Any) -> None:
    """Configure the overlay to participate in full-screen macOS Spaces."""

    appkit = None
    application = None
    try:
        import AppKit

        appkit = AppKit
        application = AppKit.NSApplication.sharedApplication()
        application.setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory
        )
    except Exception:
        LOGGER.debug("AppKit is unavailable for the macOS overlay", exc_info=True)

    try:
        root.tk.call("wm", "attributes", root._w, "-class", "nspanel")
    except Exception:
        LOGGER.debug("Could not create the Tk overlay as an NSPanel", exc_info=True)

    try:
        root.tk.call(
            "::tk::unsupported::MacWindowStyle",
            "style",
            root._w,
            "overlay",
            ("canJoinAllSpaces", "nonActivating"),
        )
    except Exception:  # noqa: BLE001 - Aqua/Tk version-dependent API
        try:
            root.tk.call(
                "::tk::unsupported::MacWindowStyle",
                "style",
                root._w,
                "overlay",
                "canJoinAllSpaces",
            )
        except Exception:
            LOGGER.debug("Could not set Tk overlay window style", exc_info=True)

    if appkit is None or application is None:
        return

    def configure_native_window(_event: object | None = None) -> None:
        _configure_native_overlay_window(root, application, appkit)

    configure_native_window()
    try:
        root.bind("<Map>", configure_native_window, add="+")
    except Exception:
        LOGGER.debug("Could not bind native overlay setup to map", exc_info=True)


def _configure_native_overlay_window(root: Any, application: Any, appkit: Any) -> None:
    """Allow the Tk overlay to participate in other apps' full-screen Spaces."""

    try:
        title = root.title()
        window = next(
            (
                candidate
                for candidate in application.windows()
                if candidate.title() == title
            ),
            None,
        )
        if window is None:
            return

        collection_behavior = int(window.collectionBehavior())
        collection_behavior |= (
            appkit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | appkit.NSWindowCollectionBehaviorCanJoinAllApplications
            | appkit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        window.setCollectionBehavior_(collection_behavior)
    except Exception:
        LOGGER.warning(
            "Could not enable macOS full-screen Space participation for the overlay",
            exc_info=True,
        )
