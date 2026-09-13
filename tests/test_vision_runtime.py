"""Context Policy gates Vision. Missing context still runs Vision."""

import unittest

from app.context.models import ContextPolicyAction
from app.context.store import ForegroundContextStore
from app.vision.decision import VisualDecisionEngine
from app.vision.nudenet_adapter import NudeNetAdapter
from app.vision.runtime import VisionSession, allows_vision
from app.vision.temporal import EvidenceAccumulator, TemporalEngine
from app.service import LavocadoService, State
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

    def test_architecture_aliases_keep_layer_names(self) -> None:
        from app.vision.decision import DecisionEngine
        from app.vision.temporal import TemporalVerifier

        self.assertIs(VisualDecisionEngine, DecisionEngine)
        self.assertIs(TemporalEngine, TemporalVerifier)

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

    def test_vision_session_skips_pipeline_while_bypassed(self) -> None:
        class Pipeline:
            def __init__(self) -> None:
                self.evaluate_calls = 0
                self.reset_count = 0

            def evaluate(self, _frame: object, *, monitor_index: int = 1) -> dict[str, object]:
                self.evaluate_calls += 1
                return {"blocked": True, "monitor_index": monitor_index}

            def reset(self) -> None:
                self.reset_count += 1

        session = VisionSession(Pipeline())  # type: ignore[arg-type]
        session.enter_bypass()
        result = session.evaluate(object())

        self.assertEqual(result["source"], "full_bypass")
        self.assertFalse(result["blocked"])
        self.assertEqual(session.pipeline.evaluate_calls, 0)
        session.exit_bypass_if_needed()
        self.assertGreaterEqual(session.pipeline.reset_count, 2)

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
