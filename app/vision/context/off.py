"""Disabled context ranker. Tile order then uses change + age."""

from __future__ import annotations

import numpy as np

from app.vision.context.base import CONTEXT_LABELS, ContextResult


class OffContextRanker:
    """Always available. Never scores tiles and never blocks."""

    @property
    def name(self) -> str:
        return "off"

    def classify_batch(self, frames: list[np.ndarray]) -> list[ContextResult]:
        empty = dict.fromkeys(CONTEXT_LABELS, 0.0)
        return [ContextResult(scores=dict(empty), model=self.name) for _ in frames]

    def classify(self, bgr_image: np.ndarray) -> dict[str, float] | None:
        del bgr_image
        return None
