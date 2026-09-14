"""Per-monitor vision and temporal verification for Protection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.diagnostics import DiagnosticsStore
from app.platforms.capture import CaptureFrame
from app.vision.change_scheduler import ChangeScheduler
from app.vision.decision import DecisionEngine
from app.vision.pipeline import VisionPipeline
from app.vision.preprocessor import FramePreprocessor
from app.vision.temporal import TemporalVerifier
from app.vision.violation_policy import (
    VisualViolationClassification,
    VisualViolationDecision,
)


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    """One monitor's result, including frames intentionally not scanned."""

    fresh_frame: bool
    decision: VisualViolationDecision | None = None
    candidate: bool = False
    confirmed: bool = False
    temporal_history: tuple[bool, ...] = ()


@dataclass(slots=True)
class MonitorRuntimeState:
    """One monitor's freshness and temporal identity; never shared across displays."""

    monitor_index: int
    backend: str | None = None
    latest_sequence: int = 0
    verifier: TemporalVerifier | None = None
    candidate_since: float | None = None
    candidate_track_id: int | None = None


class ProtectionRuntime:
    """Own scan scheduling, pipeline execution, and temporal evidence state."""

    def __init__(
        self,
        pipeline: VisionPipeline,
        decision_engine: DecisionEngine,
        change_scheduler: ChangeScheduler,
        diagnostics: DiagnosticsStore,
        verifier_factory: Callable[[], TemporalVerifier],
        scan_clock: Callable[[], float],
    ) -> None:
        self.pipeline = pipeline
        self.decision_engine = decision_engine
        self.change_scheduler = change_scheduler
        self.diagnostics = diagnostics
        self.verifier_factory = verifier_factory
        self.scan_clock = scan_clock
        self._monitors: dict[int, MonitorRuntimeState] = {}

    def scan_monitor(
        self,
        frame: CaptureFrame,
        monitor_index: int,
        *,
        is_active_monitor: bool,
        scan_started: float,
    ) -> ScanOutcome:
        """Evaluate a fresh frame and update the monitor's temporal verifier."""

        if not self._is_fresh_frame(monitor_index, frame):
            return ScanOutcome(fresh_frame=False)

        schedule = self.change_scheduler.should_scan(
            frame,
            monitor_index,
            vision_allowed=True,
        )
        if not schedule.scan:
            return ScanOutcome(fresh_frame=True)

        prepared_frame = FramePreprocessor(frame)
        scan_plan = self.pipeline.prepare_scan(
            frame,
            monitor_index,
            is_active_monitor=is_active_monitor,
            prepared_frame=prepared_frame,
        )
        decision = self.pipeline.evaluate(
            frame,
            monitor_index=monitor_index,
            scan_plan=scan_plan,
            is_active_monitor=is_active_monitor,
            prepared_frame=prepared_frame,
        )

        is_violation = (
            decision.classification is VisualViolationClassification.VIOLATION
        )
        self.change_scheduler.record_candidate(monitor_index, is_violation)
        if decision.classification is VisualViolationClassification.UNCERTAIN:
            self.change_scheduler.request_focused_verification(monitor_index)

        state = self._monitor(monitor_index)
        if state.verifier is None:
            state.verifier = self.verifier_factory()
        verifier = state.verifier
        temporal_started = self.scan_clock()
        if not is_violation:
            state.candidate_since = None
            state.candidate_track_id = None
        elif (
            state.candidate_since is None
            or (decision.track_id is not None and decision.track_id != state.candidate_track_id)
        ):
            state.candidate_since = scan_started
            state.candidate_track_id = decision.track_id
        confirmed = verifier.update(
            is_violation,
            frame_sequence=frame.sequence,
            region=decision.primary_region,
            evidence_type=decision.evidence_type,
            track_id=decision.track_id,
            evidence_score=decision.track_evidence,
        )
        temporal_finished = self.scan_clock()
        self.diagnostics.record_scan(
            monitor_index=monitor_index,
            elapsed_ms=(self.scan_clock() - scan_started) * 1000,
            decision=decision,
            temporal=verifier.history,
            rescue_status=self.decision_engine.rescue_status(monitor_index),
            latencies=self.pipeline.last_latency,
            temporal_ms=(temporal_finished - temporal_started) * 1000,
            confirmation_ms=(
                (temporal_finished - state.candidate_since) * 1000
                if confirmed and state.candidate_since is not None
                else None
            ),
        )
        return ScanOutcome(
            fresh_frame=True,
            decision=decision,
            candidate=is_violation,
            confirmed=confirmed,
            temporal_history=verifier.history,
        )

    def reset_vision(self) -> None:
        """Reset temporal and scan state after an intervention."""

        for state in self._monitors.values():
            if state.verifier is not None:
                state.verifier.reset()
            state.candidate_since = None
            state.candidate_track_id = None
        self.pipeline.reset()
        self.change_scheduler.reset()

    def reset_for_context_boundary(self) -> None:
        """Also discard freshness identities when vision has been bypassed."""

        self.reset_vision()
        self._monitors.clear()

    def _monitor(self, monitor_index: int) -> MonitorRuntimeState:
        state = self._monitors.get(monitor_index)
        if state is None:
            state = MonitorRuntimeState(monitor_index=monitor_index)
            self._monitors[monitor_index] = state
        return state

    def _is_fresh_frame(self, monitor_index: int, frame: CaptureFrame) -> bool:
        if frame.sequence < 1:
            return True
        state = self._monitor(monitor_index)
        if state.backend == frame.backend and frame.sequence <= state.latest_sequence:
            return False
        state.backend = frame.backend
        state.latest_sequence = frame.sequence
        return True
