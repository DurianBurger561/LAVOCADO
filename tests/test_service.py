"""Tests for the LAVOCADO monitoring state machine."""

import unittest
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Event

from app.blocklist.watcher import BlocklistResult, WindowInfo
from app.intervention.recorder import ProtectionEvent
from app.service import LavocadoService, State
from app.vision.diagnostics import DiagnosticsStore
from app.vision.temporal import TemporalVerifier


@dataclass(frozen=True)
class FakeCapturedFrame:
    original_frame: int
    model_frame: int


class FakePlatform:
    def get_foreground_window(self) -> None:
        return None


class FakeCapturer:
    def __init__(
        self,
        monitor_indexes: tuple[int, ...] = (1,),
        point_monitor_index: int | None = 1,
    ) -> None:
        self.monitor_indexes = monitor_indexes
        self.point_monitor_index = point_monitor_index
        self.grabbed_indexes: list[int] = []
        self.closed = False

    def grab(self, monitor_index: int) -> FakeCapturedFrame:
        self.grabbed_indexes.append(monitor_index)
        return FakeCapturedFrame(
            original_frame=monitor_index,
            model_frame=monitor_index,
        )

    def close(self) -> None:
        self.closed = True

    def monitor_index_at(self, _x: int, _y: int) -> int | None:
        return self.point_monitor_index


class FakeDetector:
    def __init__(self, results_by_monitor: dict[int, list[bool]]) -> None:
        self._results_by_monitor = {
            monitor_index: iter(results)
            for monitor_index, results in results_by_monitor.items()
        }

    def check(self, monitor_index: int) -> dict[str, object]:
        blocked = next(self._results_by_monitor[monitor_index])
        return {
            "blocked": blocked,
            "reason": "test" if blocked else "",
            "label": "TEST" if blocked else None,
            "confidence": 1.0 if blocked else 0.0,
            "check_points": [],
        }


class FakeOverlay:
    def __init__(self) -> None:
        self.shown_on: list[int] = []
        self.support_messages: list[Future[str] | None] = []

    def show(
        self,
        monitor_index: int,
        support_message: Future[str] | None = None,
    ) -> None:
        self.shown_on.append(monitor_index)
        self.support_messages.append(support_message)


class FakeRecorder:
    def __init__(self) -> None:
        self.events: list[ProtectionEvent] = []
        self.shown_event_ids: list[int] = []
        self.closed = False

    def record_async(self, event: ProtectionEvent) -> Future[int]:
        self.events.append(event)
        future: Future[int] = Future()
        future.set_result(len(self.events))
        return future

    def mark_intervention_shown(self, event_id: int) -> None:
        self.shown_event_ids.append(event_id)

    def close(self) -> None:
        self.closed = True


