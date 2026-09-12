"""Identify supported browsers from stable application identifiers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.context.models import ApplicationContext


@dataclass(frozen=True, slots=True)
class BrowserDefinition:
    application_identifier: str
    family: str


DEFAULT_BROWSERS = (
    BrowserDefinition("chrome.exe", "chromium"),
    BrowserDefinition("chrome", "chromium"),
    BrowserDefinition("msedge.exe", "chromium"),
    BrowserDefinition("msedge", "chromium"),
    BrowserDefinition("brave.exe", "chromium"),
    BrowserDefinition("brave", "chromium"),
    BrowserDefinition("firefox.exe", "firefox"),
    BrowserDefinition("firefox", "firefox"),
    BrowserDefinition("com.google.chrome", "chromium"),
    BrowserDefinition("com.microsoft.edgemac", "chromium"),
    BrowserDefinition("com.brave.browser", "chromium"),
    BrowserDefinition("com.apple.safari", "safari"),
    BrowserDefinition("org.mozilla.firefox", "firefox"),
    BrowserDefinition("google-chrome", "chromium"),
    BrowserDefinition("google-chrome-stable", "chromium"),
    BrowserDefinition("chromium", "chromium"),
    BrowserDefinition("chromium-browser", "chromium"),
    BrowserDefinition("brave-browser", "chromium"),
    BrowserDefinition("microsoft-edge", "chromium"),
    BrowserDefinition("org.chromium.chromium", "chromium"),
)


class BrowserRegistry:
    def __init__(self, definitions: Iterable[BrowserDefinition] = DEFAULT_BROWSERS) -> None:
        self._by_identifier = {
            definition.application_identifier.casefold(): definition
            for definition in definitions
        }

    def identify(self, application: ApplicationContext) -> BrowserDefinition | None:
        """Do not infer browser identity from a mutable window title or app label."""

        if not application.identifier:
            return None
        return self._by_identifier.get(application.identifier.casefold())

    def is_supported_browser(self, application: ApplicationContext) -> bool:
        return self.identify(application) is not None

