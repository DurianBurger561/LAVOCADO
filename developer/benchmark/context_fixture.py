"""Build benchmark context fixtures using the product policy contracts."""

from __future__ import annotations

from typing import Any

from app.context.models import (
    ApplicationContext,
    ApplicationRule,
    ContextPolicyAction,
    ForegroundContext,
    WebsiteContext,
    WebsiteContextState,
    WebsiteMatchMode,
    WebsiteRule,
)
from app.context.policy.application import ApplicationPolicy
from app.context.policy.resolver import ContextPolicyService
from app.context.policy.website import WebsitePolicy
from developer.benchmark.dataset import BenchmarkSample


def context_policy_for_sample(
    sample: BenchmarkSample,
) -> tuple[ContextPolicyService, ForegroundContext]:
    """Resolve an isolated, privacy-safe application/website test fixture."""

    fixture = sample.context_fixture or {}
    if not isinstance(fixture, dict):
        raise TypeError("Benchmark context_fixture must be an object")
    app_identifier = _optional_string(fixture.get("application_identifier"))
    hostname = _optional_string(fixture.get("website_hostname"))
    website_state = WebsiteContextState(
        fixture.get("website_state", WebsiteContextState.KNOWN.value)
    )
    is_browser = fixture.get("is_browser", hostname is not None)
    if not isinstance(is_browser, bool):
        raise TypeError("Benchmark is_browser must be a boolean")
    application = ApplicationContext(
        identifier=app_identifier,
        display_name=None,
        process_name=None,
        window_id=None,
        captured_at=0.0,
    )
    website = (
        WebsiteContext(
            state=website_state,
            browser=None,
            hostname=hostname,
            source="benchmark_fixture",
            captured_at=0.0,
        )
        if is_browser
        else None
    )
    context = ForegroundContext(
        application=application,
        is_browser=is_browser,
        website=website,
        captured_at=0.0,
    )
    application_rules = tuple(
        ApplicationRule(
            identifier=_required_string(rule, "identifier"),
            action=ContextPolicyAction(_required_string(rule, "action")),
            enabled=bool(rule.get("enabled", True)),
        )
        for rule in _rule_objects(fixture.get("application_rules", []))
    )
    website_rules = tuple(
        WebsiteRule(
            domain=_required_string(rule, "domain"),
            action=ContextPolicyAction(_required_string(rule, "action")),
            match_mode=WebsiteMatchMode(
                rule.get("match_mode", WebsiteMatchMode.EXACT_HOST.value)
            ),
            enabled=bool(rule.get("enabled", True)),
        )
        for rule in _rule_objects(fixture.get("website_rules", []))
    )
    policy = ContextPolicyService(
        application=ApplicationPolicy(application_rules),
        website=WebsitePolicy(website_rules),
    )
    return policy, context


def _rule_objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Benchmark context rules must be a list of objects")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Benchmark context identifiers must be strings")
    return value.strip() or None


def _required_string(rule: dict[str, Any], name: str) -> str:
    value = _optional_string(rule.get(name))
    if value is None:
        raise ValueError(f"Benchmark context rule requires {name}")
    return value
