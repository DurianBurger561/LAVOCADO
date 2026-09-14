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
        self._verifiers: dict[int, TemporalVerifier] = {}
        self._last_frame_sequences: dict[int, tuple[str, int]] = {}

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

        verifier = self._verifiers.get(monitor_index)
        if verifier is None:
            verifier = self.verifier_factory()
            self._verifiers[monitor_index] = verifier
        evidence_type = (
            decision.evidence[0].evidence_type.value if decision.evidence else None
        )
        confirmed = verifier.update(
            is_violation,
            frame_sequence=frame.sequence,
            region=decision.primary_region,
            evidence_type=evidence_type,
            track_id=decision.track_id,
            evidence_score=decision.track_evidence,
        )
        self.diagnostics.record_scan(
            monitor_index=monitor_index,
            elapsed_ms=(self.scan_clock() - scan_started) * 1000,
            decision=decision,
            temporal=verifier.history,
            rescue_status=self.decision_engine.rescue_status(monitor_index),
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

        for verifier in self._verifiers.values():
            verifier.reset()
        self.pipeline.reset()
        self.change_scheduler.reset()

    def reset_for_context_boundary(self) -> None:
        """Also discard freshness identities when vision has been bypassed."""

        self.reset_vision()
        self._last_frame_sequences.clear()

    def _is_fresh_frame(self, monitor_index: int, frame: CaptureFrame) -> bool:
        if frame.sequence < 1:
            return True
        identity = (frame.backend, frame.sequence)
        if self._last_frame_sequences.get(monitor_index) == identity:
            return False
        self._last_frame_sequences[monitor_index] = identity
        return True
