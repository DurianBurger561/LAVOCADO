"""Context ranker protocol. Viddexa answers where to look, never whether to Block."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

CONTEXT_LABELS = ("normal", "porn", "hentai", "sexy", "drawing")


@dataclass(frozen=True, slots=True)
class ContextResult:
    scores: dict[str, float]
    model: str

    @property
    def porn_score(self) -> float:
        return float(self.scores.get("porn", 0.0) or 0.0)

    @property
    def rank_risk(self) -> float:
        return max(
            float(self.scores.get("porn", 0.0) or 0.0),
            float(self.scores.get("hentai", 0.0) or 0.0),
        )


class ContextRanker(Protocol):
    """Score tiles so the primary detector can check the riskiest region first."""

    @property
    def name(self) -> str: ...

    def classify_batch(self, frames: list[np.ndarray]) -> list[ContextResult]: ...
