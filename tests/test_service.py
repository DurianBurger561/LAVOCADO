"""Tests for the LAVOCADO monitoring state machine."""

import unittest
from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.diagnostics import DiagnosticsStore
from app.intervention.recorder import ProtectionEvent
from app.platforms.capture import CaptureBackendStatus, CaptureFrame, MonitorInfo, Rect
from app.service import LavocadoService, State
from app.ui.api import DashboardAPI
from app.vision.change_scheduler import ChangeDecision
from app.vision.primary_detector_set import PrimaryDetection
from app.vision.scheduler import ScanPlan
from app.vision.temporal import TemporalVerifier
from app.vision.viddexa_ranker import ViddexaRanker
from app.vision.violation_policy import (
    ViolationEvidence,
    ViolationEvidenceType,
    VisualViolationClassification,
    VisualViolationDecision,
)


class FakePlatform:
    name = "Windows"

    def default_data_dir(self) -> Path:
        return Path(__file__).parent / "_nonexistent_data"

    def get_foreground_application(self) -> None:
        return None

    def create_website_reader(self) -> object:
        return object()

    def get_foreground_window(self) -> None:
        return None


class SettingsPlatform(FakePlatform):
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def default_data_dir(self) -> Path:
        return self.directory


class FakeCapturer:
    def __init__(
        self,
        monitor_indexes: tuple[int, ...] = (1,),
        point_monitor_index: int | None = 1,
        sequences: dict[int, list[int]] | None = None,
    ) -> None:
        self.monitor_indexes = monitor_indexes
        self.point_monitor_index = point_monitor_index
        self.grabbed_indexes: list[int] = []
        self.closed = False
        self._sequences = {
            monitor_index: iter(values)
            for monitor_index, values in (sequences or {}).items()
        }
        self._sequence_counts: dict[int, int] = {}

    def grab(self, monitor_index: int) -> CaptureFrame:
        self.grabbed_indexes.append(monitor_index)
        sequence_source = self._sequences.get(monitor_index)
        if sequence_source is None:
            sequence = self._sequence_counts.get(monitor_index, 0) + 1
            self._sequence_counts[monitor_index] = sequence
        else:
            sequence = next(sequence_source)
        return CaptureFrame(
            image=np.full((8, 8, 3), monitor_index, dtype=np.uint8),
            monitor_id=str(monitor_index),
            sequence=sequence,
            changed_regions=(Rect(0, 0, 8, 8),),
            backend="fake",
        )

    def close(self) -> None:
        self.closed = True

    @property
    def status(self) -> CaptureBackendStatus:
        return CaptureBackendStatus(
            preferred_backend="fake-native",
            active_backend=None if self.closed else "fake-native",
            fallback=False,
            fallback_reason=None,
            healthy=not self.closed,
            monitor_count=len(self.monitor_indexes),
            frame_age_ms=4.2,
        )

    def monitor_index_at(self, _x: int, _y: int) -> int | None:
        return self.point_monitor_index

    def monitor_for_index(self, monitor_index: int | None = None) -> MonitorInfo:
        selected = self.monitor_indexes[0] if monitor_index is None else monitor_index
        if selected not in self.monitor_indexes:
            raise ValueError(f"Monitor {selected} is unavailable")
        return MonitorInfo(
            id=f"display-{selected}",
            index=selected,
            left=(selected - 1) * 100,
            top=0,
            width=100,
            height=80,
            is_primary=selected == self.monitor_indexes[0],
        )


class FakeDetector:
    def __init__(self, results_by_monitor: dict[int, list[bool]]) -> None:
        self.checked_indexes: list[int] = []
        self._results_by_monitor = {
            monitor_index: iter(results)
            for monitor_index, results in results_by_monitor.items()
        }

    def detect(self, prepared: object) -> tuple[ViolationEvidence, ...]:
        image = prepared.image
        frame_sequence = prepared.frame_sequence
        if not isinstance(image, np.ndarray) or image.shape != (8, 8, 3):
            return ()
        monitor_index = int(image[0, 0, 0])
        self.checked_indexes.append(monitor_index)
        blocked = next(self._results_by_monitor[monitor_index])
        if not blocked:
            return ()
        return (
            ViolationEvidence(
                evidence_type=ViolationEvidenceType.BREAST_EXPOSURE,
                label="FEMALE_BREAST_EXPOSED",
                confidence=1.0,
                bbox=None,
                model="nudenet_640m",
                frame_sequence=frame_sequence,
            ),
        )


