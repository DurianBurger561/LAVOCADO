"""Coordinate per-frame tile scoring, tracked ROI prediction, and scan plans."""

from __future__ import annotations

import time
from collections.abc import Callable

from app.platforms.capture.models import CaptureFrame
from app.vision.preprocessor import FramePreprocessor
from app.vision.scheduler import ScanPlan, TileScheduler
from app.vision.tracking import CandidateTracker
from app.vision.viddexa_ranker import ViddexaRanker


class ScanPlanner:
    """Prepare one scan plan without running a primary detector or deciding Block."""

    def __init__(
        self,
        scheduler: TileScheduler,
        tracker: CandidateTracker,
        ranker: ViddexaRanker,
        *,
        crop_expansion: float,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.scheduler = scheduler
        self.tracker = tracker
        self.ranker = ranker
        self.crop_expansion = crop_expansion
        self._clock = clock

    def prepare_scan(
        self,
        captured_frame: CaptureFrame,
        monitor_index: int,
        *,
        is_active_monitor: bool = True,
        prepared_frame: FramePreprocessor | None = None,
    ) -> ScanPlan:
        prepared = prepared_frame or FramePreprocessor(captured_frame)
        prepared.require_frame(captured_frame)
        started = self._clock()
        tiles, change_map = self.scheduler.refresh_frame(
            monitor_index, prepared, self.ranker
        )
        active = self.tracker.active_track(monitor_index)
        if active is not None:
            predicted = self.tracker.predicted_roi(
                active, prepared.original.shape, self.crop_expansion
            )
            if predicted is not None:
                active.box = predicted
        plan = self.scheduler.plan(
            monitor_index=monitor_index,
            tiles=tiles,
            change_map=change_map,
            active_track=active,
            is_active_monitor=is_active_monitor,
            elapsed_ms=max(0.0, (self._clock() - started) * 1000.0),
        )
        self.scheduler.remember_plan(monitor_index, plan)
        return plan
