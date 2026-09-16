"""Load Off / Viddexa Nano / Viddexa Mini without affecting the primary detector."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app.vision.context.base import ContextRanker
from app.vision.context.off import OffContextRanker
from app.vision.context.viddexa_mini import load_viddexa_mini
from app.vision.context.viddexa_nano import load_viddexa_nano
from app.vision.context_classifier import ClassificationPipeline

LOGGER = logging.getLogger(__name__)

CONTEXT_OFF = "off"
CONTEXT_NANO = "viddexa_nano"
CONTEXT_MINI = "viddexa_mini"
KNOWN_CONTEXT = frozenset({CONTEXT_OFF, CONTEXT_NANO, CONTEXT_MINI})


def normalize_context_name(name: str | None, *, enabled: bool = True) -> str:
    if not enabled:
        return CONTEXT_OFF
    raw = str(name or CONTEXT_MINI).strip().lower().replace("-", "_")
    aliases = {
        "off": CONTEXT_OFF,
        "none": CONTEXT_OFF,
        "disabled": CONTEXT_OFF,
        "nano": CONTEXT_NANO,
        "viddexa_nano": CONTEXT_NANO,
        "mini": CONTEXT_MINI,
        "viddexa_mini": CONTEXT_MINI,
        "viddexa": CONTEXT_MINI,
    }
    return aliases.get(raw, CONTEXT_MINI if raw not in KNOWN_CONTEXT else raw)


def load_context_ranker(
    name: str | None = None,
    *,
    enabled: bool = True,
    data_dir: Path | None = None,
    pipeline_factory: Callable[..., ClassificationPipeline] | None = None,
) -> ContextRanker:
    """Always return a ranker. Missing weights become Off, never disable tiles."""

    requested = normalize_context_name(name, enabled=enabled)
    if requested == CONTEXT_OFF:
        return OffContextRanker()

    loader = load_viddexa_nano if requested == CONTEXT_NANO else load_viddexa_mini
    ranker = loader(
        enabled=True, data_dir=data_dir, pipeline_factory=pipeline_factory
    )
    if ranker is not None:
        return ranker
    LOGGER.warning(
        "Region ranker %s is unavailable; tile ranking will use change + age",
        requested,
    )
    return OffContextRanker()
