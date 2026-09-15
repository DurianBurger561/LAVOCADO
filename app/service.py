"""Monitoring state machine for the LAVOCADO core."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timezone
from enum import Enum
from threading import Event

from app.context.foreground_service import ForegroundContextService
from app.context.models import (
    ContextPolicyAction,
    ContextPolicyResult,
    ForegroundContext,
)
from app.context.policy.resolver import ContextPolicyService, allows_vision
from app.context.store import ForegroundContextStore
from app.context.worker import ForegroundContextWorker
from app.diagnostics import DiagnosticsStore
from app.intervention.recorder import EventRecorder, ProtectionEvent
from app.platforms import PlatformAdapter
from app.protection_runtime import ProtectionRuntime
from app.settings.storage import load_vision_settings
from app.ui.overlay import OverlayBackend, create_overlay_backend
from app.vision.capture import Capturer
from app.vision.change_scheduler import ChangeScheduler
from app.vision.context.factory import load_context_ranker
from app.vision.decision import DecisionEngine
from app.vision.detectors.base import PrimaryDetector
from app.vision.detectors.factory import load_primary_bundle
from app.vision.model_lifecycle import compact_model_status, inspect_models
from app.vision.pipeline import VisionPipeline
from app.vision.temporal import TemporalVerifier
from app.vision.violation_policy import (
    ThresholdPolicy,
    VisualViolationDecision,
)
from app.vision.yolo_adapter import load_yolo_adapter

LOGGER = logging.getLogger(__name__)


class State(str, Enum):
    STOPPED = "stopped"
    MONITORING = "monitoring"
    CANDIDATE = "candidate"
    BYPASSED = "bypassed"
    BLOCKED = "blocked"
    COOLDOWN = "cooldown"


class LavocadoService:
    """Coordinate capture, detection, confirmation, and intervention."""

    def __init__(
        self,
        platform_adapter: PlatformAdapter,
        capturer: Capturer | None = None,
        detector: PrimaryDetector | None = None,
        overlay: OverlayBackend | None = None,
        recorder: EventRecorder | None = None,
        decision_engine: DecisionEngine | None = None,
        diagnostics: DiagnosticsStore | None = None,
        change_scheduler: ChangeScheduler | None = None,
        *,
        context_store: ForegroundContextStore | None = None,
        context_policy: ContextPolicyService | None = None,
        context_worker: ForegroundContextWorker | None = None,
        verifier_factory: Callable[[], TemporalVerifier] | None = None,
        check_interval: float | None = None,
        cooldown_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        scan_clock: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.platform_adapter = platform_adapter
        data_dir = platform_adapter.default_data_dir()
        self.vision_settings = load_vision_settings(data_dir)
        uses_default_detector = detector is None
        yolo_adapter = None
        shadow_adapter = None
        yolo_status = "disabled"
        if uses_default_detector:
            bundle = load_primary_bundle(
                self.vision_settings.detector.primary,
                full_input_size=self.vision_settings.detector.full_input_size,
                data_dir=data_dir,
            )
            self.detector = bundle.primary
            yolo_status = bundle.yolo_status
            if self.vision_settings.shadow.enabled:
                shadow_adapter = load_yolo_adapter(enabled=True, data_dir=data_dir)
        else:
            assert detector is not None
            self.detector = detector
        self.capturer = (
            capturer
            if capturer is not None
            else Capturer(
                platform_adapter,
                monitor_index=self.vision_settings.capture.monitor_index,
            )
        )
        if decision_engine is not None:
            self.decision_engine = decision_engine
        else:
            use_context_ranking = (
                self.vision_settings.context.model != "off"
                and self.vision_settings.context.tile_ranking
                and self.vision_settings.tiles.enabled
            )
            ranker = (
                load_context_ranker(
                    self.vision_settings.context.model,
                    enabled=use_context_ranking,
                    data_dir=data_dir,
                )
                if uses_default_detector and use_context_ranking
                else None
            )
            context_sensor = None if ranker is None or ranker.name == "off" else ranker
            local_rescue_detector = self.detector if uses_default_detector else None
            self.decision_engine = DecisionEngine(
                context_sensor,
                local_rescue_detector,
                settings=self.vision_settings,
                rescue_enabled=self.vision_settings.tiles.enabled,
                rescue_rows=self.vision_settings.tiles.rows,
                rescue_columns=self.vision_settings.tiles.columns,
                crop_expansion=self.vision_settings.recheck.crop_expansion,
                tile_overlap=self.vision_settings.tiles.overlap,
                max_tile_skip=self.vision_settings.tiles.max_skip,
                checks_per_scan=self.vision_settings.tiles.checks_per_scan,
                borderline_margin=self.vision_settings.recheck.proposal_margin,
                pin_followup_checks=max(0, self.vision_settings.temporal.window_size - 1),
            )
        self.vision_pipeline = VisionPipeline(
            self.detector,
            self.decision_engine,
            yolo_adapter=yolo_adapter,
            shadow_adapter=shadow_adapter,
            full_input_size=self.vision_settings.detector.full_input_size,
        )
        context_sensor = self.decision_engine.viddexa_ranker.classifier
        if (
            self.vision_settings.context.model == "off"
            or not self.vision_settings.context.tile_ranking
            or not self.vision_settings.tiles.enabled
        ):
            context_status = "disabled"
        elif context_sensor is None:
            context_status = "unavailable"
        else:
            context_status = "available"
        context_model_name = self.vision_settings.context.model
        if context_sensor is not None:
            context_model_name = str(
                getattr(context_sensor, "model_name", None)
                or getattr(context_sensor, "name", context_model_name)
            )
        self.diagnostics = diagnostics or DiagnosticsStore(
            model_variant=str(getattr(self.detector, "model_variant", "custom")),
            inference_resolution=getattr(
                self.detector,
                "inference_resolution",
                None,
            ),
            context_model=context_model_name,
            context_status=context_status,
            yolo_status=yolo_status,
            primary_detector=str(
                getattr(self.detector, "name", None)
                or getattr(self.detector, "model_variant", "nudenet_640m")
            ),
            models=compact_model_status(
                inspect_models(data_dir=data_dir)
            ),
            threshold_policy=ThresholdPolicy.from_settings(self.vision_settings),
            borderline_margin=self.vision_settings.recheck.proposal_margin,
        )
        self.overlay = (
            overlay
            if overlay is not None
            else create_overlay_backend(
                platform_adapter.name,
                data_dir=data_dir,
            )
        )
        self.recorder = (
            recorder
            if recorder is not None
            else EventRecorder(platform_adapter.default_data_dir() / "events.db")
        )
        self._verifier_factory = (
            verifier_factory
            if verifier_factory is not None
            else lambda: TemporalVerifier(
                self.vision_settings.temporal.window_size,
                self.vision_settings.temporal.min_fresh_hits,
                evidence_threshold=self.vision_settings.temporal.evidence_threshold,
                decay=self.vision_settings.temporal.decay,
                confirmation=self.vision_settings.temporal.confirmation,
            )
        )
        self.change_scheduler = change_scheduler or ChangeScheduler(
            change_ratio_threshold=self.vision_settings.scan.change_sensitivity,
            adaptive=self.vision_settings.scan.adaptive,
            periodic_scan_interval=self.vision_settings.scan.periodic_scan_interval,
            candidate_followup_checks=max(0, self.vision_settings.temporal.window_size - 1),
        )
        self.context_store = context_store or ForegroundContextStore()
        self.context_policy = context_policy or ContextPolicyService()
        self.context_worker = (
            context_worker
            if context_worker is not None
            else self._create_context_worker(platform_adapter)
        )
        self._bypass_active = False
        self.check_interval = (
            float(self.vision_settings.scan.normal_interval_ms) / 1000.0
            if check_interval is None
            else check_interval
        )
        self.cooldown_seconds = (
            self.vision_settings.ui.cooldown_seconds
            if cooldown_seconds is None
            else cooldown_seconds
        )
        self._clock = clock
        self._scan_clock = scan_clock
        self._sleeper = sleeper
        self.runtime = ProtectionRuntime(
            self.vision_pipeline,
            self.decision_engine,
            self.change_scheduler,
            self.diagnostics,
            self._verifier_factory,
            self._scan_clock,
        )
        self._running = False
        self._state = State.STOPPED
        self.diagnostics.set_protection_state(self._state.name)
        self._record_capture_diagnostics()
        self._cooldown_until = 0.0

    @property
    def state(self) -> State:
        return self._state

    def start(
        self,
        stop_event: Event | None = None,
        test_intervention_event: Event | None = None,
    ) -> None:
        """Run monitoring until stop is requested or Ctrl+C is received."""

        self._running = True
        self._transition(State.MONITORING)

        try:
            self.context_worker.start()
            while self._running and not (stop_event and stop_event.is_set()):
                if test_intervention_event and test_intervention_event.is_set():
                    test_intervention_event.clear()
                    self.show_test_intervention()
                else:
                    self.check_once()
                if self._running and not (stop_event and stop_event.is_set()):
                    self._sleeper(self._next_interval())
        finally:
            try:
                try:
                    self.context_worker.stop()
                finally:
                    try:
                        self.overlay.close()
                    finally:
                        try:
                            self.capturer.close()
                        finally:
                            self.recorder.close()
            finally:
                self._transition(State.STOPPED)
                self._running = False

    def stop(self) -> None:
        """Request a clean stop after the current operation finishes."""

        self._running = False

    def show_test_intervention(self) -> None:
        """Show an unrecorded manual test overlay on the primary monitor."""

        monitor = self.capturer.monitor_for_index()
        self._transition(State.BLOCKED)
        try:
            self.overlay.show(monitor)
        finally:
            self._transition(State.BYPASSED if self._bypass_active else State.MONITORING)

    def check_once(self) -> list[VisualViolationDecision] | None:
        """Advance the state machine by one monitoring step."""

        now = self._clock()
        self._record_capture_diagnostics()

        if self._state == State.STOPPED:
            self._transition(State.MONITORING)

        if self._state == State.COOLDOWN:
            if now < self._cooldown_until:
                return None
            self._transition(State.MONITORING)

        context = self.context_store.latest()
        policy_result = (
            self.context_policy.evaluate(context) if context is not None else None
        )
        self.diagnostics.record_foreground_context(context, policy_result)
        if policy_result is not None and not allows_vision(policy_result.action):
            if policy_result.action is ContextPolicyAction.FORCE_BLOCK:
                self._leave_bypass()
                monitor_index, trigger_type = self._context_rule_detection(
                    context, policy_result
                )
                self._show_intervention(
                    monitor_index=monitor_index,
                    trigger_type=trigger_type,
                )
                return None
            self._enter_bypass()
            return []

        self._leave_bypass()

        results: list[VisualViolationDecision] = []
        has_candidate = False
        has_fresh_frame = False
        active_index = self._active_monitor_index(context)

        for monitor_index in self.capturer.monitor_indexes:
            scan_started = self._scan_clock()
            captured_frame = self.capturer.grab(monitor_index)
            self._record_capture_diagnostics()
            outcome = self.runtime.scan_monitor(
                captured_frame,
                monitor_index,
                is_active_monitor=(
                    active_index is None or active_index == monitor_index
                ),
                scan_started=scan_started,
            )
            if not outcome.fresh_frame:
                continue
            has_fresh_frame = True
            decision = outcome.decision
            if decision is None:
                continue
            results.append(decision)
            has_candidate = has_candidate or outcome.candidate

            if outcome.confirmed:
                self._show_intervention(
                    monitor_index=monitor_index,
                    trigger_type="vision",
                    label=decision.label,
                    confidence=decision.confidence,
                )
                return results

        if has_fresh_frame:
            self._transition(State.CANDIDATE if has_candidate else State.MONITORING)
        return results

    def _transition(self, state: State) -> None:
        self._state = state
        self.diagnostics.set_protection_state(state.name)

    def _record_capture_diagnostics(self) -> None:
        self.diagnostics.record_capture(self.capturer.status)

    def _next_interval(self) -> float:
        if self._state == State.CANDIDATE:
            return max(
                0.05,
                float(self.vision_settings.scan.candidate_interval_ms) / 1000.0,
            )
        return self.check_interval

    def _active_monitor_index(self, context: ForegroundContext | None) -> int | None:
        if context is None:
            return None
        center = context.application.window_center
        if center is None:
            return None
        return self.capturer.monitor_index_at(*center)

    def _enter_bypass(self) -> None:
        if self._bypass_active:
            self._transition(State.BYPASSED)
            return
        self.runtime.reset_for_context_boundary()
        self._bypass_active = True
        self._transition(State.BYPASSED)

    def _leave_bypass(self) -> None:
        if not self._bypass_active:
            return
        self.runtime.reset_for_context_boundary()
        self._bypass_active = False
        self._transition(State.MONITORING)

    def _context_rule_detection(
        self,
        context: ForegroundContext,
        policy: ContextPolicyResult,
    ) -> tuple[int, str]:
        center = context.application.window_center
        monitor_index = (
            self.capturer.monitor_index_at(*center) if center is not None else None
        )
        if monitor_index is None:
            monitor_index = self.capturer.monitor_for_index().index

        website_rule = (
            policy.matched_website_rule
            if policy.website_action is ContextPolicyAction.FORCE_BLOCK
            else None
        )
        if website_rule is not None:
            trigger_type = "website_rule"
        else:
            trigger_type = "application_rule"
        return monitor_index, trigger_type

    def _create_context_worker(
        self,
        platform_adapter: PlatformAdapter,
    ) -> ForegroundContextWorker:
        service = ForegroundContextService(
            platform_adapter.get_foreground_application,
            platform_adapter.create_website_reader(),
        )
        return ForegroundContextWorker(
            service,
            self.context_store,
            application_policy=self.context_policy.application,
        )

    def _record_trigger(
        self,
        monitor_index: int,
        trigger_type: str,
        *,
        label: str | None = None,
        confidence: float | None = None,
    ) -> Future[int] | None:
        event = ProtectionEvent(
            occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            trigger_type=trigger_type,
            label=label,
            confidence=confidence,
            monitor_index=monitor_index,
        )

        try:
            return self.recorder.record_async(event)
        except Exception:
            LOGGER.exception("Could not queue protection event recording")
            return None

    def _show_intervention(
        self,
        *,
        monitor_index: int,
        trigger_type: str,
        label: str | None = None,
        confidence: float | None = None,
    ) -> None:
        self._transition(State.BLOCKED)
        record_future = self._record_trigger(
            monitor_index,
            trigger_type,
            label=label,
            confidence=confidence,
        )
        monitor = self.capturer.monitor_for_index(monitor_index)
        self.overlay.show(monitor)
        self._mark_intervention_shown_after_record(record_future)
        self.runtime.reset_vision()
        self._cooldown_until = self._clock() + self.cooldown_seconds
        self._transition(State.COOLDOWN)

    def _mark_intervention_shown_after_record(
        self,
        record_future: Future[int] | None,
    ) -> None:
        if record_future is None:
            return

        record_future.add_done_callback(self._queue_intervention_shown_marker)

    def _queue_intervention_shown_marker(self, record_future: Future[int]) -> None:
        try:
            event_id = record_future.result()
        except Exception:
            LOGGER.exception("Could not finish recording protection event")
            return

        try:
            marker_future = self.recorder.mark_intervention_shown_async(event_id)
            marker_future.add_done_callback(self._log_recording_failure)
        except Exception:
            LOGGER.exception("Could not queue intervention-shown marker")

    @staticmethod
    def _log_recording_failure(future: Future[object]) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("Could not finish recording protection event")