class PendingRecorder(FakeRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.future: Future[int] = Future()

    def record_async(self, event: ProtectionEvent) -> Future[int]:
        self.events.append(event)
        return self.future


class FakeIntervention:
    def __init__(self) -> None:
        self.generate_count = 0
        self.closed = False

    def generate_async(self) -> Future[str]:
        self.generate_count += 1
        future: Future[str] = Future()
        future.set_result("Support message")
        return future

    def close(self) -> None:
        self.closed = True


class FakeWatcher:
    def __init__(self, result: BlocklistResult) -> None:
        self.result = result

    def check(self) -> BlocklistResult:
        return self.result


class FakeDecisionEngine:
    def __init__(self) -> None:
        self.original_frames: list[int] = []

    def evaluate(
        self,
        result: dict[str, object],
        captured: FakeCapturedFrame,
        *,
        monitor_index: int,
    ) -> dict[str, object]:
        del monitor_index
        self.original_frames.append(captured.original_frame)
        return result


class SequenceDecisionEngine:
    def __init__(self, candidates: list[bool]) -> None:
        self._candidates = iter(candidates)

    def evaluate(
        self,
        result: dict[str, object],
        _captured: FakeCapturedFrame,
        *,
        monitor_index: int,
    ) -> dict[str, object]:
        del monitor_index
        candidate = next(self._candidates)
        promoted = dict(result)
        promoted.update(
            {
                "blocked": candidate,
                "label": "FUSED" if candidate else None,
                "confidence": 0.60 if candidate else 0.0,
            }
        )
        return promoted


class ServiceTests(unittest.TestCase):
    def test_updates_in_memory_diagnostics_after_scan(self) -> None:
        scan_times = iter((10.0, 10.123))
        diagnostics = DiagnosticsStore(
            model_variant="test",
            inference_resolution=640,
            context_model="test-context",
            context_status="unavailable",
        )
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [True]}),
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            diagnostics=diagnostics,
            scan_clock=lambda: next(scan_times),
        )

        service.check_once()

        snapshot = diagnostics.snapshot()
        self.assertEqual(snapshot["protection_state"], "CANDIDATE")
        self.assertEqual(snapshot["last_scan_ms"], 123.0)
        self.assertEqual(snapshot["monitor_index"], 1)
        self.assertEqual(snapshot["temporal"], [1])

    def test_passes_full_capture_to_decision_engine(self) -> None:
        decision_engine = FakeDecisionEngine()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [False]}),
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            decision_engine=decision_engine,
        )

        service.check_once()

        self.assertEqual(decision_engine.original_frames, [1])

    def test_fused_candidates_still_require_two_hits_in_three_frames(self) -> None:
        overlay = FakeOverlay()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [False, False, False]}),
            overlay=overlay,
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            decision_engine=SequenceDecisionEngine([True, False, True]),
            verifier_factory=lambda: TemporalVerifier(3, 2),
        )

        service.check_once()
        service.check_once()
        self.assertEqual(overlay.shown_on, [])

        service.check_once()

        self.assertEqual(overlay.shown_on, [1])

    def test_blocks_after_two_candidate_frames_in_three_checks(self) -> None:
        current_time = [0.0]
        capturer = FakeCapturer()
        overlay = FakeOverlay()
        recorder = FakeRecorder()
        intervention = FakeIntervention()
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=FakeDetector({1: [False, True, True]}),
            overlay=overlay,
            recorder=recorder,
            intervention=intervention,
            verifier_factory=lambda: TemporalVerifier(3, 2),
            cooldown_seconds=8.0,
            clock=lambda: current_time[0],
        )

        service.check_once()
        service.check_once()
        self.assertEqual(service.state, State.CANDIDATE)

        service.check_once()

        self.assertEqual(overlay.shown_on, [1])
        self.assertEqual(service.state, State.COOLDOWN)
        self.assertEqual(capturer.grabbed_indexes, [1, 1, 1])
        self.assertEqual(len(recorder.events), 1)
        self.assertEqual(recorder.events[0].label, "TEST")
        self.assertEqual(recorder.events[0].monitor_index, 1)
        self.assertEqual(recorder.shown_event_ids, [1])
        self.assertEqual(intervention.generate_count, 1)
        self.assertEqual(overlay.support_messages[0].result(), "Support message")

    def test_intervention_does_not_wait_for_event_recording(self) -> None:
        current_time = [0.0]
        recorder = PendingRecorder()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [True, True]}),
            overlay=FakeOverlay(),
            recorder=recorder,
            intervention=FakeIntervention(),
            verifier_factory=lambda: TemporalVerifier(2, 2),
            cooldown_seconds=8.0,
            clock=lambda: current_time[0],
        )

        service.check_once()
        service.check_once()

        self.assertEqual(service.state, State.COOLDOWN)
        self.assertEqual(recorder.shown_event_ids, [])

        recorder.future.set_result(1)

        self.assertEqual(recorder.shown_event_ids, [1])

    def test_cooldown_temporarily_skips_capture(self) -> None:
        current_time = [0.0]
        capturer = FakeCapturer()
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=FakeDetector({1: [False, True, True, False]}),
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            intervention=FakeIntervention(),
            verifier_factory=lambda: TemporalVerifier(3, 2),
            cooldown_seconds=8.0,
            clock=lambda: current_time[0],
        )

        service.check_once()
        service.check_once()
        service.check_once()

        current_time[0] = 7.9
        self.assertIsNone(service.check_once())
        self.assertEqual(capturer.grabbed_indexes, [1, 1, 1])

        current_time[0] = 8.1
        service.check_once()
        self.assertEqual(capturer.grabbed_indexes, [1, 1, 1, 1])
        self.assertEqual(service.state, State.MONITORING)

    def test_only_overlays_the_monitor_that_confirmed_risk(self) -> None:
        capturer = FakeCapturer(monitor_indexes=(1, 2, 3))
        overlay = FakeOverlay()
        recorder = FakeRecorder()
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=FakeDetector(
                {
                    1: [False, False, False],
                    2: [False, False, False],
                    3: [False, True, True],
                }
            ),
            overlay=overlay,
            recorder=recorder,
            intervention=FakeIntervention(),
            verifier_factory=lambda: TemporalVerifier(3, 2),
        )

        service.check_once()
        service.check_once()
        service.check_once()

        self.assertEqual(overlay.shown_on, [3])
        self.assertEqual([event.monitor_index for event in recorder.events], [3])
        self.assertEqual(
            capturer.grabbed_indexes,
            [1, 2, 3, 1, 2, 3, 1, 2, 3],
        )

    def test_start_closes_capture_and_recorder(self) -> None:
        capturer = FakeCapturer()
        recorder = FakeRecorder()
        intervention = FakeIntervention()
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=FakeDetector({1: [False]}),
            overlay=FakeOverlay(),
            recorder=recorder,
            intervention=intervention,
            sleeper=lambda _: service.stop(),
        )

        service.start()

        self.assertTrue(capturer.closed)
        self.assertTrue(recorder.closed)
        self.assertTrue(intervention.closed)
        self.assertEqual(service.state, State.STOPPED)

    def test_manual_intervention_runs_on_service_loop_without_recording(self) -> None:
        overlay = FakeOverlay()
        recorder = FakeRecorder()
        test_event = Event()
        test_event.set()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [False]}),
            overlay=overlay,
            recorder=recorder,
            intervention=FakeIntervention(),
            sleeper=lambda _: service.stop(),
        )

        service.start(test_intervention_event=test_event)

        self.assertEqual(overlay.shown_on, [1])
        self.assertEqual(recorder.events, [])
        self.assertFalse(test_event.is_set())

    def test_blocklist_match_immediately_blocks_the_window_monitor(self) -> None:
        capturer = FakeCapturer(
            monitor_indexes=(1, 2),
            point_monitor_index=2,
        )
        overlay = FakeOverlay()
        recorder = FakeRecorder()
        intervention = FakeIntervention()
        watcher = FakeWatcher(
            BlocklistResult(
                blocked=True,
                matched_term="blocked.example",
                window=WindowInfo(
                    title="blocked.example - Browser",
                    left=2000,
                    top=100,
                    width=1000,
                    height=800,
                ),
            )
        )
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=FakeDetector({1: [], 2: []}),
            overlay=overlay,
            recorder=recorder,
            intervention=intervention,
            watcher=watcher,
        )

        result = service.check_once()

        self.assertEqual(capturer.grabbed_indexes, [])
        self.assertEqual(overlay.shown_on, [2])
        self.assertEqual(result[0]["label"], "blocked.example")
        self.assertEqual(recorder.events[0].trigger_type, "blocklist")
        self.assertIsNone(recorder.events[0].confidence)
        self.assertEqual(intervention.generate_count, 1)


if __name__ == "__main__":
    unittest.main()
