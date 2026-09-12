"""Normalized screen-capture data shared with the vision pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Rect:
    """One changed region in monitor-local pixels."""

    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    """Stable normalized metadata for one physical display."""

    id: str
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool = False

    def contains(self, x: int, y: int) -> bool:
        return (
            self.left <= x < self.left + self.width
            and self.top <= y < self.top + self.height
        )


@dataclass(frozen=True, slots=True)
class CaptureFrame:
    """One fresh full-resolution BGR frame produced by a capture backend."""

    image: np.ndarray
    monitor_id: str
    timestamp_ns: int
    sequence: int
    changed_regions: tuple[Rect, ...] | None
    backend: str


@dataclass(frozen=True, slots=True)
class CaptureBackendStatus:
    """Privacy-safe health information for the active capture backend."""

    preferred_backend: str
    active_backend: str | None
    fallback: bool
    fallback_reason: str | None
    healthy: bool
    error: str | None = None
    session: str | None = None
    monitor_count: int = 0
    frame_age_ms: float | None = None
