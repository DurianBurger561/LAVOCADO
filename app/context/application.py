"""Reduce platform foreground-window metadata to rule-safe app identity."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.context.models import ApplicationContext

if TYPE_CHECKING:
    from app.platforms.base import WindowInfo


def application_from_window(
    window: WindowInfo | None,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> ApplicationContext | None:
    """Never copy the mutable window title into the context or rule key."""

    if window is None:
        return None
    return ApplicationContext(
        identifier=window.app_identifier,
        display_name=window.app_name or None,
        process_name=window.app_name or None,
        window_id=window.window_id,
        captured_at=clock(),
        process_id=window.process_id,
        window_center=window.center,
    )
