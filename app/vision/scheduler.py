"""Decide what limited vision compute should inspect next. No model inference."""

from __future__ import annotations

from dataclasses import dataclass

from app.settings.schema import VisionSettings
from app.vision.change_map import ChangeMap
from app.vision.regions import Region
from app.vision.tiles import TileState, rank_tiles
from app.vision.tracking import CandidateTrack

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


class VisionScheduler:
    """Allocate full scans, tiles, focused ROI, and starvation catch-up."""

    def __init__(self, settings: VisionSettings) -> None:
        self.settings = settings
        self._monitors: dict[int, _MonitorBudget] = {}

    def reset(self) -> None:
        self._monitors.clear()

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
            and not any(tile.skipped_scans >= settings.tiles.max_skip for tile in tiles)
        ):
            mode = "deferred"
            checks = 1

        remaining_ms = max(0.0, settings.scan.vision_budget_ms - elapsed_ms)
        if remaining_ms < 40:
            checks = 0 if mode != "aggressive" else 1

        ranked = rank_tiles(tiles, max_skip=settings.tiles.max_skip)
        selected = tuple(tile.index for tile in ranked[: max(0, checks)])
        starved = [tile for tile in tiles if tile.skipped_scans >= settings.tiles.max_skip]
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