class FakeChangeScheduler:
    def __init__(self, scan_results: list[bool]) -> None:
        self._scan_results = iter(scan_results)
        self.candidates: list[tuple[int, bool]] = []
        self.reset_count = 0

    def should_scan(
        self,
        _captured: CaptureFrame,
        _monitor_index: int,
        *,
        vision_allowed: bool = True,
    ) -> ChangeDecision:
        if not vision_allowed:
            return ChangeDecision(False, "policy_skip", 0.0)
        return ChangeDecision(next(self._scan_results), "fake", 0.0)

    def record_candidate(self, monitor_index: int, is_candidate: bool) -> None:
        self.candidates.append((monitor_index, is_candidate))

    def request_focused_verification(self, monitor_index: int) -> None:
        self.candidates.append((monitor_index, True))

    def reset(self) -> None:
        self.reset_count += 1


class FakeOverlay:
    def __init__(self) -> None:
        self.shown_on: list[int] = []
        self.shown_monitors: list[MonitorInfo] = []
        self.closed = False

    def show(
        self,
        monitor: MonitorInfo,
    ) -> None:
        self.shown_on.append(monitor.index)
        self.shown_monitors.append(monitor)

    def close(self) -> None:
        self.closed = True


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

    def mark_intervention_shown_async(self, event_id: int) -> Future[None]:
        self.mark_intervention_shown(event_id)
        future: Future[None] = Future()
        future.set_result(None)
        return future

    def close(self) -> None:
        self.closed = True


