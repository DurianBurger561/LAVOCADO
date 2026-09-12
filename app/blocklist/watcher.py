"""Platform-neutral foreground-window blocklist matching."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app import config
from app.platforms import PlatformAdapter, WindowInfo

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BlocklistResult:
    blocked: bool
    matched_term: str | None = None
    window: WindowInfo | None = None


class WindowWatcher:
    """Match configured terms against the active app and window title."""

    def __init__(
        self,
        platform_adapter: PlatformAdapter,
        blocked_terms: Sequence[str] = config.BLOCKED_APPS,
    ) -> None:
        self._platform = platform_adapter
        self._blocked_terms = tuple(
            term.strip() for term in blocked_terms if term.strip()
        )

    def check(self) -> BlocklistResult:
        if not self._blocked_terms:
            return BlocklistResult(blocked=False)

        try:
            window = self._platform.get_foreground_window()
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
