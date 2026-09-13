"""Discover foreground context without making policy decisions."""

from __future__ import annotations

import time
from collections.abc import Callable

from app.context.browser_registry import BrowserDefinition, BrowserRegistry
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

        application = self.read_application()
        browser = self.identify_browser(application)
        captured_at = self._clock()
        if browser is None:
            return ForegroundContext(application, False, None, captured_at)
        return ForegroundContext(
            application,
            True,
            self.read_website(application, browser),
            captured_at,
        )

    def read_application(self) -> ApplicationContext:
        """Return an unidentified application when foreground lookup fails."""

        try:
            application = self._read_application()
        except Exception:  # noqa: BLE001 - native errors may contain private text
            application = None
        if application is None:
            return ApplicationContext(None, None, None, None, self._clock())
        return application

    def identify_browser(self, application: ApplicationContext) -> BrowserDefinition | None:
        return self._browser_registry.identify(application)

    def read_website(
        self,
        application: ApplicationContext,
        browser: BrowserDefinition,
    ) -> WebsiteContext:
        """Read only a normalized hostname; do not retain native error text."""

        # Use the earliest possible observation time so a slow native read
        # cannot acquire a fresh TTL merely by finishing late.
        started_at = self._clock()
        hostname = None
        try:
            hostname = normalize_hostname(
                self._website_reader.read_active_hostname(application, browser)
            )
        except Exception:  # noqa: BLE001 - native errors may contain private URLs
            hostname = None
        return WebsiteContext(
            state=(
                WebsiteContextState.KNOWN
                if hostname is not None
                else WebsiteContextState.UNKNOWN
            ),
            browser=browser.family,
            hostname=hostname,
            source=(getattr(self._website_reader, "source", None) if hostname else None),
            captured_at=started_at,
        )
