"""Viddexa tile scoring; context never classifies a protection violation."""

from __future__ import annotations

from time import perf_counter
from typing import Protocol

import numpy as np

from app.vision.context.base import ContextResult
from app.vision.preprocessor import FramePreprocessor, FrameRegion
from app.vision.regions import Region
from app.vision.tiles import TileState


class ContextSensor(Protocol):
    def classify(self, bgr_image: np.ndarray) -> dict[str, float] | None: ...

    def classify_batch(self, frames: list[np.ndarray]) -> list[ContextResult]: ...


def _risk(scores: dict[str, float]) -> float:
    return max(
        float(scores.get("porn", 0.0) or 0.0),
        float(scores.get("hentai", 0.0) or 0.0),
    )


class ViddexaRanker:
    """Provide optional context priority without gating primary evidence."""

    def __init__(self, classifier: ContextSensor | None) -> None:
        self.classifier = classifier
        self._frame_token: int | None = None
        self.last_latency_ms = 0.0

    def latency_for(self, prepared: FramePreprocessor) -> float:
        """Return only this frame's model-ranking time without retaining pixels."""

        return (
            self.last_latency_ms
            if self._frame_token == prepared.generation_id
            else 0.0
        )

    def _begin_frame(self, prepared: FramePreprocessor) -> None:
        if self._frame_token != prepared.generation_id:
            self._frame_token = prepared.generation_id
            self.last_latency_ms = 0.0

    def refresh_scores(
        self, prepared: FramePreprocessor, tiles: list[TileState]
    ) -> None:
        self._begin_frame(prepared)
        if self.classifier is None:
            for tile in tiles:
                tile.context_score = 0.0
                tile.context_scores = {}
            return

        valid = [
            (tile, crop)
            for tile in tiles
            if (crop := prepared.crop_xyxy(tile.region)) is not None
        ]
        started = perf_counter()
        try:
            results = self.classifier.classify_batch([crop for _, crop in valid])
        finally:
            self.last_latency_ms += (perf_counter() - started) * 1000
        for tile in tiles:
            tile.context_score = 0.0
            tile.context_scores = {}
        for (tile, _crop), result in zip(valid, results, strict=False):
            tile.context_scores = dict(result.scores)
            tile.context_score = _risk(result.scores)

    def top_subtile(
        self, prepared: FramePreprocessor, region: Region
    ) -> FrameRegion | None:
        self._begin_frame(prepared)
        subtiles = prepared.subtiles(region)
        if not subtiles:
            return None
        if self.classifier is None:
            return subtiles[0]
        started = perf_counter()
        try:
            scored = [
                (_risk(self.classifier.classify(tile.image) or {}), index, tile)
                for index, tile in enumerate(subtiles)
            ]
        finally:
            self.last_latency_ms += (perf_counter() - started) * 1000
        return min(scored, key=lambda item: (-item[0], item[1]))[2]
