"""Context policy gates vision without changing the existing intervention path."""

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
from app.service import LavocadoService, State
from app.vision.temporal import TemporalVerifier
from tests.test_service import (
    FakeCapturer,
    FakeChangeScheduler,
    FakeDetector,
    FakeIntervention,
    FakeOverlay,
    FakePlatform,
    FakeRecorder,
)

BROWSER = BrowserDefinition("chrome.exe", "chromium")


def application(identifier="chrome.exe", window_id="one"):
    return ApplicationContext(
        identifier,
        identifier,
        identifier,
        window_id,
        0.0,
        42,
        (2500, 500),
    )


def store_for(app, hostname=None):
    store = ForegroundContextStore(clock=lambda: 0.0)
    browser = BROWSER if app.identifier == "chrome.exe" else None
    generation = store.observe_application(app, browser)
    if hostname is not None:
        store.publish_website(
            generation,
            WebsiteContext(WebsiteContextState.KNOWN, "chromium", hostname, "test", 0.0),
        )
    return store


def policy(*, application_rules=(), website_rules=()):
    return ContextPolicyService(
        application=ApplicationPolicy(application_rules),
        website=WebsitePolicy(website_rules),
    )


class FakeContextWorker:
    def __init__(self):
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


class ContextPlatform(FakePlatform):
    def __init__(self, website_value):
        self.website_value = website_value
        self.website_reads = 0

    def get_foreground_application(self):
        return application()

    def create_website_reader(self):
        platform = self

        class Reader:
            source = "test"

            def read_active_hostname(self, _application, _browser):
                platform.website_reads += 1
                return platform.website_value

        return Reader()


