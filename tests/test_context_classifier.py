"""Tests for the optional Viddexa context adapter."""

import unittest
from typing import Any
from unittest.mock import Mock

import numpy as np
from PIL import Image

from app.vision.context_classifier import (
    CONTEXT_LABELS,
    ContextClassifier,
    load_context_classifier,
)


class FakePipeline:
    def __init__(
        self,
        predictions: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.predictions = predictions or []
        self.error = error
        self.received_image: Image.Image | None = None
        self.received_top_k: int | None | str = "unset"

    def __call__(
        self,
        image: Image.Image,
        *,
        top_k: int | None,
    ) -> list[dict[str, Any]]:
        self.received_image = image
        self.received_top_k = top_k
        if self.error is not None:
            raise self.error
        return self.predictions


class ContextClassifierTests(unittest.TestCase):
    def test_normalizes_all_labels_and_maps_safe_to_normal(self) -> None:
        pipeline = FakePipeline(
            [
                {"label": "safe", "score": 0.72},
                {"label": "Porn", "score": 0.18},
                {"label": "SEXY", "score": 0.10},
            ]
        )
        classifier = ContextClassifier(pipeline)

        scores = classifier.classify(np.zeros((2, 3, 3), dtype=np.uint8))

        self.assertIsNotNone(scores)
        assert scores is not None
        self.assertEqual(tuple(scores), CONTEXT_LABELS)
        self.assertEqual(scores["normal"], 0.72)
        self.assertEqual(scores["porn"], 0.18)
        self.assertEqual(scores["hentai"], 0.0)
        self.assertEqual(scores["sexy"], 0.10)
        self.assertEqual(scores["drawing"], 0.0)
        self.assertIsNone(pipeline.received_top_k)

    def test_converts_capture_bgr_to_pipeline_rgb(self) -> None:
        pipeline = FakePipeline()
        classifier = ContextClassifier(pipeline)
        bgr_image = np.array([[[10, 20, 30]]], dtype=np.uint8)

        classifier.classify(bgr_image)

        assert pipeline.received_image is not None
        self.assertEqual(pipeline.received_image.mode, "RGB")
        self.assertEqual(pipeline.received_image.getpixel((0, 0)), (30, 20, 10))

    def test_inference_failure_returns_none(self) -> None:
        classifier = ContextClassifier(FakePipeline(error=RuntimeError("failed")))

        with self.assertLogs("app.vision.context_classifier", level="ERROR"):
            result = classifier.classify(
                np.zeros((2, 2, 3), dtype=np.uint8)
            )

        self.assertIsNone(result)

    def test_loads_pinned_model_with_pytorch(self) -> None:
        pipeline = FakePipeline()
        factory = Mock(return_value=pipeline)

        classifier = load_context_classifier(pipeline_factory=factory)

        self.assertIsNotNone(classifier)
        factory.assert_called_once_with(
            "image-classification",
            model="viddexa/nsfw-detection-2-mini",
            revision="15f61cddc0a1a2a9176f018fb6838ef92c8163cc",
            framework="pt",
            device=-1,
            use_fast=False,
        )

    def test_disabled_context_does_not_load_dependencies(self) -> None:
        factory = Mock()

        classifier = load_context_classifier(
            enabled=False,
            pipeline_factory=factory,
        )

        self.assertIsNone(classifier)
        factory.assert_not_called()

    def test_load_failure_returns_none_for_nudenet_only_mode(self) -> None:
        factory = Mock(side_effect=ImportError("transformers missing"))

        with self.assertLogs("app.vision.context_classifier", level="ERROR"):
            classifier = load_context_classifier(pipeline_factory=factory)

        self.assertIsNone(classifier)


if __name__ == "__main__":
    unittest.main()
