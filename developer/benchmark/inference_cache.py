"""Raw detector cache. Threshold and policy changes reuse stored detections."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RawInferenceResult:
    sample_id: str
    model_id: str
    model_revision: str
    input_size: int
    region_id: str
    detections: list[dict[str, Any]] = field(default_factory=list)
    preprocess_ms: float = 0.0
    inference_ms: float = 0.0
    postprocess_ms: float = 0.0
    tile_summary: dict[str, Any] | None = None
    context_scores: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RawInferenceResult:
        return cls(
            sample_id=str(payload.get("sample_id") or ""),
            model_id=str(payload.get("model_id") or ""),
            model_revision=str(payload.get("model_revision") or ""),
            input_size=int(payload.get("input_size") or 0),
            region_id=str(payload.get("region_id") or "full"),
            detections=list(payload.get("detections") or []),
            preprocess_ms=float(payload.get("preprocess_ms") or 0.0),
            inference_ms=float(payload.get("inference_ms") or 0.0),
            postprocess_ms=float(payload.get("postprocess_ms") or 0.0),
            tile_summary=payload.get("tile_summary"),
            context_scores=payload.get("context_scores"),
        )


def cache_key(
    *,
    sample_hash: str,
    model_id: str,
    model_revision: str,
    input_size: int,
    region_id: str,
    tile_geometry: str = "",
) -> str:
    payload = "|".join(
        [
            str(sample_hash),
            str(model_id),
            str(model_revision),
            str(int(input_size)),
            str(region_id),
            str(tile_geometry),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InferenceCache:
    """JSON files under dataset/cache. Stores detections, never source pixels."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> RawInferenceResult | None:
        path = self.path_for(key)
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return RawInferenceResult.from_dict(payload)

    def put(self, key: str, result: RawInferenceResult) -> Path:
        path = self.path_for(key)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle)
        path.write_bytes(temporary.read_bytes())
        temporary.unlink(missing_ok=True)
        return path

    def clear(self) -> None:
        for child in self.root.glob("*.json"):
            child.unlink(missing_ok=True)
