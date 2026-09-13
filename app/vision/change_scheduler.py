"""Select fresh frames for detection using native or software change metadata."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app import config
from app.platforms.capture import Rect
from app.vision.capture import CapturedFrame


@dataclass(frozen=True, slots=True)
class ChangeDecision:
    """Privacy-safe scheduling decision for one fresh capture frame."""

    scan: bool
    source: str
    change_ratio: float


@dataclass(slots=True)
class _MonitorSchedule:
    previous_gray: np.ndarray
    checks_since_scan: int = 0
    forced_checks_remaining: int = 0


class ChangeScheduler:
    """Prefer native changed regions and fall back to a grayscale change map."""

    def __init__(
        self,
        *,
        map_max_edge: int = config.CHANGE_MAP_MAX_EDGE,
        pixel_delta: int = config.CHANGE_PIXEL_DELTA,
        change_ratio_threshold: float = config.CHANGE_RATIO_THRESHOLD,
        periodic_scan_interval: int = config.CHANGE_PERIODIC_SCAN_INTERVAL,
        candidate_followup_checks: int = config.CONFIRMATION_WINDOW_SIZE - 1,
    ) -> None:
        if map_max_edge < 1:
            raise ValueError("map_max_edge must be positive")
        if not 0 <= pixel_delta <= 255:
            raise ValueError("pixel_delta must be between 0 and 255")
        if not 0 <= change_ratio_threshold <= 1:
            raise ValueError("change_ratio_threshold must be between 0 and 1")
        if periodic_scan_interval < 1:
            raise ValueError("periodic_scan_interval must be positive")
        if candidate_followup_checks < 0:
            raise ValueError("candidate_followup_checks cannot be negative")
        self.map_max_edge = map_max_edge
        self.pixel_delta = pixel_delta
        self.change_ratio_threshold = change_ratio_threshold
        self.periodic_scan_interval = periodic_scan_interval
        self.candidate_followup_checks = candidate_followup_checks
        self._schedules: dict[int, _MonitorSchedule] = {}

    def should_scan(
        self,
        captured: CapturedFrame,
        monitor_index: int,
    ) -> ChangeDecision:
        """Return whether this fresh frame should enter the detection pipeline."""

        current_gray = self._grayscale_map(captured.original_frame)
        if current_gray is None:
            return ChangeDecision(True, "invalid_frame_failsafe", 1.0)

        schedule = self._schedules.get(monitor_index)
        if schedule is None:
            self._schedules[monitor_index] = _MonitorSchedule(current_gray)
            return ChangeDecision(True, "initial", 1.0)

        schedule.checks_since_scan += 1
        software_ratio = self._software_change_ratio(
            schedule.previous_gray,
            current_gray,
        )
        schedule.previous_gray = current_gray

        if schedule.forced_checks_remaining > 0:
            schedule.forced_checks_remaining -= 1
            schedule.checks_since_scan = 0
            return ChangeDecision(True, "candidate_followup", software_ratio)

        native_regions = captured.changed_regions
        if native_regions is not None:
            change_ratio = self._native_change_ratio(
                native_regions,
                captured.original_frame.shape,
            )
            changed = bool(native_regions)
            source = "native"
        else:
            change_ratio = software_ratio
            changed = change_ratio >= self.change_ratio_threshold
            source = "software"

        if changed:
            schedule.checks_since_scan = 0
            return ChangeDecision(True, source, change_ratio)
        if schedule.checks_since_scan >= self.periodic_scan_interval:
            schedule.checks_since_scan = 0
            return ChangeDecision(True, "periodic", change_ratio)
        return ChangeDecision(False, source, change_ratio)

    def record_candidate(self, monitor_index: int, is_candidate: bool) -> None:
        """Keep temporal confirmation fast after the first candidate frame."""

        if not is_candidate:
            return
        self.request_focused_verification(monitor_index)

    def request_focused_verification(self, monitor_index: int) -> None:
        """Force follow-up scans after UNCERTAIN or VIOLATION evidence."""

        schedule = self._schedules.get(monitor_index)
        if schedule is not None:
            schedule.forced_checks_remaining = max(
                schedule.forced_checks_remaining,
                self.candidate_followup_checks,
            )

    def reset(self) -> None:
        """Force a fresh baseline after intervention or capture discontinuity."""

        self._schedules.clear()

    def _grayscale_map(self, image: object) -> np.ndarray | None:
        if (
            not isinstance(image, np.ndarray)
            or image.dtype != np.uint8
            or image.ndim != 3
            or image.shape[2] != 3
            or image.shape[0] < 1
            or image.shape[1] < 1
        ):
            return None
        height, width = image.shape[:2]
        row_indexes = np.linspace(
            0,
            height - 1,
            min(height, self.map_max_edge),
            dtype=np.intp,
        )
        column_indexes = np.linspace(
            0,
            width - 1,
            min(width, self.map_max_edge),
            dtype=np.intp,
        )
        sampled = image[row_indexes[:, None], column_indexes]
        blue = sampled[:, :, 0].astype(np.uint16)
        green = sampled[:, :, 1].astype(np.uint16)
        red = sampled[:, :, 2].astype(np.uint16)
        gray = (29 * blue + 150 * green + 77 * red) >> 8
        return np.ascontiguousarray(gray, dtype=np.uint8)

    def _software_change_ratio(
        self,
        previous: np.ndarray,
        current: np.ndarray,
    ) -> float:
        if previous.shape != current.shape:
            return 1.0
        difference = np.abs(current.astype(np.int16) - previous.astype(np.int16))
        return float(np.count_nonzero(difference >= self.pixel_delta) / difference.size)

    @staticmethod
    def _native_change_ratio(
        regions: tuple[Rect, ...],
        frame_shape: tuple[int, ...],
    ) -> float:
        height, width = frame_shape[:2]
        frame_area = max(1, height * width)
        changed_area = sum(
            max(0, region.width) * max(0, region.height) for region in regions
        )
        return min(1.0, changed_area / frame_area)
