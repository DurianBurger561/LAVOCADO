"""Optional local Viddexa tile-ranking adapter.

Viddexa scores tiles so the primary detector can check the highest-risk
region first. Its porn/hentai scores never trigger protection on their own
and are not a viewing-purpose (medical/art/education) classifier.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np
from PIL import Image

from app import config

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
    """Import the optional heavyweight dependency only when requested."""

    from transformers import pipeline

    return pipeline(task, **kwargs)


class ContextClassifier:
    """Normalize Viddexa's five-class image-classification output."""

    def __init__(
        self,
        classifier: ClassificationPipeline,
        *,
        model_name: str = config.CONTEXT_MODEL_NAME,
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
            LOGGER.exception("Viddexa context inference failed; ignoring context")
            return None

    @staticmethod
    def _to_rgb_image(bgr_image: np.ndarray) -> Image.Image:
        if not isinstance(bgr_image, np.ndarray):
            raise TypeError("context image must be a NumPy array")
        if bgr_image.ndim != 3 or bgr_image.shape[2] != 3:
            raise ValueError("context image must have shape (height, width, 3)")
        if bgr_image.size == 0:
            raise ValueError("context image cannot be empty")
        rgb_image = np.ascontiguousarray(bgr_image[:, :, ::-1], dtype=np.uint8)
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
    model_name: str = config.CONTEXT_MODEL_NAME,
    revision: str = config.CONTEXT_MODEL_REVISION,
    pipeline_factory: Callable[..., ClassificationPipeline] | None = None,
) -> ContextClassifier | None:
    """Load the pinned local classifier or return None without crashing."""

    if enabled is None:
        enabled = config.CONTEXT_MODEL_ENABLED
    if not enabled:
        LOGGER.info("Viddexa context model is disabled")
        return None

    factory = pipeline_factory or _create_transformers_pipeline
    try:
        classifier = factory(
            "image-classification",
            model=model_name,
            revision=revision,
            framework="pt",
            device=-1,
            use_fast=False,
        )
    except ImportError:
        LOGGER.warning(
            "Viddexa dependencies are unavailable; continuing NudeNet-only"
        )
        return None
    except Exception:
        LOGGER.exception(
            "Viddexa context model is unavailable; continuing NudeNet-only"
        )
        return None
    return ContextClassifier(classifier, model_name=model_name)
