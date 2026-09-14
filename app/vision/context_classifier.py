"""Local Viddexa region-ranking adapter.

Viddexa scores tiles so the primary detector can check the highest-risk
region first. Its porn/hentai scores never trigger protection on their own
and are not a viewing-purpose (medical/art/education) classifier.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from app.vision.model_manifest import VIDDEXA_MINI_REPO
from app.vision.preprocessor import FramePreprocessor

LOGGER = logging.getLogger(__name__)
CONTEXT_LABELS = ("normal", "porn", "hentai", "sexy", "drawing")
LABEL_ALIASES = {"safe": "normal"}


class ClassificationPipeline(Protocol):
    """Subset of a Transformers image-classification pipeline used here."""

    def __call__(
        self,
        image: Image.Image,
        *,
        top_k: int | None,
    ) -> list[dict[str, Any]]:
        ...


def _create_transformers_pipeline(
    task: str,
    **kwargs: object,
) -> ClassificationPipeline:
    """Import the bundled heavyweight dependency only when requested."""

    from transformers import pipeline

    return pipeline(task, **kwargs)


class ContextClassifier:
    """Normalize Viddexa's five-class region-ranking signal."""

    def __init__(
        self,
        classifier: ClassificationPipeline,
        *,
        model_name: str = VIDDEXA_MINI_REPO,
    ) -> None:
        self._classifier = classifier
        self.model_name = model_name

    def classify(self, bgr_image: np.ndarray) -> dict[str, float] | None:
        """Classify an in-memory BGR image, degrading safely on failure."""

        try:
            image = self._to_rgb_image(bgr_image)
            predictions = self._classifier(image, top_k=None)
            return self._normalize_predictions(predictions)
        except Exception:
            LOGGER.exception("Viddexa region-ranking inference failed; ignoring scores")
            return None

    @staticmethod
    def _to_rgb_image(bgr_image: np.ndarray) -> Image.Image:
        if not isinstance(bgr_image, np.ndarray):
            raise TypeError("ranker image must be a NumPy array")
        if bgr_image.ndim != 3 or bgr_image.shape[2] != 3:
            raise ValueError("ranker image must have shape (height, width, 3)")
        if bgr_image.size == 0:
            raise ValueError("ranker image cannot be empty")
        rgb_image = FramePreprocessor.to_rgb(bgr_image)
        return Image.fromarray(rgb_image, mode="RGB")

    @staticmethod
    def _normalize_predictions(
        predictions: list[dict[str, Any]],
    ) -> dict[str, float]:
        scores = dict.fromkeys(CONTEXT_LABELS, 0.0)
        for prediction in predictions:
            raw_label = str(prediction.get("label", "")).strip().lower()
            label = LABEL_ALIASES.get(raw_label, raw_label)
            if label not in scores:
                continue
            score = min(1.0, max(0.0, float(prediction.get("score", 0.0))))
            scores[label] = max(scores[label], score)
        return scores


def load_context_classifier(
    *,
    enabled: bool | None = None,
    model_name: str = VIDDEXA_MINI_REPO,
    local_model_path: Path | None = None,
    pipeline_factory: Callable[..., ClassificationPipeline] | None = None,
) -> ContextClassifier | None:
    """Load the pinned local classifier or return None without crashing."""

    if enabled is False:
        LOGGER.info("Viddexa region ranker is disabled")
        return None
    if local_model_path is None or not Path(local_model_path).is_dir():
        LOGGER.warning("Local Viddexa region-ranker files are unavailable")
        return None

    factory = pipeline_factory or _create_transformers_pipeline
    try:
        classifier = factory(
            "image-classification",
            model=str(local_model_path),
            framework="pt",
            device=-1,
            use_fast=False,
            model_kwargs={"local_files_only": True},
        )
    except ImportError:
        LOGGER.warning(
            "Viddexa dependencies are unavailable; continuing without region ranking"
        )
        return None
    except Exception:
        LOGGER.exception(
            "Viddexa region ranker is unavailable; continuing without region ranking"
        )
        return None
    return ContextClassifier(classifier, model_name=model_name)
