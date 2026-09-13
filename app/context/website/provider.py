"""Native website reader contract; adapters must never publish full URLs."""

from __future__ import annotations

from typing import Protocol

from app.context.browser_registry import BrowserDefinition
from app.context.models import ApplicationContext


class WebsiteReader(Protocol):
    def read_active_hostname(
        self,
        application: ApplicationContext,
        browser: BrowserDefinition,
    ) -> str | None:
        """Return a hostname only, or None when unavailable/unknown."""