class PendingRecorder(FakeRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.future: Future[int] = Future()

    def record_async(self, event: ProtectionEvent) -> Future[int]:
        self.events.append(event)
        return self.future


def _scan_plan() -> ScanPlan:
    return ScanPlan(
        mode="monitoring",
        run_full=True,
        tile_indexes=(),
        roi=None,
        subdivide=False,
        input_size=640,
        interval_ms=0,
    )


def _decision_from_detection(
    result: PrimaryDetection,
    *,
    monitor_index: int = 1,
    frame_sequence: int = 1,
    candidate: bool | None = None,
) -> VisualViolationDecision:
    selected = result.primary[0] if result.primary else None
    is_candidate = selected is not None if candidate is None else candidate
    return VisualViolationDecision(
        classification=(
            VisualViolationClassification.VIOLATION
            if is_candidate
            else VisualViolationClassification.CLEAR
        ),
        evidence=(),
        reason_codes=(),
        primary_region=None,
        frame_sequence=frame_sequence,
        label=(
            "FUSED"
            if candidate is True
            else selected.label
            if selected is not None and is_candidate
            else None
        ),
        confidence=(
            0.60
            if candidate is True
            else selected.confidence
            if selected is not None and is_candidate
            else 0.0
        ),
        monitor_index=monitor_index,
    )


class FakeDecisionEngine:
    def __init__(self) -> None:
        self.scan_planner = self
        self.viddexa_ranker = ViddexaRanker(None)
        self.original_frames: list[int] = []
        self.prepared_for_scan: object | None = None
        self.prepared_for_evaluation: object | None = None

    def evaluate(
        self,
        result: PrimaryDetection,
        captured: CaptureFrame,
        *,
        monitor_index: int,
        scan_plan: object | None = None,
        is_active_monitor: bool = True,
        prepared_frame: object | None = None,
    ) -> VisualViolationDecision:
        del scan_plan, is_active_monitor
        self.prepared_for_evaluation = prepared_frame
        self.original_frames.append(int(captured.image[0, 0, 0]))
        return _decision_from_detection(
            result,
            monitor_index=monitor_index,
            frame_sequence=captured.sequence,
        )

    def prepare_scan(
        self,
        _captured: CaptureFrame,
        _monitor_index: int,
        *,
        is_active_monitor: bool = True,
        prepared_frame: object | None = None,
    ) -> ScanPlan:
        del is_active_monitor
        self.prepared_for_scan = prepared_frame
        return _scan_plan()

    def rescue_status(self, _monitor_index: int) -> dict[str, int | None]:
        return {}

    def reset(self) -> None:
        return None


class SequenceDecisionEngine:
    def __init__(self, candidates: list[bool]) -> None:
        self.scan_planner = self
        self.viddexa_ranker = ViddexaRanker(None)
        self._candidates = iter(candidates)

    def evaluate(
        self,
        result: PrimaryDetection,
        captured: CaptureFrame,
        *,
        monitor_index: int,
        scan_plan: object | None = None,
        is_active_monitor: bool = True,
        prepared_frame: object | None = None,
    ) -> VisualViolationDecision:
        del scan_plan, is_active_monitor, prepared_frame
        candidate = next(self._candidates)
        return _decision_from_detection(
            result,
            monitor_index=monitor_index,
            frame_sequence=captured.sequence,
            candidate=candidate,
        )

    def prepare_scan(
        self,
        _captured: CaptureFrame,
        _monitor_index: int,
        *,
        is_active_monitor: bool = True,
        prepared_frame: object | None = None,
    ) -> ScanPlan:
        del is_active_monitor, prepared_frame
        return _scan_plan()

    def rescue_status(self, _monitor_index: int) -> dict[str, int | None]:
        return {}

    def reset(self) -> None:
        return None


class ServiceTests(unittest.TestCase):
    def test_dashboard_primary_setting_controls_next_protection_start(self) -> None:
        for primary, model_path in (
            ("nudenet_640m", "/unused/yolo.pt"),
            ("yolo11_nsfw_small", ""),
        ):
            with self.subTest(primary=primary), TemporaryDirectory() as temporary:
                data_dir = Path(temporary)
                api = DashboardAPI(None, None, data_dir=data_dir)
                saved = api.save_vision_settings(
                    {"detector": {"primary": primary}, "context": {"model": "off"}}
                )
                self.assertTrue(saved["ok"])
                self.assertEqual(saved["settings"]["primary_detector"], primary)
                self.assertEqual(
                    saved["settings"]["yolo"]["requested"],
                    primary == "yolo11_nsfw_small",
                )

                bundle = SimpleNamespace(
                    primary=FakeDetector({1: [False]}),
                    yolo_status="disabled",
                )
                with (
                    patch.dict(
                        "os.environ",
                        {
                            "LAVOCADO_YOLO_MODEL": model_path,
                            "LAVOCADO_PRIMARY_DETECTOR": "nudenet_640m",
                        },
                    ),
                    patch("app.service.load_primary_bundle", return_value=bundle) as load,
                ):
                    service = LavocadoService(
                        SettingsPlatform(data_dir),
                        capturer=FakeCapturer(),
                        overlay=FakeOverlay(),
                        recorder=FakeRecorder(),
                        decision_engine=FakeDecisionEngine(),
                        diagnostics=DiagnosticsStore(
                            model_variant="test",
                            inference_resolution=640,
                            context_model="off",
                            context_status="disabled",
                        ),
                    )

                self.assertEqual(service.vision_settings.detector.primary, primary)
                self.assertIs(service.detector, bundle.primary)
                self.assertEqual(load.call_args.args[0], primary)

    def test_dashboard_scan_and_temporal_settings_reach_runtime_components(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            saved = DashboardAPI(None, None, data_dir=data_dir).save_vision_settings(
                {
                    "context": {"model": "off"},
                    "scan": {
                        "normal_interval_ms": 1000,
                        "candidate_interval_ms": 250,
                        "adaptive": False,
                        "change_sensitivity": 0.05,
                        "vision_budget_ms": 150,
                        "periodic_scan_interval": 12,
                    },
                    "ui": {"cooldown_seconds": 11.5},
                    "temporal": {"window_size": 5, "min_fresh_hits": 3},
                    "tiles": {"rows": 3, "columns": 3, "max_skip": 5},
                    "recheck": {"proposal_margin": 0.20},
                }
            )
            self.assertTrue(saved["ok"])
            bundle = SimpleNamespace(
                primary=FakeDetector({1: [False]}), yolo_status="disabled"
            )
            with patch("app.service.load_primary_bundle", return_value=bundle):
                service = LavocadoService(
                    SettingsPlatform(data_dir),
                    capturer=FakeCapturer(),
                    overlay=FakeOverlay(),
                    recorder=FakeRecorder(),
                    diagnostics=DiagnosticsStore(
                        model_variant="test",
                        inference_resolution=640,
                        context_model="off",
                        context_status="disabled",
                    ),
                )

            self.assertEqual(service.check_interval, 1.0)
            self.assertEqual(service._next_interval(), 1.0)
            service._transition(State.CANDIDATE)
            self.assertEqual(service._next_interval(), 0.25)
            self.assertFalse(service.change_scheduler.adaptive)
            self.assertEqual(service.change_scheduler.change_ratio_threshold, 0.05)
            self.assertEqual(service.change_scheduler.periodic_scan_interval, 12)
            self.assertEqual(service.cooldown_seconds, 11.5)
            self.assertEqual(service.change_scheduler.candidate_followup_checks, 4)
            self.assertEqual(service.decision_engine.scheduler.pin_followup_checks, 4)
            self.assertEqual(service.decision_engine.scheduler.tile_spec.rows, 3)
            self.assertEqual(service.decision_engine.scheduler.max_skip, 5)
            self.assertEqual(service.decision_engine.borderline_margin, 0.20)
            verifier = service._verifier_factory()
            self.assertEqual(verifier._window_size, 5)
            self.assertEqual(verifier._required_hits, 3)

    def test_disabled_context_ranking_does_not_load_context_model(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            saved = DashboardAPI(None, None, data_dir=data_dir).save_vision_settings(
                {"context": {"model": "viddexa_mini", "tile_ranking": False}}
            )
            self.assertTrue(saved["ok"])
            self.assertFalse(saved["settings"]["context_model"]["enabled"])
            bundle = SimpleNamespace(
                primary=FakeDetector({1: [False]}), yolo_status="disabled"
            )
            with (
                patch("app.service.load_primary_bundle", return_value=bundle),
                patch("app.service.load_context_ranker") as load_context,
            ):
                service = LavocadoService(
                    SettingsPlatform(data_dir),
                    capturer=FakeCapturer(),
                    overlay=FakeOverlay(),
                    recorder=FakeRecorder(),
                    diagnostics=DiagnosticsStore(
                        model_variant="test",
                        inference_resolution=640,
                        context_model="off",
                        context_status="disabled",
                    ),
                )

            load_context.assert_not_called()
            self.assertIsNone(service.decision_engine.viddexa_ranker.classifier)

    def test_change_scheduler_skips_detector_until_scan_is_due(self) -> None:
        detector = FakeDetector({1: [False]})
        scheduler = FakeChangeScheduler([False, True])
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=detector,
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            change_scheduler=scheduler,
        )

        self.assertEqual(service.check_once(), [])
        self.assertEqual(detector.checked_indexes, [])

        service.check_once()

        self.assertEqual(detector.checked_indexes, [1])
        self.assertEqual(scheduler.candidates, [(1, False)])

    def test_duplicate_capture_sequence_does_not_advance_temporal(self) -> None:
        overlay = FakeOverlay()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(sequences={1: [7, 7, 8, 9]}),
            detector=FakeDetector({1: [True, True, False]}),
            overlay=overlay,
            recorder=FakeRecorder(),
            verifier_factory=lambda: TemporalVerifier(3, 2),
        )

        service.check_once()
        duplicate_results = service.check_once()

        self.assertEqual(duplicate_results, [])
        self.assertEqual(service.state, State.CANDIDATE)
        self.assertEqual(overlay.shown_on, [])

        service.check_once()

        self.assertEqual(overlay.shown_on, [])

        service.check_once()

        self.assertEqual(overlay.shown_on, [1])

    def test_older_capture_sequence_is_dropped_without_backlog(self) -> None:
        detector = FakeDetector({1: [False, False]})
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(sequences={1: [7, 6, 8]}),
            detector=detector,
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            change_scheduler=FakeChangeScheduler([True, True]),
        )

        service.check_once()
        self.assertEqual(service.check_once(), [])
        service.check_once()
        self.assertEqual(detector.checked_indexes, [1, 1])

    def test_runtime_clears_frame_identity_only_at_context_boundary(self) -> None:
        detector = FakeDetector({1: [False, False]})
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(sequences={1: [7, 7, 7]}),
            detector=detector,
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            change_scheduler=FakeChangeScheduler([True, True]),
        )

        service.check_once()
        service.runtime.reset_vision()
        service.check_once()
        self.assertEqual(detector.checked_indexes, [1])

        service.runtime.reset_for_context_boundary()
        service.check_once()
        self.assertEqual(detector.checked_indexes, [1, 1])

    def test_updates_in_memory_diagnostics_after_scan(self) -> None:
        scan_times = iter((10.0, 10.100, 10.101, 10.123))
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
            diagnostics=diagnostics,
            scan_clock=lambda: next(scan_times),
        )

        service.check_once()

        snapshot = diagnostics.snapshot().to_dict()
        self.assertEqual(snapshot["protection_state"], "CANDIDATE")
        self.assertEqual(snapshot["last_scan_ms"], 123.0)
        self.assertEqual(snapshot["monitor_index"], 1)
        self.assertEqual(snapshot["temporal"], [1])
        self.assertEqual(snapshot["capture"]["preferred_backend"], "fake-native")
        self.assertEqual(snapshot["capture"]["active_backend"], "fake-native")
        self.assertEqual(snapshot["capture"]["monitor_count"], 1)
        self.assertEqual(snapshot["capture"]["frame_age_ms"], 4.2)
        self.assertEqual(snapshot["latencies"]["temporal_ms"], 1.0)
        self.assertIsNone(snapshot["latencies"]["confirmation_ms"])

    def test_confirmation_latency_uses_fresh_frames_on_one_monitor(self) -> None:
        scan_times = iter((1.0, 1.050, 1.051, 1.070, 1.200, 1.250, 1.251, 1.270))
        diagnostics = DiagnosticsStore(
            model_variant="test", inference_resolution=640,
            context_model="off", context_status="disabled",
        )
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [True, True]}),
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            diagnostics=diagnostics,
            verifier_factory=lambda: TemporalVerifier(2, 2),
            scan_clock=lambda: next(scan_times),
        )

        service.check_once()
        self.assertIsNone(diagnostics.snapshot().latencies["confirmation_ms"])
        service.check_once()

        self.assertAlmostEqual(
            diagnostics.snapshot().latencies["confirmation_ms"], 251.0
        )

    def test_passes_full_capture_to_decision_engine(self) -> None:
        decision_engine = FakeDecisionEngine()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [False]}),
            overlay=FakeOverlay(),
            recorder=FakeRecorder(),
            decision_engine=decision_engine,
        )

        service.check_once()

        self.assertEqual(decision_engine.original_frames, [1])
        self.assertIs(
            decision_engine.prepared_for_scan,
            decision_engine.prepared_for_evaluation,
        )

    def test_fused_candidates_still_require_two_hits_in_three_frames(self) -> None:
        overlay = FakeOverlay()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [False, False, False]}),
            overlay=overlay,
            recorder=FakeRecorder(),
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
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=FakeDetector({1: [False, True, True]}),
            overlay=overlay,
            recorder=recorder,
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
        self.assertEqual(recorder.events[0].label, "FEMALE_BREAST_EXPOSED")
        self.assertEqual(recorder.events[0].monitor_index, 1)
        self.assertEqual(recorder.shown_event_ids, [1])

    def test_intervention_does_not_wait_for_event_recording(self) -> None:
        current_time = [0.0]
        recorder = PendingRecorder()
        service = LavocadoService(
            FakePlatform(),
            capturer=FakeCapturer(),
            detector=FakeDetector({1: [True, True]}),
            overlay=FakeOverlay(),
            recorder=recorder,
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
            verifier_factory=lambda: TemporalVerifier(3, 2),
        )

        service.check_once()
        service.check_once()
        service.check_once()

        self.assertEqual(overlay.shown_on, [3])
        self.assertEqual(
            overlay.shown_monitors,
            [capturer.monitor_for_index(3)],
        )
        self.assertEqual([event.monitor_index for event in recorder.events], [3])
        self.assertEqual(
            capturer.grabbed_indexes,
            [1, 2, 3, 1, 2, 3, 1, 2, 3],
        )

    def test_start_closes_capture_and_recorder(self) -> None:
        capturer = FakeCapturer()
        overlay = FakeOverlay()
        recorder = FakeRecorder()
        service = LavocadoService(
            FakePlatform(),
            capturer=capturer,
            detector=FakeDetector({1: [False]}),
            overlay=overlay,
            recorder=recorder,
            sleeper=lambda _: service.stop(),
        )

        service.start()

        self.assertTrue(capturer.closed)
        self.assertTrue(overlay.closed)
        self.assertTrue(recorder.closed)
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
            sleeper=lambda _: service.stop(),
        )

        service.start(test_intervention_event=test_event)

        self.assertEqual(overlay.shown_on, [1])
        self.assertEqual(recorder.events, [])
        self.assertFalse(test_event.is_set())


if __name__ == "__main__":
    unittest.main()
