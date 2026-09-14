"""Context Policy gates Vision. Missing context still runs Vision."""

import unittest

from app.context.models import ContextPolicyAction
from app.context.policy.resolver import allows_vision
from app.context.store import ForegroundContextStore
from app.service import LavocadoService, State
from app.vision.nudenet_adapter import NudeNetAdapter
from app.vision.temporal import EvidenceAccumulator
from app.vision.visual_decision import VisualDecisionEngine
from tests.test_service import (
    FakeCapturer,
    FakeDetector,
    FakeIntervention,
    FakeOverlay,
    FakePlatform,
    FakeRecorder,
)


class VisionRuntimeTests(unittest.TestCase):
    def test_only_normal_and_missing_context_allow_vision(self) -> None:
        self.assertTrue(allows_vision(None))
        self.assertTrue(allows_vision(ContextPolicyAction.NORMAL))
        self.assertFalse(allows_vision(ContextPolicyAction.FORCE_BLOCK))
        self.assertFalse(allows_vision(ContextPolicyAction.FULL_BYPASS))

    def test_visual_decision_and_orchestration_are_distinct(self) -> None:
        from app.vision.decision import DecisionEngine

        self.assertIsNot(VisualDecisionEngine, DecisionEngine)

    def test_nudenet_adapter_emits_shared_evidence(self) -> None:
        evidence = NudeNetAdapter().detect_evidence(
            [{"class": "ANUS_EXPOSED", "score": 0.7, "box": [1, 2, 3, 4]}]
        )

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].label, "ANUS_EXPOSED")

    def test_evidence_accumulator_decays_visual_types_not_purpose(self) -> None:
        accumulator = EvidenceAccumulator(3)
        accumulator.add("sexual_act")
        accumulator.decay()
        accumulator.decay()

        self.assertEqual(accumulator.history(), ("sexual_act", None, None))

    def test_missing_context_still_runs_vision(self) -> None:
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
        self.assertGreater(service.vision_pipeline.evaluate_calls, 0)
        self.assertEqual(service.state, State.MONITORING)


if __name__ == "__main__":
    unittest.main()
