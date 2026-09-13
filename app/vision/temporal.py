"""Confirm visual violations across distinct fresh frames and regions."""

from __future__ import annotations

from collections import deque


def _regions_overlap(left: object, right: object) -> bool:
    if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
        return True
    if len(left) != 4 or len(right) != 4:
        return True
    try:
        ax1, ay1, ax2, ay2 = (float(value) for value in left)
        bx1, by1, bx2, by2 = (float(value) for value in right)
    except (TypeError, ValueError):
        return True
    return ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2


class TemporalVerifier:
    """Require confirmed visual violations on distinct fresh frames."""

    def __init__(self, window_size: int, required_hits: int) -> None:
        if window_size < 1:
            raise ValueError("window_size must be at least 1")
        if not 1 <= required_hits <= window_size:
            raise ValueError("required_hits must be between 1 and window_size")

        self._window_size = window_size
        self._required_hits = required_hits
        self._history: deque[bool] = deque(maxlen=window_size)
        self._evidence: deque[str | None] = deque(maxlen=window_size)
        self._last_frame_sequence: int | None = None
        self._active_region: object | None = None

    @property
    def hits(self) -> int:
        """Return the number of candidate frames currently in the window."""

        return sum(self._history)

    @property
    def history(self) -> tuple[bool, ...]:
        """Return an immutable copy for privacy-safe diagnostics."""

        return tuple(self._history)

    @property
    def evidence_history(self) -> tuple[str | None, ...]:
        """Return visual-violation evidence types, never pixels or purpose."""

        return tuple(self._evidence)

    def update(
        self,
        is_candidate: bool,
        *,
        frame_sequence: int | None = None,
        region: object | None = None,
        evidence_type: str | None = None,
    ) -> bool:
        """Record one fresh-frame decision and report whether it is confirmed.

        Full-scan, ROI, and tile rechecks that share ``frame_sequence`` count
        as a single temporal observation. Hits on non-overlapping regions do
        not confirm each other.
        """

        if (
            frame_sequence is not None
            and self._last_frame_sequence == frame_sequence
        ):
            return self._is_confirmed()

        if frame_sequence is not None:
            self._last_frame_sequence = frame_sequence

        if is_candidate and region is not None and self._active_region is not None:
            if not _regions_overlap(region, self._active_region):
                self._history.clear()
                self._evidence.clear()
        if is_candidate and region is not None:
            self._active_region = region
        elif not is_candidate:
            self._active_region = None

        self._history.append(bool(is_candidate))
        self._evidence.append(evidence_type if is_candidate else None)
        return self._is_confirmed()

    def reset(self) -> None:
        """Forget all previous frame decisions."""

        self._history.clear()
        self._evidence.clear()
        self._last_frame_sequence = None
        self._active_region = None

    def _is_confirmed(self) -> bool:
        return (
            len(self._history) == self._window_size
            and self.hits >= self._required_hits
        )
