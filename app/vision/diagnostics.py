"""Thread-safe, privacy-safe in-memory protection diagnostics."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app import config


def _friendly_model_name(variant: str) -> str:
    if variant == "640m":
        return "NudeNet 640m"
    if variant == "320n-fallback":
        return "NudeNet 320n (fallback)"
    return f"NudeNet {variant}"


def _safe_region(value: object) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [int(coordinate) for coordinate in value]
    except (TypeError, ValueError):
        return None


class DiagnosticsStore:
    """Keep only explicitly allow-listed scalar detection metadata in memory."""

    def __init__(
        self,
        *,
        model_variant: str,
        inference_resolution: int | None,
        context_model: str,
        context_status: str,
    ) -> None:
        self._lock = Lock()
        self._snapshot: dict[str, Any] = {
            "protection_state": "STOPPED",
            "model": _friendly_model_name(model_variant),
            "model_variant": model_variant,
            "inference_resolution": inference_resolution,
            "context_model": context_model,
            "context_status": context_status,
            "last_scan_ms": None,
            "last_scan_at": None,
            "monitor_index": None,
            "nudenet": {
                "label": None,
                "score": 0.0,
                "threshold": None,
                "status": "none",
            },
            "context": {"label": None, "score": None},
            "decision_source": None,
            "temporal": [],
            "rescue": {
                "tile_index": None,
                "region": None,
                "pinned_tile_index": None,
                "pinned_checks_remaining": 0,
                "next_tile_index": 0,
            },
            "monitors": {},
        }

    def set_protection_state(self, state: str) -> None:
        """Update the service state without changing the latest scan."""

        with self._lock:
            self._snapshot["protection_state"] = str(state).upper()

    def record_scan(
        self,
        *,
        monitor_index: int,
        elapsed_ms: float,
        decision: dict[str, Any],
        temporal: tuple[bool, ...],
        rescue_status: dict[str, int | None] | None = None,
        scanned_at: str | None = None,
    ) -> None:
        """Extract a fixed safe schema from one completed monitor scan."""

        scan = {
            "last_scan_ms": round(max(0.0, float(elapsed_ms)), 1),
            "last_scan_at": scanned_at or datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "monitor_index": int(monitor_index),
            "nudenet": self._nudenet_summary(decision),
            "context": {
                "label": self._optional_string(decision.get("context_label")),
                "score": self._optional_float(decision.get("context_score")),
            },
            "decision_source": self._optional_string(decision.get("source")),
            "temporal": [int(value) for value in temporal],
            "rescue": self._rescue_summary(decision, rescue_status or {}),
        }
        with self._lock:
            monitors = self._snapshot["monitors"]
            assert isinstance(monitors, dict)
            monitors[str(monitor_index)] = deepcopy(scan)
            self._snapshot.update(deepcopy(scan))

    def snapshot(self) -> dict[str, Any]:
        """Return an isolated JSON-serializable copy of current diagnostics."""

        with self._lock:
            return deepcopy(self._snapshot)

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _nudenet_summary(cls, decision: dict[str, Any]) -> dict[str, Any]:
        label = cls._optional_string(decision.get("nudenet_label"))
        score = cls._optional_float(decision.get("nudenet_score"))
        threshold = cls._optional_float(decision.get("threshold"))

        if label is None:
            checkpoints = decision.get("check_points")
            if isinstance(checkpoints, list):
                valid = [
                    item
                    for item in checkpoints
                    if isinstance(item, dict) and item.get("class") is not None
                ]
                if valid:
                    strongest = max(
                        valid,
                        key=lambda item: float(item.get("score", 0.0)),
                    )
                    label = str(strongest["class"])
                    score = cls._optional_float(strongest.get("score"))
                    threshold = config.BLOCK_THRESHOLDS.get(label)

        score = 0.0 if score is None else score
        source = str(decision.get("source", ""))
        if label is None:
            status = "none"
        elif source == "nudenet_borderline":
            status = "borderline"
        elif source == "nudenet_borderline_context":
            status = "context_confirmed"
        elif source == "rescue_tile":
            status = "rescued"
        elif threshold is None:
            status = "observed"
        elif score >= threshold:
            status = "strong"
        elif score >= threshold - config.NUDENET_BORDERLINE_MARGIN:
            status = "borderline"
        else:
            status = "below_threshold"

        return {
            "label": label,
            "score": score,
            "threshold": threshold,
            "status": status,
        }

    @staticmethod
    def _rescue_summary(
        decision: dict[str, Any],
        rescue_status: dict[str, int | None],
    ) -> dict[str, Any]:
        tile_index = decision.get("rescue_tile_index")
        return {
            "tile_index": None if tile_index is None else int(tile_index),
            "region": _safe_region(decision.get("rescue_region")),
            "pinned_tile_index": rescue_status.get("pinned_tile_index"),
            "pinned_checks_remaining": int(
                rescue_status.get("pinned_checks_remaining") or 0
            ),
            "next_tile_index": int(rescue_status.get("next_tile_index") or 0),
        }
