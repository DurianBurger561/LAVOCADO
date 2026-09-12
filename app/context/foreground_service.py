"""Discover foreground context without making policy decisions."""

from __future__ import annotations

import time
from collections.abc import Callable

from app.context.browser_registry import BrowserRegistry
from app.context.models import (
    ApplicationContext,
    ForegroundContext,
    WebsiteContext,
    WebsiteContextState,
)
from app.context.website.normalization import normalize_hostname
from app.context.website.provider import WebsiteReader


class ForegroundContextService:
    def __init__(
        self,
        read_application: Callable[[], ApplicationContext | None],
        website_reader: WebsiteReader,
        *,
        browser_registry: BrowserRegistry | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._read_application = read_application
        self._website_reader = website_reader
        self._browser_registry = browser_registry or BrowserRegistry()
        self._clock = clock

    def discover(self) -> ForegroundContext:
        """Read a fresh application, then a site only for a supported browser.

        Reader errors are intentionally discarded: exceptions from accessibility
        APIs may contain an address value, which must not be logged or retained.
        """

        captured_at = self._clock()
        try:
            application = self._read_application()
        except Exception:
            application = None
        if application is None:
            application = ApplicationContext(None, None, None, None, captured_at)

        browser = self._browser_registry.identify(application)
        if browser is None:
            return ForegroundContext(application, False, None, captured_at)

        hostname = None
        try:
            hostname = normalize_hostname(
                self._website_reader.read_active_hostname(application, browser)
            )
        except Exception:
            pass
        website = WebsiteContext(
            state=(
                WebsiteContextState.KNOWN
                if hostname is not None
                else WebsiteContextState.UNKNOWN
            ),
            browser=browser.family,
            hostname=hostname,
            source=None,
            captured_at=captured_at,
        )
        return ForegroundContext(application, True, website, captured_at)
