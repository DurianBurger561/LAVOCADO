"""Decide what limited vision compute should inspect next. No model inference."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.settings.schema import VisionSettings
from app.vision.change_map import ChangeMap, build_change_map, tile_change_scores
from app.vision.preprocessor import FramePreprocessor, TileSpec
from app.vision.regions import Region
from app.vision.tiles import TileState, mark_checked, rank_tiles
from app.vision.tracking import CandidateTrack
from app.vision.viddexa_ranker import ViddexaRanker

HIGH_CHANGE = 0.12
AGGRESSIVE_SCANS = 4


@dataclass(frozen=True, slots=True)
class ScanPlan:
    mode: str
    run_full: bool
    tile_indexes: tuple[int, ...]
    roi: Region | None
    subdivide: bool
    input_size: int
    interval_ms: int


@dataclass(slots=True)
class _MonitorBudget:
    aggressive_scans_remaining: int = 0
    scan_id: int = 0
    last_mode: str = "monitoring"


@dataclass(slots=True)
class _RescueSchedule:
    next_tile_index: int = 0
    pinned_tile_index: int | None = None
    pinned_checks_remaining: int = 0


class TileScheduler:
    """Allocate full scans, tiles, focused ROI, and starvation catch-up."""

    def __init__(
        self,
        settings: VisionSettings,
        *,
        rows: int | None = None,
        columns: int | None = None,
        overlap: float | None = None,
        max_skip: int | None = None,
        pin_followup_checks: int = 0,
    ) -> None:
        self.settings = settings
        self.tile_spec = TileSpec(
            settings.tiles.rows if rows is None else rows,
            settings.tiles.columns if columns is None else columns,
            settings.tiles.overlap if overlap is None else overlap,
        )
        self.max_skip = settings.tiles.max_skip if max_skip is None else max_skip
        self.pin_followup_checks = max(0, pin_followup_checks)
        self._monitors: dict[int, _MonitorBudget] = {}
        self._tiles: dict[int, list[TileState]] = {}
        self._previous_gray: dict[int, np.ndarray] = {}
        self._scan_ids: dict[int, int] = {}
        self._last_plan: dict[int, ScanPlan] = {}
        self._rescue_schedules: dict[int, _RescueSchedule] = {}

    def reset(self) -> None:
        self._monitors.clear()
        self._tiles.clear()
        self._previous_gray.clear()
        self._scan_ids.clear()
        self._last_plan.clear()
        self._rescue_schedules.clear()

    def tiles_for(
        self, monitor_index: int, prepared: FramePreprocessor
    ) -> list[TileState]:
        regions = tuple(item.region for item in prepared.tiles(self.tile_spec))
        existing = self._tiles.get(monitor_index)
        if existing is not None and len(existing) == len(regions):
            for tile, region in zip(existing, regions, strict=False):
                tile.region = region
            return existing
        tiles = [TileState(index=index, region=region) for index, region in enumerate(regions)]
        self._tiles[monitor_index] = tiles
        return tiles

    def refresh_frame(
        self,
        monitor_index: int,
        prepared: FramePreprocessor,
        ranker: ViddexaRanker,
    ) -> tuple[list[TileState], ChangeMap | None]:
        original = prepared.original
        tiles = self.tiles_for(monitor_index, prepared)
        change_map = build_change_map(original, self._previous_gray.get(monitor_index))
        if change_map is not None:
            self._previous_gray[monitor_index] = change_map.gray
            scores = tile_change_scores(
                change_map, tuple(tile.region for tile in tiles), original.shape
            )
            for tile, score in zip(tiles, scores, strict=False):
                tile.change_score = score
        ranker.refresh_scores(prepared, tiles)
        self._scan_ids[monitor_index] = self._scan_ids.get(monitor_index, 0) + 1
        return tiles, change_map

    def scan_id(self, monitor_index: int) -> int:
        return self._scan_ids.get(monitor_index, 0)

    def ranked_tiles(self, tiles: list[TileState]) -> list[TileState]:
        return rank_tiles(tiles, max_skip=self.max_skip)

    def mark_checked(
        self, monitor_index: int, tiles: list[TileState], checked: set[int]
    ) -> None:
        mark_checked(tiles, checked, self.scan_id(monitor_index))

    def advance_tile(self, monitor_index: int, tile_index: int, tile_count: int) -> None:
        schedule = self._rescue_schedules.setdefault(monitor_index, _RescueSchedule())
        schedule.next_tile_index = (tile_index + 1) % max(1, tile_count)

    def pin_tile(self, monitor_index: int, tile_index: int) -> None:
        if not self.pin_followup_checks:
            return
        schedule = self._rescue_schedules.setdefault(monitor_index, _RescueSchedule())
        schedule.pinned_tile_index = tile_index
        schedule.pinned_checks_remaining = self.pin_followup_checks

    def rescue_status(self, monitor_index: int) -> dict[str, int | None]:
        schedule = self._rescue_schedules.get(monitor_index, _RescueSchedule())
        return {
            "next_tile_index": schedule.next_tile_index,
            "pinned_tile_index": schedule.pinned_tile_index,
            "pinned_checks_remaining": schedule.pinned_checks_remaining,
        }

    def remember_plan(self, monitor_index: int, plan: ScanPlan) -> None:
        self._last_plan[monitor_index] = plan

    def last_plan(self, monitor_index: int) -> ScanPlan | None:
        return self._last_plan.get(monitor_index)

    def plan(
        self,
        *,
        monitor_index: int,
        tiles: list[TileState],
        change_map: ChangeMap | None,
        active_track: CandidateTrack | None,
        is_active_monitor: bool,
        elapsed_ms: float = 0.0,
    ) -> ScanPlan:
        budget = self._monitors.setdefault(monitor_index, _MonitorBudget())
        budget.scan_id += 1
        settings = self.settings
        change_ratio = 0.0 if change_map is None else change_map.global_ratio

        if active_track is not None:
            budget.last_mode = "focused"
            return ScanPlan(
                mode="focused",
                run_full=False,
                tile_indexes=(),
                roi=active_track.box,
                subdivide=False,
                input_size=settings.detector.tile_input_size,
                interval_ms=settings.scan.candidate_interval_ms,
            )

        if change_ratio >= HIGH_CHANGE:
            budget.aggressive_scans_remaining = AGGRESSIVE_SCANS
        if budget.aggressive_scans_remaining > 0:
            budget.aggressive_scans_remaining -= 1
            mode = "aggressive"
            checks = min(2, max(settings.tiles.checks_per_scan, 2))
        else:
            mode = "monitoring"
            checks = settings.tiles.checks_per_scan

        if (
            settings.scan.active_monitor_priority
            and not is_active_monitor
            and budget.scan_id % 2 == 0
            and not any(tile.skipped_scans >= self.max_skip for tile in tiles)
        ):
            mode = "deferred"
            checks = 1

        remaining_ms = max(0.0, settings.scan.vision_budget_ms - elapsed_ms)
        if remaining_ms < 40:
            checks = 0 if mode != "aggressive" else 1

        ranked = self.ranked_tiles(tiles)
        selected = tuple(tile.index for tile in ranked[: max(0, checks)])
        starved = [tile for tile in tiles if tile.skipped_scans >= self.max_skip]
        if starved and starved[0].index not in selected:
            selected = (starved[0].index,) + selected
            mode = "starvation"

        subdivide = False
        if ranked and ranked[0].context_score >= 0.6 and ranked[0].change_score >= 0.4:
            subdivide = True

        budget.last_mode = mode
        interval = (
            settings.scan.candidate_interval_ms
            if mode == "aggressive"
            else settings.scan.normal_interval_ms
        )
        return ScanPlan(
            mode=mode,
            run_full=True,
            tile_indexes=selected[:2],
            roi=None,
            subdivide=subdivide,
            input_size=settings.detector.full_input_size,
            interval_ms=interval,
        )
