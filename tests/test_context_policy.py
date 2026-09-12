"""Global priority and exact-identifier/domain-boundary policy regressions."""

import unittest

from app.context.models import (
    ApplicationContext,
    ApplicationRule,
    ContextPolicyAction as Action,
    ForegroundContext,
    WebsiteContext,
    WebsiteContextState,
    WebsiteMatchMode,
    WebsiteRule,
)
from app.context.policy.application import ApplicationPolicy
from app.context.policy.resolver import ContextPolicyService, resolve_context_policy
from app.context.policy.website import WebsitePolicy


def foreground(
    identifier: str | None = "chrome.exe",
    hostname: str | None = "github.com",
    *,
    is_browser: bool = True,
    website_state: WebsiteContextState = WebsiteContextState.KNOWN,
) -> ForegroundContext:
    return ForegroundContext(
        application=ApplicationContext(identifier, "Chrome", "chrome.exe", "123", 10.0),
        is_browser=is_browser,
        website=(
            WebsiteContext(website_state, "chromium", hostname, "uia", 10.0)
            if is_browser
            else None
        ),
        captured_at=10.0,
    )


def app_rule(identifier: str, action: Action, enabled: bool = True) -> ApplicationRule:
    return ApplicationRule(identifier, action, enabled)


def site_rule(
    domain: str,
    action: Action,
    mode: WebsiteMatchMode = WebsiteMatchMode.DOMAIN_AND_SUBDOMAINS,
    enabled: bool = True,
) -> WebsiteRule:
    return WebsiteRule(domain, action, mode, enabled)


class ContextPolicyTests(unittest.TestCase):
    def test_global_priority_is_independent_of_action_order(self) -> None:
        cases = (
            (Action.NORMAL, None, Action.NORMAL),
            (Action.NORMAL, Action.FULL_BYPASS, Action.FULL_BYPASS),
            (Action.FULL_BYPASS, Action.NORMAL, Action.FULL_BYPASS),
            (Action.FULL_BYPASS, Action.FORCE_BLOCK, Action.FORCE_BLOCK),
            (Action.FORCE_BLOCK, Action.FULL_BYPASS, Action.FORCE_BLOCK),
        )
        for application, website, expected in cases:
            with self.subTest(application=application, website=website):
                self.assertEqual(resolve_context_policy(application, website), expected)

    def test_app_whitelist_does_not_hide_website_blacklist(self) -> None:
        service = ContextPolicyService(
            ApplicationPolicy([app_rule("CHROME.EXE", Action.FULL_BYPASS)]),
            WebsitePolicy([site_rule("blocked.example", Action.FORCE_BLOCK)]),
        )

        result = service.evaluate(foreground(hostname="blocked.example"))

        self.assertEqual(result.app_action, Action.FULL_BYPASS)
        self.assertEqual(result.website_action, Action.FORCE_BLOCK)
        self.assertEqual(result.action, Action.FORCE_BLOCK)
        self.assertIsNotNone(result.matched_application_rule)
        self.assertIsNotNone(result.matched_website_rule)

    def test_app_blacklist_wins_over_website_whitelist(self) -> None:
        service = ContextPolicyService(
            ApplicationPolicy([app_rule("chrome.exe", Action.FORCE_BLOCK)]),
            WebsitePolicy([site_rule("trusted.example", Action.FULL_BYPASS)]),
        )
        result = service.evaluate(foreground(hostname="trusted.example"))
        self.assertEqual(result.website_action, Action.FULL_BYPASS)
        self.assertEqual(result.action, Action.FORCE_BLOCK)

    def test_unknown_website_does_not_cancel_explicit_app_whitelist(self) -> None:
        service = ContextPolicyService(
            ApplicationPolicy([app_rule("chrome.exe", Action.FULL_BYPASS)]),
            WebsitePolicy([site_rule("trusted.example", Action.FORCE_BLOCK)]),
        )
        result = service.evaluate(
            foreground(hostname="trusted.example", website_state=WebsiteContextState.UNKNOWN)
        )
        self.assertEqual(result.website_action, Action.NORMAL)
        self.assertEqual(result.action, Action.FULL_BYPASS)

    def test_unrecognized_website_keeps_normal_vision_policy(self) -> None:
        service = ContextPolicyService(
            website=WebsitePolicy([site_rule("trusted.example", Action.FULL_BYPASS)])
        )
        result = service.evaluate(foreground(hostname=None, website_state=WebsiteContextState.UNKNOWN))
        self.assertEqual(result.action, Action.NORMAL)

    def test_non_browser_only_evaluates_application(self) -> None:
        service = ContextPolicyService(
            ApplicationPolicy([app_rule("steam.exe", Action.FULL_BYPASS)]),
            WebsitePolicy([site_rule("blocked.example", Action.FORCE_BLOCK)]),
        )
        result = service.evaluate(foreground("steam.exe", is_browser=False))
        self.assertEqual(result.action, Action.FULL_BYPASS)
        self.assertEqual(result.website_action, Action.NORMAL)

    def test_no_rules_preserves_normal_behavior(self) -> None:
        self.assertEqual(ContextPolicyService().evaluate(foreground()).action, Action.NORMAL)

    def test_application_match_uses_identifier_not_name_or_title(self) -> None:
        policy = ApplicationPolicy([app_rule("steam.exe", Action.FORCE_BLOCK)])
        context = ApplicationContext("other.exe", "Steam", "steam.exe", None, 10.0)
        self.assertEqual(policy.evaluate(context), Action.NORMAL)
        self.assertEqual(policy.evaluate(ApplicationContext(None, "Steam", None, None, 10.0)), Action.NORMAL)

    def test_conflicting_or_disabled_application_rules(self) -> None:
        policy = ApplicationPolicy([
            app_rule("chrome.exe", Action.FULL_BYPASS),
            app_rule("chrome.exe", Action.FORCE_BLOCK, enabled=False),
            app_rule("chrome.exe", Action.FORCE_BLOCK),
        ])
        self.assertEqual(policy.evaluate(foreground().application), Action.FORCE_BLOCK)

    def test_exact_host_and_domain_boundary(self) -> None:
        exact = WebsitePolicy([site_rule("www.example.com", Action.FORCE_BLOCK, WebsiteMatchMode.EXACT_HOST)])
        subtree = WebsitePolicy([site_rule("example.com", Action.FULL_BYPASS)])

        self.assertEqual(exact.evaluate(foreground(hostname="WWW.EXAMPLE.COM").website), Action.FORCE_BLOCK)
        self.assertEqual(exact.evaluate(foreground(hostname="a.www.example.com").website), Action.NORMAL)
        for host in ("example.com", "a.b.example.com", "EXAMPLE.COM."):
            with self.subTest(host=host):
                self.assertEqual(subtree.evaluate(foreground(hostname=host).website), Action.FULL_BYPASS)
        for host in ("fakeexample.com", "example.com.evil.test"):
            with self.subTest(host=host):
                self.assertEqual(subtree.evaluate(foreground(hostname=host).website), Action.NORMAL)

    def test_conflicting_or_disabled_website_rules(self) -> None:
        policy = WebsitePolicy([
            site_rule("example.com", Action.FULL_BYPASS),
            site_rule("example.com", Action.FORCE_BLOCK, enabled=False),
            site_rule("a.example.com", Action.FORCE_BLOCK),
        ])
        self.assertEqual(policy.evaluate(foreground(hostname="a.example.com").website), Action.FORCE_BLOCK)
        self.assertEqual(policy.evaluate(foreground(hostname="b.example.com").website), Action.FULL_BYPASS)


if __name__ == "__main__":
    unittest.main()