class ServiceContextPolicyTests(unittest.TestCase):
    def test_default_worker_skips_site_for_application_force_block(self) -> None:
        platform = ContextPlatform("https://private.example/path")
        recorder = FakeRecorder()
        service = LavocadoService(
            platform,
            capturer=FakeCapturer(),
            detector=FakeDetector({1: []}),
            overlay=FakeOverlay(),
            recorder=recorder,
            intervention=FakeIntervention(),
            context_policy=policy(application_rules=[
                ApplicationRule("chrome.exe", ContextPolicyAction.FORCE_BLOCK)
            ]),
        )

        service.context_worker.poll_once()
        self.assertFalse(service.context_worker.read_pending_once())
        service.check_once()

        self.assertEqual(platform.website_reads, 0)
        self.assertEqual(recorder.events[0].trigger_type, "application_rule")

    def test_default_worker_reads_site_despite_browser_whitelist(self) -> None:
        platform = ContextPlatform("https://blocked.example/private?q=secret")
        recorder = FakeRecorder()
        service = LavocadoService(
            platform,
            capturer=FakeCapturer(),
            detector=FakeDetector({1: []}),
            overlay=FakeOverlay(),
            recorder=recorder,
            intervention=FakeIntervention(),
            context_policy=policy(
                application_rules=[ApplicationRule(
                    "chrome.exe", ContextPolicyAction.FULL_BYPASS
                )],
                website_rules=[WebsiteRule(
                    "blocked.example", ContextPolicyAction.FORCE_BLOCK,
                    WebsiteMatchMode.EXACT_HOST,
                )],
            ),
        )

        service.context_worker.poll_once()
        self.assertTrue(service.context_worker.read_pending_once())
        service.check_once()

        self.assertEqual(platform.website_reads, 1)
        self.assertEqual(recorder.events[0].trigger_type, "website_rule")
        self.assertIsNone(recorder.events[0].label)

    def test_website_blacklist_overrides_browser_whitelist_before_vision(self) -> None:
        capturer = FakeCapturer(monitor_indexes=(1, 2), point_monitor_index=2)
        detector = FakeDetector({1: [], 2: []})
        recorder = FakeRecorder()
        overlay = FakeOverlay()
        store = store_for(application(), "blocked.example")
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=detector,
            overlay=overlay,
            recorder=recorder,
            intervention=FakeIntervention(),
            context_store=store,
            context_policy=policy(
                application_rules=[ApplicationRule("chrome.exe", ContextPolicyAction.FULL_BYPASS)],
                website_rules=[WebsiteRule(
                    "blocked.example", ContextPolicyAction.FORCE_BLOCK,
                    WebsiteMatchMode.EXACT_HOST,
                )],
            ),
        )

        results = service.check_once()

        self.assertEqual(capturer.grabbed_indexes, [])
        self.assertEqual(detector.checked_indexes, [])
        self.assertEqual(overlay.shown_on, [2])
        self.assertEqual(recorder.events[0].trigger_type, "website_rule")
        self.assertIsNone(recorder.events[0].label)
        self.assertEqual(results[0]["monitor_index"], 2)
        self.assertEqual(service.diagnostics.snapshot()["foreground_context"], {
            "application_available": True,
            "is_browser": True,
            "website_state": "known",
            "application_rule": "full_bypass",
            "website_rule": "force_block",
            "effective_policy": "force_block",
        })

    def test_application_blacklist_blocks_without_a_known_website(self) -> None:
        recorder = FakeRecorder()
        detector = FakeDetector({1: []})
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=detector,
            overlay=FakeOverlay(),
            recorder=recorder,
            intervention=FakeIntervention(),
            context_store=store_for(application()),
            context_policy=policy(application_rules=[
                ApplicationRule("chrome.exe", ContextPolicyAction.FORCE_BLOCK)
            ]),
        )

        service.check_once()

        self.assertEqual(detector.checked_indexes, [])
        self.assertEqual(recorder.events[0].trigger_type, "application_rule")
        self.assertIsNone(recorder.events[0].label)

    def test_website_event_never_records_rule_url_path_or_query(self) -> None:
        recorder = FakeRecorder()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: []}),
            overlay=FakeOverlay(),
            recorder=recorder,
            intervention=FakeIntervention(),
            context_store=store_for(application(), "blocked.example"),
            context_policy=policy(website_rules=[WebsiteRule(
                "https://blocked.example/private?q=secret",
                ContextPolicyAction.FORCE_BLOCK,
                WebsiteMatchMode.EXACT_HOST,
            )]),
        )

        service.check_once()

        self.assertIsNone(recorder.events[0].label)
        self.assertNotIn("blocked.example", repr(recorder.events[0]))
        self.assertNotIn("secret", repr(recorder.events[0]))

    def test_bypass_enter_stay_exit_resets_temporal_and_capture_baseline(self) -> None:
        store = store_for(application())
        scheduler = FakeChangeScheduler([True, True, True, True])
        detector = FakeDetector({1: [True, True, True, True]})
        capturer = FakeCapturer(sequences={1: [7, 7, 8, 9]})
        overlay = FakeOverlay()
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=detector,
            overlay=overlay,
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            change_scheduler=scheduler,
            context_store=store,
            context_policy=policy(website_rules=[WebsiteRule(
                "trusted.example", ContextPolicyAction.FULL_BYPASS,
                WebsiteMatchMode.EXACT_HOST,
            )]),
            verifier_factory=lambda: TemporalVerifier(3, 2),
        )

        service.check_once()
        self.assertEqual(service.state, State.CANDIDATE)
        generation = store.observe_application(application(), BROWSER)
        store.publish_website(generation, WebsiteContext(
            WebsiteContextState.KNOWN, "chromium", "trusted.example", "test", 0.0
        ))

        self.assertEqual(service.check_once(), [])
        self.assertEqual(service.state, State.BYPASSED)
        self.assertEqual(scheduler.reset_count, 1)
        self.assertEqual(service.check_once(), [])
        self.assertEqual(scheduler.reset_count, 1)
        self.assertEqual(capturer.grabbed_indexes, [1])

        store.observe_application(application("steam.exe"), None)
        service.check_once()
        self.assertEqual(detector.checked_indexes, [1, 1])
        self.assertEqual(overlay.shown_on, [])
        self.assertEqual(scheduler.reset_count, 2)
        service.check_once()
        self.assertEqual(overlay.shown_on, [])
        service.check_once()
        self.assertEqual(overlay.shown_on, [1])

    def test_unknown_website_does_not_cancel_application_whitelist(self) -> None:
        capturer = FakeCapturer()
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=FakeDetector({1: []}),
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            context_store=store_for(application()),
            context_policy=policy(application_rules=[
                ApplicationRule("chrome.exe", ContextPolicyAction.FULL_BYPASS)
            ]),
        )

        self.assertEqual(service.check_once(), [])
        self.assertEqual(service.state, State.BYPASSED)
        self.assertEqual(capturer.grabbed_indexes, [])
        self.assertEqual(
            service.diagnostics.snapshot()["foreground_context"]["effective_policy"],
            "full_bypass",
        )

    def test_manual_intervention_restores_bypassed_state(self) -> None:
        overlay = FakeOverlay()
        recorder = FakeRecorder()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: []}),
            overlay=overlay,
            recorder=recorder,
            intervention=FakeIntervention(),
            context_store=store_for(application()),
            context_policy=policy(application_rules=[
                ApplicationRule("chrome.exe", ContextPolicyAction.FULL_BYPASS)
            ]),
        )

        service.check_once()
        service.show_test_intervention()

        self.assertEqual(service.state, State.BYPASSED)
        self.assertEqual(overlay.shown_on, [1])
        self.assertEqual(recorder.events, [])

    def test_no_rules_preserve_existing_vision_protection(self) -> None:
        cases = (
            ("no_context", ForegroundContextStore(), {
                "application_available": False,
                "is_browser": None,
                "website_state": "unavailable",
            }),
            ("browser_known_unlisted_site", store_for(application(), "github.com"), {
                "application_available": True,
                "is_browser": True,
                "website_state": "known",
            }),
            ("browser_unknown_site", store_for(application()), {
                "application_available": True,
                "is_browser": True,
                "website_state": "unknown",
            }),
            ("non_browser", store_for(application("code.exe")), {
                "application_available": True,
                "is_browser": False,
                "website_state": "not_browser",
            }),
        )
        expected_foreground = {
            "application_rule": "normal",
            "website_rule": "normal",
            "effective_policy": "normal",
        }

        for name, store, availability in cases:
            with self.subTest(name):
                capturer = FakeCapturer(
                    monitor_indexes=(1, 2),
                    point_monitor_index=2,
                )
                detector = FakeDetector({
                    1: [False, True, True],
                    2: [False, False, False],
                })
                overlay = FakeOverlay()
                recorder = FakeRecorder()
                intervention = FakeIntervention()
                service = LavocadoService(
                    FakePlatform(),
                    capturer=capturer,
                    detector=detector,
                    overlay=overlay,
                    recorder=recorder,
                    intervention=intervention,
                    context_store=store,
                    context_policy=policy(),
                    verifier_factory=lambda: TemporalVerifier(3, 2),
                )

                service.check_once()
                service.check_once()
                self.assertEqual(service.state, State.CANDIDATE)
                self.assertEqual(overlay.shown_on, [])
                self.assertEqual(recorder.events, [])

                service.check_once()

                self.assertEqual(capturer.grabbed_indexes, [1, 2, 1, 2, 1])
                self.assertEqual(detector.checked_indexes, [1, 2, 1, 2, 1])
                self.assertEqual(overlay.shown_on, [1])
                self.assertEqual(service.state, State.COOLDOWN)
                self.assertEqual(recorder.events[0].trigger_type, "vision")
                self.assertEqual(recorder.events[0].label, "TEST")
                self.assertEqual(recorder.events[0].monitor_index, 1)
                self.assertEqual(recorder.shown_event_ids, [1])
                self.assertEqual(intervention.generate_count, 1)
                self.assertEqual(
                    service.diagnostics.snapshot()["foreground_context"],
                    {**availability, **expected_foreground},
                )

    def test_whitelisted_medical_site_skips_vision_despite_explicit_image(self) -> None:
        detector = FakeDetector({1: [True, True, True]})
        overlay = FakeOverlay()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=detector,
            overlay=overlay,
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            context_store=store_for(application(), "medical.example"),
            context_policy=policy(website_rules=[WebsiteRule(
                "medical.example", ContextPolicyAction.FULL_BYPASS,
                WebsiteMatchMode.EXACT_HOST,
            )]),
        )

        self.assertEqual(service.check_once(), [])

        self.assertEqual(detector.checked_indexes, [])
        self.assertEqual(service.vision_pipeline.evaluate_calls, 0)
        self.assertEqual(overlay.shown_on, [])
        self.assertEqual(service.state, State.BYPASSED)

    def test_website_blacklist_does_not_call_vision_pipeline(self) -> None:
        detector = FakeDetector({1: [True]})
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=detector,
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            context_store=store_for(application(), "blocked.example"),
            context_policy=policy(website_rules=[WebsiteRule(
                "blocked.example", ContextPolicyAction.FORCE_BLOCK,
                WebsiteMatchMode.EXACT_HOST,
            )]),
        )

        service.check_once()

        self.assertEqual(service.vision_pipeline.evaluate_calls, 0)
        self.assertEqual(detector.checked_indexes, [])

    def test_context_worker_starts_and_stops_with_protection_process(self) -> None:
        worker = FakeContextWorker()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [False]}),
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            context_worker=worker,
            sleeper=lambda _: service.stop(),
        )

        service.start()

        self.assertEqual((worker.starts, worker.stops), (1, 1))
        self.assertEqual(service.state, State.STOPPED)


if __name__ == "__main__":
    unittest.main()
