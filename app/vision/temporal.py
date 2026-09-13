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


class EvidenceAccumulator:
    """Accumulate visual-violation types. Never stores porn-purpose probability."""

    def __init__(self, window_size: int) -> None:
        self._items: deque[str | None] = deque(maxlen=window_size)

    def add(self, evidence_type: str | None) -> None:
        self._items.append(evidence_type)

    def decay(self) -> None:
        self._items.append(None)

    def reset(self) -> None:
        self._items.clear()

    def history(self) -> tuple[str | None, ...]:
        return tuple(self._items)


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
        self._evidence = EvidenceAccumulator(window_size)
        self._last_frame_sequence: int | None = None
        self._active_region: object | None = None
        self._active_track_id: int | None = None

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

        return self._evidence.history()

    def update(
        self,
        is_candidate: bool,
        *,
        frame_sequence: int | None = None,
        region: object | None = None,
        evidence_type: str | None = None,
        track_id: int | None = None,
    ) -> bool:
        """Record one fresh-frame decision and report whether it is confirmed.

        Full-scan, ROI, and tile rechecks that share ``frame_sequence`` count
        as a single temporal observation. Hits on different tracks or
        non-overlapping regions do not confirm each other.
        """

        if (
            frame_sequence is not None
            and self._last_frame_sequence == frame_sequence
        ):
            return self._is_confirmed()

        if frame_sequence is not None:
            self._last_frame_sequence = frame_sequence

        if is_candidate and track_id is not None and self._active_track_id is not None:
            if track_id != self._active_track_id:
                self._history.clear()
                self._evidence.reset()
                self._active_region = None
        if is_candidate and region is not None and self._active_region is not None:
            if track_id is None and not _regions_overlap(region, self._active_region):
                self._history.clear()
                self._evidence.reset()
        if is_candidate and region is not None:
            self._active_region = region
        elif not is_candidate:
            self._active_region = None
        if is_candidate and track_id is not None:
            self._active_track_id = track_id
        elif not is_candidate:
            self._active_track_id = None

        self._history.append(bool(is_candidate))
        if is_candidate:
            self._evidence.add(evidence_type)
        else:
            self._evidence.decay()
        return self._is_confirmed()

    def reset(self) -> None:
        """Forget all previous frame decisions."""

        self._history.clear()
        self._evidence.reset()
        self._last_frame_sequence = None
        self._active_region = None
        self._active_track_id = None

    def _is_confirmed(self) -> bool:
        return (
            len(self._history) == self._window_size
            and self.hits >= self._required_hits
        )


TemporalEngine = TemporalVerifier
