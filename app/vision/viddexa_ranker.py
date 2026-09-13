"""Viddexa tile scoring; context never classifies a protection violation."""

from __future__ import annotations

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

    def refresh_scores(
        self, prepared: FramePreprocessor, tiles: list[TileState]
    ) -> None:
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
        results = self.classifier.classify_batch([crop for _, crop in valid])
        for tile in tiles:
            tile.context_score = 0.0
            tile.context_scores = {}
        for (tile, _crop), result in zip(valid, results, strict=False):
            tile.context_scores = dict(result.scores)
            tile.context_score = _risk(result.scores)

    def top_subtile(
        self, prepared: FramePreprocessor, region: Region
    ) -> FrameRegion | None:
        subtiles = prepared.subtiles(region)
        if not subtiles:
            return None
        if self.classifier is None:
            return subtiles[0]
        scored = [
            (_risk(self.classifier.classify(tile.image) or {}), index, tile)
            for index, tile in enumerate(subtiles)
        ]
        return min(scored, key=lambda item: (-item[0], item[1]))[2]
