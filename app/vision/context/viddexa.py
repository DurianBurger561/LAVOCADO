"""Shared Viddexa ranker wrapping the existing local classifier."""

from __future__ import annotations

import numpy as np

from app.vision.context.base import CONTEXT_LABELS, ContextResult
from app.vision.context_classifier import ContextClassifier


class ViddexaContextRanker:
    """Batch-classify tiles. A failed frame degrades to zero scores, not a veto."""

    def __init__(self, classifier: ContextClassifier, name: str) -> None:
        self._classifier = classifier
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return str(getattr(self._classifier, "model_name", self._name))

    def classify_batch(self, frames: list[np.ndarray]) -> list[ContextResult]:
        results: list[ContextResult] = []
        for frame in frames:
            scores = self.classify(frame)
            if scores is None:
                results.append(
                    ContextResult(
                        scores=dict.fromkeys(CONTEXT_LABELS, 0.0),
                        model=self._name,
                    )
                )
            else:
                results.append(ContextResult(scores=scores, model=self._name))
        return results

    def classify(self, bgr_image: np.ndarray) -> dict[str, float] | None:
        return self._classifier.classify(bgr_image)
