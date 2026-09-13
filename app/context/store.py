"""Thread-safe, short-lived foreground context for the protection loop."""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import Lock

from app.context.browser_registry import BrowserDefinition
from app.context.models import (
    ApplicationContext,
    ForegroundContext,
    WebsiteContext,
    WebsiteContextState,
)
from app.context.website.normalization import normalize_hostname


class ForegroundContextStore:
    def __init__(
        self,
        *,
        website_ttl: float = 1.5,
        application_ttl: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if website_ttl <= 0 or application_ttl <= 0:
            raise ValueError("context TTLs must be positive")
        self._website_ttl = website_ttl
        self._application_ttl = application_ttl
        self._clock = clock
        self._lock = Lock()
        self._context: ForegroundContext | None = None
        self._foreground_key: (
            tuple[str | None, int | None, str | None, str | None, bool] | None
        ) = None
        self._generation = 0

    def observe_application(
        self,
        application: ApplicationContext,
        browser: BrowserDefinition | None,
        *,
        suppress_website: bool = False,
    ) -> int:
        """Invalidate the old site immediately when foreground identity changes."""

        now = self._clock()
        key = (
            application.identifier.casefold() if application.identifier else None,
            application.process_id,
            application.window_id,
            browser.family if browser else None,
            suppress_website and browser is not None,
        )
        with self._lock:
            changed = key != self._foreground_key
            if changed:
                self._generation += 1
                self._foreground_key = key
            website = None
            if browser is not None:
                website = (
                    _unknown_website(browser.family, now)
                    if (
                        changed
                        or suppress_website
                        or self._context is None
                        or self._context.website is None
                    )
                    else self._fresh_website(self._context.website, now)
                )
            self._context = ForegroundContext(application, browser is not None, website, now)
            return self._generation

    def publish_website(self, generation: int, website: WebsiteContext) -> bool:
        """Discard results from a browser that is no longer foreground."""

        now = self._clock()
        with self._lock:
            current = self._context
            if (
                generation != self._generation
                or current is None
                or not current.is_browser
                or current.website is None
                or (self._foreground_key is not None and self._foreground_key[4])
                or now - current.captured_at >= self._application_ttl
            ):
                return False
            hostname = (
                normalize_hostname(website.hostname)
                if (
                    website.state is WebsiteContextState.KNOWN
                    and 0 <= now - website.captured_at < self._website_ttl
                )
                else None
            )
            updated = WebsiteContext(
                state=(WebsiteContextState.KNOWN if hostname else WebsiteContextState.UNKNOWN),
                browser=current.website.browser,
                hostname=hostname,
                source=website.source if hostname else None,
                captured_at=website.captured_at if hostname else now,
            )
            self._context = ForegroundContext(
                current.application,
                True,
                updated,
                current.captured_at,
            )
            return True

    def latest(self) -> ForegroundContext | None:
        """Return a fresh snapshot without calling a platform or accessibility API."""

        now = self._clock()
        with self._lock:
            current = self._context
            if current is None:
                return current
            if now - current.captured_at >= self._application_ttl:
                self._generation += 1
                self._foreground_key = None
                unidentified = ApplicationContext(None, None, None, None, now)
                self._context = ForegroundContext(unidentified, False, None, now)
                return self._context
            if current.website is None:
                return current
            website = self._fresh_website(current.website, now)
            if website is not current.website:
                current = ForegroundContext(
                    current.application,
                    current.is_browser,
                    website,
                    current.captured_at,
                )
                self._context = current
            return current

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._foreground_key = None
            self._context = None

    def _fresh_website(self, website: WebsiteContext, now: float) -> WebsiteContext:
        if (
            website.state is WebsiteContextState.KNOWN
            and now - website.captured_at >= self._website_ttl
        ):
            return _unknown_website(website.browser, now)
        return website


def _unknown_website(browser: str | None, captured_at: float) -> WebsiteContext:
    return WebsiteContext(WebsiteContextState.UNKNOWN, browser, None, None, captured_at)
