"""Thread-safe, privacy-safe in-memory protection diagnostics."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app import config
from app.context.models import (
    ContextPolicyAction,
    ContextPolicyResult,
    ForegroundContext,
    WebsiteContextState,
)
from app.platforms.capture.models import CaptureBackendStatus
from app.vision.violation_policy import VisualViolationDecision, evidence_to_dict


def _friendly_model_name(variant: str) -> str:
    raw = str(variant or "")
    mapping = {
        "640m": "NudeNet 640m",
        "nudenet_640m": "NudeNet 640m",
        "320n-fallback": "NudeNet 320n (fallback)",
        "nudenet_320n": "NudeNet 320n (fallback)",
        "yolo11-nsfw-small": "YOLO11 NSFW Small",
        "yolo11_nsfw_small": "YOLO11 NSFW Small",
    }
    if raw in mapping:
        return mapping[raw]
    if raw.startswith("yolo"):
        return "YOLO11 NSFW Small"
    return f"NudeNet {raw}" if raw else "NudeNet 640m"


def _safe_region(value: object) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [int(coordinate) for coordinate in value]
    except (TypeError, ValueError):
        return None


def _decision_diagnostics_payload(decision: VisualViolationDecision) -> dict[str, Any]:
    """Serialize a typed decision at the diagnostics boundary only."""

    source = decision.reason_codes[0] if decision.reason_codes else ""
    return {
        "source": source,
        "classification": decision.classification.value,
        "label": decision.label,
        "nudenet_label": decision.label,
        "nudenet_score": decision.confidence,
        "threshold": decision.threshold,
        "context_label": decision.context_label,
        "context_score": decision.context_score,
        "rescue_tile_index": decision.rescue_tile_index,
        "rescue_region": decision.primary_region,
        "track_id": decision.track_id,
        "track_fresh_hits": decision.track_fresh_hits,
        "track_evidence": decision.track_evidence,
        "scan_mode": decision.scan_mode,
        "scan_interval_ms": decision.scan_interval_ms,
        "shadow": decision.shadow,
        "evidence": [evidence_to_dict(item) for item in decision.evidence],
    }


class DiagnosticsStore:
    """Keep only explicitly allow-listed scalar detection metadata in memory."""

    def __init__(
        self,
        *,
        model_variant: str,
        inference_resolution: int | None,
        context_model: str,
        context_status: str,
        yolo_status: str = "disabled",
        primary_detector: str | None = None,
        models: dict[str, str] | None = None,
    ) -> None:
        self._lock = Lock()
        primary = primary_detector or model_variant
        self._snapshot: dict[str, Any] = {
            "protection_state": "STOPPED",
            "model": _friendly_model_name(model_variant),
            "model_variant": model_variant,
            "primary_detector": primary,
            "inference_resolution": inference_resolution,
            "context_model": context_model,
            "context_status": context_status,
            "yolo_status": yolo_status,
            "models": dict(models or {}),
            "foreground_context": {
                "application_available": False,
                "is_browser": None,
                "website_state": "unavailable",
                "application_rule": "normal",
                "website_rule": "normal",
                "effective_policy": "normal",
                "vision_called": True,
            },
            "capture": {
                "preferred_backend": None,
                "active_backend": None,
                "fallback": False,
                "fallback_reason": None,
                "healthy": False,
                "error": None,
                "session": None,
                "monitor_count": 0,
                "frame_age_ms": None,
            },
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
            "classification": None,
            "temporal": [],
            "rescue": {
                "tile_index": None,
                "region": None,
                "pinned_tile_index": None,
                "pinned_checks_remaining": 0,
                "next_tile_index": 0,
            },
            "scan": {
                "mode": "monitoring",
                "total_ms": None,
                "target_interval_ms": None,
            },
            "full": {
                "status": "none",
                "label": None,
                "confidence": 0.0,
            },
            "tiles": {"ranking": []},
            "track": {
                "active": False,
                "source": None,
                "fresh_hits": 0,
                "evidence": 0.0,
            },
            "shadow": None,
            "monitors": {},
        }

    def set_protection_state(self, state: str) -> None:
        """Update the service state without changing the latest scan."""

        with self._lock:
            self._snapshot["protection_state"] = str(state).upper()

    def record_capture(self, status: CaptureBackendStatus) -> None:
        """Store an allow-listed, privacy-safe capture health snapshot."""

        capture = {
            "preferred_backend": self._optional_string(status.preferred_backend),
            "active_backend": self._optional_string(status.active_backend),
            "fallback": bool(status.fallback),
            "fallback_reason": self._optional_string(status.fallback_reason),
            "healthy": bool(status.healthy),
            "error": self._optional_string(status.error),
            "session": self._optional_string(status.session),
            "monitor_count": max(0, int(status.monitor_count)),
            "frame_age_ms": self._nonnegative_float(status.frame_age_ms),
        }
        with self._lock:
            self._snapshot["capture"] = capture

    def record_foreground_context(
        self,
        context: ForegroundContext | None,
        policy: ContextPolicyResult | None,
        *,
        effective_override: ContextPolicyAction | None = None,
    ) -> None:
        """Publish only rule actions and coarse availability, never context identity."""

        application_available = bool(
            context is not None and context.application.identifier
        )
        if not application_available:
            browser = None
            website_state = "unavailable"
        elif context is not None and context.is_browser:
            browser = True
            website_state = (
                "known"
                if context.website is not None
                and context.website.state is WebsiteContextState.KNOWN
                else "unknown"
            )
        else:
            browser = False
            website_state = "not_browser"

        foreground = {
            "application_available": application_available,
            "is_browser": browser,
            "website_state": website_state,
            "application_rule": (
                policy.app_action.value if policy is not None else "normal"
            ),
            "website_rule": (
                policy.website_action.value if policy is not None else "normal"
            ),
            "effective_policy": (
                effective_override.value if effective_override is not None
                else policy.action.value if policy is not None else "normal"
            ),
        }
        foreground["vision_called"] = foreground["effective_policy"] == "normal"
        with self._lock:
            self._snapshot["foreground_context"] = foreground

    def record_scan(
        self,
        *,
        monitor_index: int,
        elapsed_ms: float,
        decision: VisualViolationDecision,
        temporal: tuple[bool, ...],
        rescue_status: dict[str, int | None] | None = None,
        scanned_at: str | None = None,
    ) -> None:
        """Extract a fixed safe schema from one completed monitor scan."""

        payload = _decision_diagnostics_payload(decision)
        scan = {
            "last_scan_ms": round(max(0.0, float(elapsed_ms)), 1),
            "last_scan_at": scanned_at or datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "monitor_index": int(monitor_index),
            "nudenet": self._nudenet_summary(payload),
            "context": {
                "label": self._optional_string(payload.get("context_label")),
                "score": self._optional_float(payload.get("context_score")),
            },
            "decision_source": self._optional_string(payload.get("source")),
            "classification": self._optional_string(payload.get("classification")),
            "temporal": [int(value) for value in temporal],
            "rescue": self._rescue_summary(payload, rescue_status or {}),
            "scan": {
                "mode": self._optional_string(payload.get("scan_mode")) or "monitoring",
                "total_ms": round(max(0.0, float(elapsed_ms)), 1),
                "target_interval_ms": self._optional_float(
                    payload.get("scan_interval_ms")
                ),
            },
            "full": self._nudenet_summary(payload),
            "tiles": {
                "ranking": self._tile_ranking(payload),
            },
            "track": {
                "active": payload.get("track_id") is not None,
                "source": self._optional_string(payload.get("source")),
                "fresh_hits": int(payload.get("track_fresh_hits") or 0),
                "evidence": self._optional_float(payload.get("track_evidence")) or 0.0,
            },
            "shadow": payload.get("shadow") if isinstance(payload.get("shadow"), dict) else None,
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
    def _nonnegative_float(cls, value: object) -> float | None:
        number = cls._optional_float(value)
        return None if number is None else round(max(0.0, number), 1)

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
        elif source in {"nudenet_roi", "anatomy_roi"}:
            status = "roi_confirmed"
        elif source == "anatomy_candidate":
            status = "borderline"
        elif source == "nudenet_borderline_context":
            status = "context_confirmed"
        elif source == "rescue_tile":
            status = "rescued"
        elif source in {"yolo_sexual_act", "yolo_sexual_act_roi"}:
            status = "strong"
        elif source == "sexual_act_candidate":
            status = "borderline"
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

    @staticmethod
    def _tile_ranking(decision: dict[str, Any]) -> list[dict[str, Any]]:
        ranking = decision.get("tile_ranking")
        if not isinstance(ranking, list):
            return []
        safe: list[dict[str, Any]] = []
        for item in ranking:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            priority = item.get("priority")
            try:
                safe.append(
                    {
                        "index": int(index),
                        "priority": float(priority),
                    }
                )
            except (TypeError, ValueError):
                continue
        return safe[:9]
