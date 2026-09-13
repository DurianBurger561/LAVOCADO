"""Vision settings schema. Values are experimental starting points, not Recommended."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app import config

SCHEMA_VERSION = 1

PRIMARY_DETECTORS = ("nudenet_640m", "yolo11_nsfw_small")
CONTEXT_MODELS = ("off", "viddexa_nano", "viddexa_mini")
PRESETS = ("low_cpu", "balanced", "high_recall")
INPUT_SIZES = (640, 960, 1280)
TILE_INPUT_SIZES = (640, 960)
GRID_CHOICES = ((2, 2), (3, 3))
OVERLAPS = (0.0, 0.10, 0.15, 0.20, 0.25)
CROP_EXPANSIONS = (1.25, 1.5, 1.75, 2.0, 2.5)
PROPOSAL_MARGINS = (0.05, 0.10, 0.15, 0.20)
CHANGE_SENSITIVITIES = (0.005, 0.01, 0.02, 0.05)
EVIDENCE_DECAYS = (0.3, 0.5, 0.7)
EVIDENCE_THRESHOLDS = (1.5, 2.0, 2.5, 3.0, 3.5)
SCAN_SPEEDS = {
    "slow": (1000, 250),
    "balanced": (750, 150),
    "fast": (500, 100),
}


def _closest(value: float, choices: tuple[float, ...]) -> float:
    return min(choices, key=lambda item: abs(item - float(value)))


def _clamp_int(value: object, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _clamp_float(value: object, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # noqa: PLR0124 - NaN check
        return default
    return max(minimum, min(maximum, number))


def _choice(value: object, choices: tuple[str, ...], default: str) -> str:
    raw = str(value or default).strip().lower().replace("-", "_")
    return raw if raw in choices else default


@dataclass(frozen=True, slots=True)
class DetectorSettings:
    primary: str = "nudenet_640m"
    full_input_size: int = 640
    tile_input_size: int = 640


@dataclass(frozen=True, slots=True)
class ContextSettings:
    model: str = "viddexa_mini"
    tile_ranking: bool = True
    borderline_assistance: bool = True


@dataclass(frozen=True, slots=True)
class TileSettings:
    enabled: bool = True
    rows: int = 2
    columns: int = 2
    overlap: float = 0.15
    checks_per_scan: int = 1
    max_skip: int = 3


@dataclass(frozen=True, slots=True)
class RecheckSettings:
    enabled: bool = True
    crop_expansion: float = 1.75
    proposal_margin: float = 0.10


@dataclass(frozen=True, slots=True)
class ScanSettings:
    normal_interval_ms: int = 750
    candidate_interval_ms: int = 150
    adaptive: bool = True
    active_monitor_priority: bool = True
    vision_budget_ms: int = 250
    change_sensitivity: float = 0.01


@dataclass(frozen=True, slots=True)
class TemporalSettings:
    min_fresh_hits: int = 2
    window_size: int = 3
    evidence_threshold: float = 2.5
    decay: float = 0.5


@dataclass(frozen=True, slots=True)
class ShadowSettings:
    enabled: bool = False
    detector: str = "yolo11_nsfw_small"


@dataclass(frozen=True, slots=True)
class VisionSettings:
    schema_version: int = SCHEMA_VERSION
    preset: str = "balanced"
    detector: DetectorSettings = field(default_factory=DetectorSettings)
    context: ContextSettings = field(default_factory=ContextSettings)
    tiles: TileSettings = field(default_factory=TileSettings)
    recheck: RecheckSettings = field(default_factory=RecheckSettings)
    scan: ScanSettings = field(default_factory=ScanSettings)
    temporal: TemporalSettings = field(default_factory=TemporalSettings)
    shadow: ShadowSettings = field(default_factory=ShadowSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_vision_settings() -> VisionSettings:
    """Experimental defaults matching current main behavior where possible."""

    context_enabled = bool(config.CONTEXT_MODEL_ENABLED)
    return VisionSettings(
        detector=DetectorSettings(
            primary="nudenet_640m",
            full_input_size=int(config.MODEL_FRAME_MAX_EDGE),
            tile_input_size=int(config.NUDENET_INFERENCE_RESOLUTION),
        ),
        context=ContextSettings(
            model="viddexa_mini" if context_enabled else "off",
            tile_ranking=bool(config.RESCUE_ENABLED and context_enabled),
        ),
        tiles=TileSettings(
            enabled=bool(config.RESCUE_ENABLED),
            rows=int(config.RESCUE_TILE_ROWS),
            columns=int(config.RESCUE_TILE_COLUMNS),
        ),
        recheck=RecheckSettings(
            crop_expansion=float(config.CONTEXT_CROP_EXPANSION),
            proposal_margin=float(config.NUDENET_BORDERLINE_MARGIN),
        ),
        scan=ScanSettings(
            normal_interval_ms=round(float(config.CHECK_INTERVAL) * 1000),
            change_sensitivity=float(config.CHANGE_RATIO_THRESHOLD),
        ),
        temporal=TemporalSettings(
            min_fresh_hits=int(config.CONFIRMATION_REQUIRED_HITS),
            window_size=int(config.CONFIRMATION_WINDOW_SIZE),
        ),
    )


def sanitize_vision_settings(payload: dict[str, Any] | None) -> VisionSettings:
    """Clamp unknown or out-of-range values. Never accept arbitrary numbers."""

    base = default_vision_settings()
    if not isinstance(payload, dict):
        return base

    detector_raw = payload.get("detector") if isinstance(payload.get("detector"), dict) else {}
    context_raw = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    tiles_raw = payload.get("tiles") if isinstance(payload.get("tiles"), dict) else {}
    recheck_raw = payload.get("recheck") if isinstance(payload.get("recheck"), dict) else {}
    scan_raw = payload.get("scan") if isinstance(payload.get("scan"), dict) else {}
    temporal_raw = payload.get("temporal") if isinstance(payload.get("temporal"), dict) else {}
    shadow_raw = payload.get("shadow") if isinstance(payload.get("shadow"), dict) else {}

    primary = _choice(detector_raw.get("primary", base.detector.primary), PRIMARY_DETECTORS, base.detector.primary)
    full_input = int(_closest(
        _clamp_int(detector_raw.get("full_input_size"), 320, 1920, base.detector.full_input_size),
        tuple(float(size) for size in INPUT_SIZES),
    ))
    tile_input = int(_closest(
        _clamp_int(detector_raw.get("tile_input_size"), 320, 1280, base.detector.tile_input_size),
        tuple(float(size) for size in TILE_INPUT_SIZES),
    ))
    if primary == "nudenet_640m":
        full_input = 640
        tile_input = 640

    context_model = _choice(context_raw.get("model", base.context.model), CONTEXT_MODELS, base.context.model)
    rows = _clamp_int(tiles_raw.get("rows"), 2, 3, base.tiles.rows)
    columns = _clamp_int(tiles_raw.get("columns"), 2, 3, base.tiles.columns)
    if (rows, columns) not in GRID_CHOICES:
        rows, columns = 2, 2
    overlap = _closest(
        _clamp_float(tiles_raw.get("overlap"), 0.0, 0.4, base.tiles.overlap),
        OVERLAPS,
    )
    crop = _closest(
        _clamp_float(recheck_raw.get("crop_expansion"), 1.0, 3.0, base.recheck.crop_expansion),
        CROP_EXPANSIONS,
    )
    proposal_margin = _closest(
        _clamp_float(
            recheck_raw.get("proposal_margin"),
            0.0,
            0.4,
            base.recheck.proposal_margin,
        ),
        PROPOSAL_MARGINS,
    )
    preset = _choice(payload.get("preset", base.preset), PRESETS, base.preset)
    shadow_detector = _choice(
        shadow_raw.get("detector", base.shadow.detector),
        PRIMARY_DETECTORS,
        base.shadow.detector,
    )

    return VisionSettings(
        schema_version=SCHEMA_VERSION,
        preset=preset,
        detector=DetectorSettings(
            primary=primary,
            full_input_size=full_input,
            tile_input_size=tile_input,
        ),
        context=ContextSettings(
            model=context_model,
            tile_ranking=bool(context_raw.get("tile_ranking", base.context.tile_ranking)),
            borderline_assistance=bool(
                context_raw.get("borderline_assistance", base.context.borderline_assistance)
            ),
        ),
        tiles=TileSettings(
            enabled=bool(tiles_raw.get("enabled", base.tiles.enabled)),
            rows=rows,
            columns=columns,
            overlap=overlap,
            checks_per_scan=_clamp_int(
                tiles_raw.get("checks_per_scan"), 1, 2, base.tiles.checks_per_scan
            ),
            max_skip=_clamp_int(tiles_raw.get("max_skip"), 1, 8, base.tiles.max_skip),
        ),
        recheck=RecheckSettings(
            enabled=bool(recheck_raw.get("enabled", base.recheck.enabled)),
            crop_expansion=crop,
            proposal_margin=proposal_margin,
        ),
        scan=ScanSettings(
            normal_interval_ms=_clamp_int(
                scan_raw.get("normal_interval_ms"), 250, 2000, base.scan.normal_interval_ms
            ),
            candidate_interval_ms=_clamp_int(
                scan_raw.get("candidate_interval_ms"), 50, 500, base.scan.candidate_interval_ms
            ),
            adaptive=bool(scan_raw.get("adaptive", base.scan.adaptive)),
            active_monitor_priority=bool(
                scan_raw.get("active_monitor_priority", base.scan.active_monitor_priority)
            ),
            vision_budget_ms=_clamp_int(
                scan_raw.get("vision_budget_ms"), 50, 1000, base.scan.vision_budget_ms
            ),
            change_sensitivity=_closest(
                _clamp_float(
                    scan_raw.get("change_sensitivity"),
                    0.0,
                    1.0,
                    base.scan.change_sensitivity,
                ),
                CHANGE_SENSITIVITIES,
            ),
        ),
        temporal=TemporalSettings(
            min_fresh_hits=_clamp_int(
                temporal_raw.get("min_fresh_hits"), 1, 3, base.temporal.min_fresh_hits
            ),
            window_size=_clamp_int(
                temporal_raw.get("window_size"), 2, 8, base.temporal.window_size
            ),
            evidence_threshold=_closest(
                _clamp_float(
                    temporal_raw.get("evidence_threshold"),
                    0.5,
                    10.0,
                    base.temporal.evidence_threshold,
                ),
                EVIDENCE_THRESHOLDS,
            ),
            decay=_closest(
                _clamp_float(temporal_raw.get("decay"), 0.1, 0.9, base.temporal.decay),
                EVIDENCE_DECAYS,
            ),
        ),
        shadow=ShadowSettings(
            enabled=bool(shadow_raw.get("enabled", False)),
            detector=shadow_detector,
        ),
    )


def merge_vision_settings(
    current: VisionSettings,
    patch: dict[str, Any],
) -> VisionSettings:
    payload = current.to_dict()
    for key, value in patch.items():
        if key in payload and isinstance(payload[key], dict) and isinstance(value, dict):
            merged = dict(payload[key])
            merged.update(value)
            payload[key] = merged
        elif key in payload or key in {"preset", "schema_version"}:
            payload[key] = value
    return sanitize_vision_settings(payload)
