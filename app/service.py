"""Monitoring state machine for the LAVOCADO core."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timezone
from enum import Enum

from app import config
from app.intervention.intervene import InterventionGenerator
from app.intervention.recorder import EventRecorder, ProtectionEvent
from app.platform_support import prepare_desktop_environment
from app.vision.capture import Capturer
from app.vision.detector import Detector
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
        capturer: Capturer | None = None,
        detector: Detector | None = None,
        overlay: Overlay | None = None,
        recorder: EventRecorder | None = None,
        intervention: InterventionGenerator | None = None,
        *,
        verifier_factory: Callable[[], TemporalVerifier] | None = None,
        check_interval: float = config.CHECK_INTERVAL,
        cooldown_seconds: float = config.COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        prepare_desktop_environment()
        self.capturer = capturer if capturer is not None else Capturer()
        self.detector = detector if detector is not None else Detector()
        self.overlay = overlay if overlay is not None else Overlay()
        self.recorder = recorder if recorder is not None else EventRecorder()
        self.intervention = (
            intervention if intervention is not None else InterventionGenerator()
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
        self.check_interval = check_interval
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._running = False
        self._state = State.STOPPED
        self._cooldown_until = 0.0

    @property
    def state(self) -> State:
        return self._state

    def start(self) -> None:
        """Run monitoring until stop is requested or Ctrl+C is received."""

        self._running = True
        self._state = State.MONITORING

        try:
            while self._running:
                self.check_once()
                if self._running:
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
                self._state = State.STOPPED
                self._running = False

    def stop(self) -> None:
        """Request a clean stop after the current operation finishes."""

        self._running = False

    def check_once(self) -> list[dict[str, object]] | None:
        """Advance the state machine by one monitoring step."""

        now = self._clock()

        if self._state == State.STOPPED:
            self._state = State.MONITORING

        if self._state == State.COOLDOWN:
            if now < self._cooldown_until:
                return None
            self._state = State.MONITORING

        results: list[dict[str, object]] = []
        has_candidate = False

        for monitor_index in self.capturer.monitor_indexes:
            frame = self.capturer.grab(monitor_index)
            result = dict(self.detector.check(frame))
            result["monitor_index"] = monitor_index
            results.append(result)

            is_candidate = bool(result["blocked"])
            has_candidate = has_candidate or is_candidate
            verifier = self._verifiers.get(monitor_index)
            if verifier is None:
                verifier = self._verifier_factory()
                self._verifiers[monitor_index] = verifier

            if verifier.update(is_candidate):
                self._state = State.BLOCKED
                record_future = self._record_trigger(result, monitor_index)
                support_message = self._generate_intervention()
                self.overlay.show(
                    monitor_index=monitor_index,
                    support_message=support_message,
                )
                if record_future is not None:
                    try:
                        event_id = record_future.result()
                        self.recorder.mark_intervention_shown(event_id)
                    except Exception:
                        LOGGER.exception("Could not finish recording protection event")
                self._reset_verifiers()
                self._cooldown_until = self._clock() + self.cooldown_seconds
                self._state = State.COOLDOWN
                return results

        self._state = State.CANDIDATE if has_candidate else State.MONITORING
        return results

    def _reset_verifiers(self) -> None:
        for verifier in self._verifiers.values():
            verifier.reset()

    def _record_trigger(
        self,
        result: dict[str, object],
        monitor_index: int,
    ) -> Future[int] | None:
        label = result.get("label")
        confidence = result.get("confidence")
        event = ProtectionEvent(
            occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            trigger_type="vision",
            label=None if label is None else str(label),
            confidence=None if confidence is None else float(confidence),
            monitor_index=monitor_index,
        )

        try:
            return self.recorder.record_async(event)
        except Exception:
            LOGGER.exception("Could not queue protection event recording")
            return None

    def _generate_intervention(self) -> Future[str] | None:
        try:
            return self.intervention.generate_async()
        except Exception:
            LOGGER.exception("Could not queue supportive intervention")
            return None
