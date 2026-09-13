"""Platform-neutral context and policy data; no page content or full URLs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ContextPolicyAction(str, Enum):
    FORCE_BLOCK = "force_block"
    FULL_BYPASS = "full_bypass"
    NORMAL = "normal"


class WebsiteContextState(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class WebsiteMatchMode(str, Enum):
    EXACT_HOST = "exact_host"
    DOMAIN_AND_SUBDOMAINS = "domain_and_subdomains"


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    identifier: str | None
    display_name: str | None
    process_name: str | None
    window_id: str | None
    captured_at: float
    process_id: int | None = None
    window_center: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class WebsiteContext:
    state: WebsiteContextState
    browser: str | None
    hostname: str | None
    source: str | None
    captured_at: float


@dataclass(frozen=True, slots=True)
class ForegroundContext:
    application: ApplicationContext
    is_browser: bool
    website: WebsiteContext | None
    captured_at: float


@dataclass(frozen=True, slots=True)
class ApplicationRule:
    identifier: str
    action: ContextPolicyAction
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class WebsiteRule:
    domain: str
    action: ContextPolicyAction
    match_mode: WebsiteMatchMode
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ContextPolicyResult:
    action: ContextPolicyAction
    app_action: ContextPolicyAction
    website_action: ContextPolicyAction
    matched_application_rule: ApplicationRule | None = None
    matched_website_rule: WebsiteRule | None = None
