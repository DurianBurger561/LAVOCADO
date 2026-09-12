"""Platform-neutral foreground-window blocklist matching."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app import config
from app.platforms import (
    WindowInfo,
    WindowProvider,
    create_window_provider as platform_window_provider,
)
from app.platforms.linux import LinuxWindowProvider
from app.platforms.macos import MacOSWindowProvider
from app.platforms.windows import WindowsWindowProvider

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BlocklistResult:
    blocked: bool
    matched_term: str | None = None
    window: WindowInfo | None = None


def create_window_provider(system_name: str | None = None) -> WindowProvider:
    """Create the selected platform provider through the adapter registry."""

    return platform_window_provider(system_name)


class WindowWatcher:
    """Match configured terms against the active app and window title."""

    def __init__(
        self,
        blocked_terms: Sequence[str] = config.BLOCKED_APPS,
        provider: WindowProvider | None = None,
        system_name: str | None = None,
    ) -> None:
        self._blocked_terms = tuple(
            term.strip() for term in blocked_terms if term.strip()
        )
        self._provider = provider
        self._system_name = system_name

    def check(self) -> BlocklistResult:
        if not self._blocked_terms:
            return BlocklistResult(blocked=False)

        try:
            if self._provider is None:
                self._provider = create_window_provider(self._system_name)
            window = self._provider.active_window()
        except Exception:
            LOGGER.exception(
                "Could not read the active window; skipping blocklist check"
            )
            return BlocklistResult(blocked=False)
        if window is None:
            return BlocklistResult(blocked=False)

        searchable = f"{window.app_name}\n{window.title}".casefold()
        for term in self._blocked_terms:
            if term.casefold() in searchable:
                return BlocklistResult(
                    blocked=True,
                    matched_term=term,
                    window=window,
                )

        return BlocklistResult(blocked=False, window=window)


__all__ = [
    "BlocklistResult",
    "LinuxWindowProvider",
    "MacOSWindowProvider",
    "WindowInfo",
    "WindowProvider",
    "WindowWatcher",
    "WindowsWindowProvider",
    "create_window_provider",
]
