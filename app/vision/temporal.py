"""Confirm risky detections across multiple frames."""

from __future__ import annotations

from collections import deque


class TemporalVerifier:
    """Require a configured number of candidate frames in a sliding window."""

    def __init__(self, window_size: int, required_hits: int) -> None:
        if window_size < 1:
            raise ValueError("window_size must be at least 1")
        if not 1 <= required_hits <= window_size:
            raise ValueError("required_hits must be between 1 and window_size")

        self._window_size = window_size
        self._required_hits = required_hits
        self._history: deque[bool] = deque(maxlen=window_size)

    @property
    def hits(self) -> int:
        """Return the number of candidate frames currently in the window."""

        return sum(self._history)

    def update(self, is_candidate: bool) -> bool:
        """Record one decision and report whether the risk is confirmed."""

        self._history.append(bool(is_candidate))
        return (
            len(self._history) == self._window_size
            and self.hits >= self._required_hits
        )

    def reset(self) -> None:
        """Forget all previous frame decisions."""

        self._history.clear()
