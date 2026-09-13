"""Slow native website reads must not block foreground invalidation."""

import threading
import time
import unittest

from app.context.foreground_service import ForegroundContextService
from app.context.models import (
    ApplicationContext,
    ApplicationRule,
    ContextPolicyAction,
    WebsiteContextState,
    WebsiteMatchMode,
    WebsiteRule,
)
from app.context.policy.application import ApplicationPolicy
from app.context.policy.resolver import ContextPolicyService
from app.context.policy.website import WebsitePolicy
from app.context.store import ForegroundContextStore
from app.context.worker import ForegroundContextWorker


def application(identifier="chrome.exe", window_id="one"):
    return ApplicationContext(identifier, identifier, identifier, window_id, 0.0, 42)


class Reader:
    source = "test"

    def __init__(self, value="https://trusted.example/private"):
        self.value = value
        self.calls = 0

    def read_active_hostname(self, _application, _browser):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class ContextWorkerTests(unittest.TestCase):
    def test_poll_only_queues_browser_read_and_coalesces_requests(self) -> None:
        reader = Reader()
        service = ForegroundContextService(lambda: application(), reader)
        store = ForegroundContextStore()
        worker = ForegroundContextWorker(service, store)

        self.assertTrue(worker.poll_once())
        self.assertTrue(worker.poll_once())
        self.assertEqual(reader.calls, 0)
        self.assertEqual(store.latest().website.state, WebsiteContextState.UNKNOWN)
        self.assertTrue(worker.read_pending_once())
        self.assertFalse(worker.read_pending_once())
        self.assertEqual(reader.calls, 1)
        self.assertEqual(store.latest().website.hostname, "trusted.example")

    def test_nonbrowser_never_schedules_address_bar_read(self) -> None:
        reader = Reader()
        service = ForegroundContextService(lambda: application("steam.exe"), reader)
        store = ForegroundContextStore()
        worker = ForegroundContextWorker(service, store)

        worker.poll_once()

        self.assertFalse(worker.read_pending_once())
        self.assertEqual(reader.calls, 0)
        self.assertFalse(store.latest().is_browser)

    def test_app_force_block_never_queues_website_read(self) -> None:
        reader = Reader()
        service = ForegroundContextService(lambda: application(), reader)
        store = ForegroundContextStore()
        app_policy = ApplicationPolicy([
            ApplicationRule("chrome.exe", ContextPolicyAction.FORCE_BLOCK)
        ])
        worker = ForegroundContextWorker(
            service, store, application_policy=app_policy
        )

        worker.poll_once()

        self.assertFalse(worker.read_pending_once())
        self.assertEqual(reader.calls, 0)
        self.assertTrue(store.latest().is_browser)
        self.assertEqual(store.latest().website.state, WebsiteContextState.UNKNOWN)
        self.assertEqual(app_policy.evaluate(store.latest().application), ContextPolicyAction.FORCE_BLOCK)

    def test_app_bypass_still_reads_website_blacklist(self) -> None:
        reader = Reader("https://blocked.example/private?q=secret")
        service = ForegroundContextService(lambda: application(), reader)
        store = ForegroundContextStore()
        app_policy = ApplicationPolicy([
            ApplicationRule("chrome.exe", ContextPolicyAction.FULL_BYPASS)
        ])
        worker = ForegroundContextWorker(
            service, store, application_policy=app_policy
        )
        context_policy = ContextPolicyService(
            application=app_policy,
            website=WebsitePolicy([WebsiteRule(
                "blocked.example", ContextPolicyAction.FORCE_BLOCK,
                WebsiteMatchMode.EXACT_HOST,
            )]),
        )

        worker.poll_once()
        self.assertTrue(worker.read_pending_once())

        self.assertEqual(reader.calls, 1)
        self.assertEqual(store.latest().website.hostname, "blocked.example")
        self.assertEqual(context_policy.evaluate(store.latest()).action, ContextPolicyAction.FORCE_BLOCK)

    def test_native_error_is_unknown_without_retaining_private_url(self) -> None:
        reader = Reader(RuntimeError("https://private.example/secret"))
        service = ForegroundContextService(lambda: application(), reader)
        store = ForegroundContextStore()
        worker = ForegroundContextWorker(service, store)

        worker.poll_once()
        worker.read_pending_once()

        self.assertEqual(store.latest().website.state, WebsiteContextState.UNKNOWN)
        self.assertNotIn("private.example", repr(store.latest()))

    def test_slow_reader_does_not_block_switch_to_another_app(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        published = threading.Event()
        current = [application()]

        class ObservedStore(ForegroundContextStore):
            def publish_website(self, generation, website):
                result = super().publish_website(generation, website)
                published.set()
                return result

        class SlowReader(Reader):
            def read_active_hostname(self, _application, _browser):
                entered.set()
                release.wait(1.0)
                return "https://old.example/private"

        service = ForegroundContextService(lambda: current[0], SlowReader())
        store = ObservedStore()
        worker = ForegroundContextWorker(service, store, poll_interval=0.01)
        worker.start()
        try:
            self.assertTrue(entered.wait(1.0))
            self.assertEqual(store.latest().website.state, WebsiteContextState.UNKNOWN)
            current[0] = application("steam.exe")
            self.assertTrue(wait_until(lambda: store.latest().application.identifier == "steam.exe"))
            self.assertIsNone(store.latest().website)
            release.set()
            self.assertTrue(published.wait(1.0))
            self.assertFalse(store.latest().is_browser)
            self.assertIsNone(store.latest().website)
        finally:
            release.set()
            worker.stop()

        self.assertIsNone(store.latest())

    def test_invalid_poll_interval_and_stopped_worker(self) -> None:
        service = ForegroundContextService(lambda: application(), Reader())
        store = ForegroundContextStore()
        with self.assertRaises(ValueError):
            ForegroundContextWorker(service, store, poll_interval=0)
        worker = ForegroundContextWorker(service, store)
        worker.stop()
        self.assertFalse(worker.poll_once())
        with self.assertRaises(RuntimeError):
            worker.start()


if __name__ == "__main__":
    unittest.main()
