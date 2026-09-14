"""Executable acceptance for context-first visual protection."""

import inspect
import unittest

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
from app.context.policy.resolver import ContextPolicyService, allows_vision
from app.context.policy.website import WebsitePolicy
from app.context.store import ForegroundContextStore
from app.service import LavocadoService, State
from app.vision.decision import DecisionEngine
from app.vision.visual_decision import VisualDecisionEngine
from developer.benchmark.ground_truth import visual_policy_classification
from developer.benchmark.ranking_metrics import ranking_quality
from tests.test_decision import (
    FakeContextClassifier,
    FakeLocalDetector,
    empty_result,
    rescue_frame,
)
from tests.test_service import (
    FakeCapturer,
    FakeDetector,
    FakeIntervention,
    FakeOverlay,
    FakePlatform,
    FakeRecorder,
)
from tests.test_service_context_policy import (
    application,
    policy,
    store_for,
)

MEDICAL_ANATOMY = [
    {
        "class": "FEMALE_GENITALIA_EXPOSED",
        "score": 0.81,
        "box": [0, 0, 10, 10],
    }
]


class ContextFirstAcceptanceTests(unittest.TestCase):
    def test_context_policy_precedes_vision_on_blacklist(self) -> None:
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

        self.assertFalse(allows_vision(ContextPolicyAction.FORCE_BLOCK))
        self.assertEqual(service.vision_pipeline.evaluate_calls, 0)
        self.assertEqual(detector.checked_indexes, [])

    def test_whitelist_skips_hidden_vision(self) -> None:
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
        self.assertEqual(service.vision_pipeline.evaluate_calls, 0)
        self.assertEqual(overlay.shown_on, [])
        self.assertEqual(service.state, State.BYPASSED)

    def test_unknown_website_is_normal_and_runs_vision(self) -> None:
        detector = FakeDetector({1: [False]})
        store = store_for(application())
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=detector,
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            context_store=store,
            context_policy=policy(),
        )

        service.check_once()

        self.assertTrue(allows_vision(ContextPolicyAction.NORMAL))
        self.assertGreater(service.vision_pipeline.evaluate_calls, 0)
        self.assertEqual(detector.checked_indexes, [1])

    def test_blacklist_beats_whitelist(self) -> None:
        context = ForegroundContext(
            ApplicationContext("chrome.exe", "Chrome", "chrome.exe", "1", 0.0),
            True,
            WebsiteContext(
                WebsiteContextState.KNOWN, "chromium", "blocked.example", "test", 0.0
            ),
            0.0,
        )
        result = ContextPolicyService(
            ApplicationPolicy(
                [ApplicationRule("chrome.exe", ContextPolicyAction.FULL_BYPASS)]
            ),
            WebsitePolicy(
                [WebsiteRule(
                    "blocked.example",
                    ContextPolicyAction.FORCE_BLOCK,
                    WebsiteMatchMode.EXACT_HOST,
                )]
            ),
        ).evaluate(context)

        self.assertEqual(result.action, ContextPolicyAction.FORCE_BLOCK)

    def test_context_policy_does_not_take_pixels(self) -> None:
        parameters = inspect.signature(ContextPolicyService.evaluate).parameters
        self.assertEqual(tuple(parameters), ("self", "context"))

    def test_visual_decision_engine_is_pure_and_separate(self) -> None:
        self.assertIsNot(VisualDecisionEngine, DecisionEngine)

    def test_viddexa_cannot_block_without_primary_evidence(self) -> None:
        result = DecisionEngine(
            FakeContextClassifier({"porn": 0.99}),
            FakeLocalDetector([False]),
        ).evaluate(empty_result(), rescue_frame())
        ranking = ranking_quality([
            {"index": 0, "scores": {"porn": 0.99}, "primary_hit": False},
        ])

        from app.vision.violation_policy import VisualViolationClassification

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIsNone(ranking["product_block"])

    def test_medical_anatomy_remains_a_visual_violation(self) -> None:
        self.assertEqual(
            visual_policy_classification(MEDICAL_ANATOMY).value,
            "violation",
        )

    def test_missing_context_store_still_runs_vision(self) -> None:
        detector = FakeDetector({1: [False]})
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=detector,
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            context_store=ForegroundContextStore(clock=lambda: 0.0),
        )

        service.check_once()

        self.assertEqual(detector.checked_indexes, [1])


if __name__ == "__main__":
    unittest.main()
