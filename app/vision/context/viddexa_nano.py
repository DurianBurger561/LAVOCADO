"""Viddexa Nano tile-ranking adapter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app import config
from app.vision.context.viddexa import ViddexaContextRanker
from app.vision.context_classifier import (
    ClassificationPipeline,
    load_context_classifier,
)
from app.vision.model_assets import resolve_viddexa_model_path


def load_viddexa_nano(
    *,
    enabled: bool | None = True,
    data_dir: Path | None = None,
    pipeline_factory: Callable[..., ClassificationPipeline] | None = None,
) -> ViddexaContextRanker | None:
    classifier = load_context_classifier(
        enabled=enabled,
        model_name=config.CONTEXT_NANO_MODEL_NAME,
        revision=config.CONTEXT_NANO_MODEL_REVISION,
        local_model_path=resolve_viddexa_model_path(
            "viddexa_nano", data_dir=data_dir
        ),
        pipeline_factory=pipeline_factory,
    )
    if classifier is None:
        return None
    return ViddexaContextRanker(classifier, name="viddexa_nano")
