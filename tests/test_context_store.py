"""Foreground cache must never preserve a stale website bypass."""

import unittest

from app.context.browser_registry import BrowserDefinition
from app.context.models import (
    ApplicationContext,
    ApplicationRule,
    ContextPolicyAction,
    WebsiteContext,
    WebsiteContextState,
    WebsiteMatchMode,
    WebsiteRule,
)
from app.context.policy.application import ApplicationPolicy
from app.context.policy.resolver import ContextPolicyService
from app.context.policy.website import WebsitePolicy
from app.context.store import ForegroundContextStore


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def application(identifier="chrome.exe", window_id="one", process_id=42):
    return ApplicationContext(identifier, identifier, identifier, window_id, 0.0, process_id)


def known(hostname="trusted.example"):
    return WebsiteContext(WebsiteContextState.KNOWN, "chromium", hostname, "uia", 0.0)


BROWSER = BrowserDefinition("chrome.exe", "chromium")


class ContextStoreTests(unittest.TestCase):
    def test_known_site_expires_to_unknown_and_website_policy_becomes_normal(self) -> None:
        clock = Clock()
        store = ForegroundContextStore(clock=clock, website_ttl=1.5)
        generation = store.observe_application(application(), BROWSER)
        self.assertTrue(store.publish_website(generation, known()))
        policy = ContextPolicyService(website=WebsitePolicy([
            WebsiteRule("trusted.example", ContextPolicyAction.FULL_BYPASS,
                        WebsiteMatchMode.EXACT_HOST)
        ]))

        self.assertEqual(policy.evaluate(store.latest()).action, ContextPolicyAction.FULL_BYPASS)
        clock.now = 1.5
        expired = store.latest()
        self.assertEqual(expired.website.state, WebsiteContextState.UNKNOWN)
        self.assertIsNone(expired.website.hostname)
        self.assertIsNone(expired.website.source)
        self.assertEqual(policy.evaluate(expired).action, ContextPolicyAction.NORMAL)

    def test_app_policy_still_applies_when_website_is_unknown(self) -> None:
        clock = Clock()
        store = ForegroundContextStore(clock=clock)
        store.observe_application(application(), BROWSER)
        policy = ContextPolicyService(application=ApplicationPolicy([
            ApplicationRule("chrome.exe", ContextPolicyAction.FULL_BYPASS)
        ]))

        self.assertEqual(store.latest().website.state, WebsiteContextState.UNKNOWN)
        self.assertEqual(policy.evaluate(store.latest()).action, ContextPolicyAction.FULL_BYPASS)

    def test_window_or_process_change_invalidates_old_site_and_result(self) -> None:
        clock = Clock()
        store = ForegroundContextStore(clock=clock)
        first = store.observe_application(application(), BROWSER)
        store.publish_website(first, known())
        second = store.observe_application(application(window_id="two"), BROWSER)

        self.assertNotEqual(first, second)
        self.assertEqual(store.latest().website.state, WebsiteContextState.UNKNOWN)
        self.assertFalse(store.publish_website(first, known("old.example")))
        self.assertIsNone(store.latest().website.hostname)

        third = store.observe_application(application(window_id="two", process_id=43), BROWSER)
        self.assertNotEqual(second, third)

    def test_app_change_discards_website_even_when_reader_finishes_late(self) -> None:
        store = ForegroundContextStore(clock=Clock())
        first = store.observe_application(application(), BROWSER)
        store.observe_application(application("steam.exe"), None)

        self.assertFalse(store.publish_website(first, known()))
        self.assertFalse(store.latest().is_browser)
        self.assertIsNone(store.latest().website)

    def test_stale_application_loses_whitelist_instead_of_bypassing_vision(self) -> None:
        clock = Clock()
        store = ForegroundContextStore(clock=clock, application_ttl=2.0)
        store.observe_application(application(), BROWSER)
        clock.now = 2.0

        context = store.latest()

        self.assertIsNone(context.application.identifier)
        self.assertFalse(context.is_browser)
        self.assertIsNone(context.website)

    def test_store_keeps_only_hostname_and_rejects_invalid_ttls(self) -> None:
        store = ForegroundContextStore(clock=Clock())
        generation = store.observe_application(application(), BROWSER)
        store.publish_website(generation, known("https://trusted.example/private?q=secret"))

        self.assertEqual(store.latest().website.hostname, "trusted.example")
        self.assertNotIn("secret", repr(store.latest()))
        with self.assertRaises(ValueError):
            ForegroundContextStore(website_ttl=0)
        with self.assertRaises(ValueError):
            ForegroundContextStore(application_ttl=0)

    def test_slow_result_is_unknown_even_when_it_finishes_now(self) -> None:
        clock = Clock()
        store = ForegroundContextStore(clock=clock, application_ttl=5.0)
        generation = store.observe_application(application(), BROWSER)
        clock.now = 1.5

        self.assertTrue(store.publish_website(generation, known()))
        self.assertEqual(store.latest().website.state, WebsiteContextState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
