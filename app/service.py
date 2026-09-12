"""Monitoring state machine for the LAVOCADO core."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timezone
from enum import Enum
from threading import Event

from app import config
from app.blocklist.watcher import BlocklistResult, WindowWatcher
from app.intervention.intervene import InterventionGenerator
from app.intervention.recorder import EventRecorder, ProtectionEvent
from app.platforms import PlatformAdapter
from app.vision.capture import Capturer
from app.vision.context_classifier import load_context_classifier
from app.vision.decision import DecisionEngine
from app.vision.detector import Detector
from app.vision.diagnostics import DiagnosticsStore
from app.vision.overlay import Overlay
from app.vision.temporal import TemporalVerifier

LOGGER = logging.getLogger(__name__)


class State(str, Enum):
    STOPPED = "stopped"
    MONITORING = "monitoring"
    CANDIDATE = "candidate"
    BLOCKED = "blocked"
    COOLDOWN = "cooldown"


class LavocadoService:
    """Coordinate capture, detection, confirmation, and intervention."""

    def __init__(
        self,
        platform_adapter: PlatformAdapter,
        capturer: Capturer | None = None,
        detector: Detector | None = None,
        overlay: Overlay | None = None,
        recorder: EventRecorder | None = None,
        intervention: InterventionGenerator | None = None,
        watcher: WindowWatcher | None = None,
        decision_engine: DecisionEngine | None = None,
        diagnostics: DiagnosticsStore | None = None,
        *,
        verifier_factory: Callable[[], TemporalVerifier] | None = None,
        check_interval: float = config.CHECK_INTERVAL,
        cooldown_seconds: float = config.COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        scan_clock: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.platform_adapter = platform_adapter
        self.capturer = (
            capturer if capturer is not None else Capturer(platform_adapter)
        )
        uses_default_detector = detector is None
        self.detector = detector if detector is not None else Detector()
        if decision_engine is not None:
            self.decision_engine = decision_engine
        else:
            context_classifier = (
                load_context_classifier() if uses_default_detector else None
            )
            local_rescue_detector = (
                self.detector
                if uses_default_detector
                and self.detector.inference_resolution
                == config.NUDENET_INFERENCE_RESOLUTION
                else None
            )
            self.decision_engine = DecisionEngine(
                context_classifier,
                local_rescue_detector,
            )
        context_sensor = getattr(self.decision_engine, "context_classifier", None)
        if not config.CONTEXT_MODEL_ENABLED:
            context_status = "disabled"
        elif context_sensor is None:
            context_status = "unavailable"
        else:
            context_status = "available"
        self.diagnostics = diagnostics or DiagnosticsStore(
            model_variant=str(getattr(self.detector, "model_variant", "custom")),
            inference_resolution=getattr(
                self.detector,
                "inference_resolution",
                None,
            ),
            context_model=config.CONTEXT_MODEL_NAME,
            context_status=context_status,
        )
        self.overlay = (
            overlay if overlay is not None else Overlay(platform_adapter)
        )
        self.recorder = (
            recorder
            if recorder is not None
            else EventRecorder(platform_adapter.default_data_dir() / "events.db")
        )
        self.intervention = (
            intervention if intervention is not None else InterventionGenerator()
        )
        self.watcher = (
            watcher
            if watcher is not None
            else WindowWatcher(platform_adapter)
        )
        self._verifier_factory = (
            verifier_factory
            if verifier_factory is not None
            else lambda: TemporalVerifier(
                config.CONFIRMATION_WINDOW_SIZE,
                config.CONFIRMATION_REQUIRED_HITS,
            )
        )
        self._verifiers: dict[int, TemporalVerifier] = {}
        self._last_frame_sequences: dict[int, tuple[str, int]] = {}
        self.check_interval = check_interval
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._scan_clock = scan_clock
        self._sleeper = sleeper
        self._running = False
        self._state = State.STOPPED
        self.diagnostics.set_protection_state(self._state.name)
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
            while self._running and not (stop_event and stop_event.is_set()):
                if test_intervention_event and test_intervention_event.is_set():
                    test_intervention_event.clear()
                    self.show_test_intervention()
                else:
                    self.check_once()
                if self._running and not (stop_event and stop_event.is_set()):
                    self._sleeper(self.check_interval)
        finally:
            try:
                try:
                    self.capturer.close()
                finally:
                    try:
                        self.recorder.close()
                    finally:
                        self.intervention.close()
            finally:
                self._transition(State.STOPPED)
                self._running = False

    def stop(self) -> None:
        """Request a clean stop after the current operation finishes."""

        self._running = False

    def show_test_intervention(self) -> None:
        """Show an unrecorded manual test overlay on the primary monitor."""

        monitor_indexes = tuple(self.capturer.monitor_indexes)
        monitor_index = monitor_indexes[0] if monitor_indexes else config.MONITOR_INDEX
        self._transition(State.BLOCKED)
        try:
            self.overlay.show(
                monitor_index=monitor_index,
                support_message=self._generate_intervention(),
            )
        finally:
            self._transition(State.MONITORING)

    def check_once(self) -> list[dict[str, object]] | None:
        """Advance the state machine by one monitoring step."""

        now = self._clock()

        if self._state == State.STOPPED:
            self._transition(State.MONITORING)

        if self._state == State.COOLDOWN:
            if now < self._cooldown_until:
                return None
            self._transition(State.MONITORING)

        blocklist_result = self.watcher.check()
        blocked_result = self._blocklist_detection(blocklist_result)
        if blocked_result is not None:
            monitor_index = int(blocked_result["monitor_index"])
            self._show_intervention(
                blocked_result,
                monitor_index,
                trigger_type="blocklist",
            )
            return [blocked_result]

        results: list[dict[str, object]] = []
        has_candidate = False
        has_fresh_frame = False

        for monitor_index in self.capturer.monitor_indexes:
            scan_started = self._scan_clock()
            captured_frame = self.capturer.grab(monitor_index)
            if not self._is_fresh_frame(monitor_index, captured_frame):
                continue
            has_fresh_frame = True
            nudenet_result = dict(self.detector.check(captured_frame.model_frame))
            result = self.decision_engine.evaluate(
                nudenet_result,
                captured_frame,
                monitor_index=monitor_index,
            )
            result["monitor_index"] = monitor_index
            results.append(result)

            is_candidate = bool(result["blocked"])
            has_candidate = has_candidate or is_candidate
            verifier = self._verifiers.get(monitor_index)
            if verifier is None:
                verifier = self._verifier_factory()
                self._verifiers[monitor_index] = verifier

            confirmed = verifier.update(is_candidate)
            rescue_status = self._decision_rescue_status(monitor_index)
            self.diagnostics.record_scan(
                monitor_index=monitor_index,
                elapsed_ms=(self._scan_clock() - scan_started) * 1000,
                decision=result,
                temporal=verifier.history,
                rescue_status=rescue_status,
            )

            if confirmed:
                self._show_intervention(result, monitor_index, trigger_type="vision")
                return results

        if has_fresh_frame:
            self._transition(State.CANDIDATE if has_candidate else State.MONITORING)
        return results

    def _transition(self, state: State) -> None:
        self._state = state
        self.diagnostics.set_protection_state(state.name)

    def _decision_rescue_status(
        self,
        monitor_index: int,
    ) -> dict[str, int | None]:
        status_reader = getattr(self.decision_engine, "rescue_status", None)
        if not callable(status_reader):
            return {}
        status = status_reader(monitor_index)
        return status if isinstance(status, dict) else {}

    def _is_fresh_frame(self, monitor_index: int, captured_frame: object) -> bool:
        sequence = getattr(captured_frame, "sequence", None)
        if not isinstance(sequence, int) or sequence < 1:
            return True
        identity = (str(getattr(captured_frame, "backend", "unknown")), sequence)
        if self._last_frame_sequences.get(monitor_index) == identity:
            return False
        self._last_frame_sequences[monitor_index] = identity
        return True

    def _reset_verifiers(self) -> None:
        for verifier in self._verifiers.values():
            verifier.reset()
        reset_decisions = getattr(self.decision_engine, "reset", None)
        if callable(reset_decisions):
            reset_decisions()

    def _record_trigger(
        self,
        result: dict[str, object],
        monitor_index: int,
        trigger_type: str,
    ) -> Future[int] | None:
        label = result.get("label")
        confidence = result.get("confidence")
        event = ProtectionEvent(
            occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            trigger_type=trigger_type,
            label=None if label is None else str(label),
            confidence=None if confidence is None else float(confidence),
            monitor_index=monitor_index,
        )

        try:
            return self.recorder.record_async(event)
        except Exception:
            LOGGER.exception("Could not queue protection event recording")
            return None

    def _show_intervention(
        self,
        result: dict[str, object],
        monitor_index: int,
        trigger_type: str,
    ) -> None:
        self._transition(State.BLOCKED)
        record_future = self._record_trigger(result, monitor_index, trigger_type)
        support_message = self._generate_intervention()
        self.overlay.show(
            monitor_index=monitor_index,
            support_message=support_message,
        )
        self._mark_intervention_shown_after_record(record_future)
        self._reset_verifiers()
        self._cooldown_until = self._clock() + self.cooldown_seconds
        self._transition(State.COOLDOWN)

    def _blocklist_detection(
        self,
        result: BlocklistResult,
    ) -> dict[str, object] | None:
        if not result.blocked or result.window is None:
            return None
        center = result.window.center
        if center is None:
            return None
        monitor_index = self.capturer.monitor_index_at(*center)
        if monitor_index is None:
            return None
        return {
            "blocked": True,
            "reason": f"Blocked window term: {result.matched_term}",
            "label": result.matched_term,
            "confidence": None,
            "check_points": [],
            "monitor_index": monitor_index,
        }

    def _generate_intervention(self) -> Future[str] | None:
        try:
            return self.intervention.generate_async()
        except Exception:
            LOGGER.exception("Could not queue supportive intervention")
            return None

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
            marker = getattr(self.recorder, "mark_intervention_shown_async", None)
            if callable(marker):
                marker_future = marker(event_id)
                marker_future.add_done_callback(self._log_recording_failure)
            else:
                self.recorder.mark_intervention_shown(event_id)
        except Exception:
            LOGGER.exception("Could not queue intervention-shown marker")

    @staticmethod
    def _log_recording_failure(future: Future[object]) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("Could not finish recording protection event")
