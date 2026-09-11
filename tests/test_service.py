"""Tests for the LAVOCADO monitoring state machine."""

import unittest
from concurrent.futures import Future

from app.intervention.recorder import ProtectionEvent
from app.service import LavocadoService, State
from app.vision.temporal import TemporalVerifier


class FakeCapturer:
    def __init__(self, monitor_indexes: tuple[int, ...] = (1,)) -> None:
        self.monitor_indexes = monitor_indexes
        self.grabbed_indexes: list[int] = []
        self.closed = False

    def grab(self, monitor_index: int) -> int:
        self.grabbed_indexes.append(monitor_index)
        return monitor_index

    def close(self) -> None:
        self.closed = True


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


class ServiceTests(unittest.TestCase):
    def test_blocks_after_two_candidate_frames_in_three_checks(self) -> None:
        current_time = [0.0]
        capturer = FakeCapturer()
        overlay = FakeOverlay()
        recorder = FakeRecorder()
        intervention = FakeIntervention()
        service = LavocadoService(
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

    def test_cooldown_temporarily_skips_capture(self) -> None:
        current_time = [0.0]
        capturer = FakeCapturer()
        service = LavocadoService(
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


if __name__ == "__main__":
    unittest.main()
