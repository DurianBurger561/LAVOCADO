"""Vision settings schema. Values are experimental starting points, not Recommended."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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
CONFIRMATION_MODES = ("boolean", "evidence", "both")
THRESHOLD_STEPS = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75)

YOLO_LABEL_DEFAULTS: dict[str, tuple[float, float]] = {
    "breast": (0.55, 0.65),
    "nipple": (0.55, 0.65),
    "penis": (0.35, 0.45),
    "vagina": (0.35, 0.45),
    "vulva": (0.35, 0.45),
    "anus": (0.40, 0.50),
    "buttocks": (0.60, 0.70),
    "blowjob": (0.35, 0.45),
    "handjob": (0.35, 0.45),
    "sex": (0.35, 0.45),
    "make_love": (0.35, 0.45),
}
NUDENET_LABEL_DEFAULTS: dict[str, float] = {
    "FEMALE_GENITALIA_EXPOSED": 0.45,
    "MALE_GENITALIA_EXPOSED": 0.45,
    "ANUS_EXPOSED": 0.50,
    "FEMALE_BREAST_EXPOSED": 0.65,
    "BUTTOCKS_EXPOSED": 0.70,
}
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


def _bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


@dataclass(frozen=True, slots=True)
class DetectorSettings:
    primary: str = "nudenet_640m"
    full_input_size: int = 640
    tile_input_size: int = 640


@dataclass(frozen=True, slots=True)
class CaptureSettings:
    monitor_index: int | None = None


@dataclass(frozen=True, slots=True)
class UISettings:
    cooldown_seconds: float = 8.0


@dataclass(frozen=True, slots=True)
class ContextSettings:
    model: str = "viddexa_mini"
    tile_ranking: bool = True


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
    periodic_scan_interval: int = 8


@dataclass(frozen=True, slots=True)
class TemporalSettings:
    min_fresh_hits: int = 2
    window_size: int = 3
    evidence_threshold: float = 2.5
    decay: float = 0.5
    confirmation: str = "boolean"


@dataclass(frozen=True, slots=True)
class ShadowSettings:
    enabled: bool = False


@dataclass(frozen=True, slots=True)
class ThresholdSettings:
    nudenet_640m: dict[str, dict[str, float]] = field(default_factory=dict)
    yolo11_nsfw_small: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VisionSettings:
    schema_version: int = SCHEMA_VERSION
    preset: str = "balanced"
    detector: DetectorSettings = field(default_factory=DetectorSettings)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    ui: UISettings = field(default_factory=UISettings)
    context: ContextSettings = field(default_factory=ContextSettings)
    tiles: TileSettings = field(default_factory=TileSettings)
    recheck: RecheckSettings = field(default_factory=RecheckSettings)
    scan: ScanSettings = field(default_factory=ScanSettings)
    temporal: TemporalSettings = field(default_factory=TemporalSettings)
    shadow: ShadowSettings = field(default_factory=ShadowSettings)
    thresholds: ThresholdSettings = field(default_factory=ThresholdSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pair_from_strong(strong: float, margin: float = 0.10) -> dict[str, float]:
    strong_v = _closest(float(strong), THRESHOLD_STEPS)
    proposal = _closest(max(THRESHOLD_STEPS[0], strong_v - margin), THRESHOLD_STEPS)
    if proposal >= strong_v:
        index = THRESHOLD_STEPS.index(strong_v)
        if index == 0:
            strong_v = THRESHOLD_STEPS[1]
            proposal = THRESHOLD_STEPS[0]
        else:
            proposal = THRESHOLD_STEPS[index - 1]
    return {"proposal": proposal, "strong": strong_v}


def default_threshold_tables() -> ThresholdSettings:
    """Experimental per-model proposal/strong tables. Not Recommended values."""

    nudenet = {
        label: _pair_from_strong(strong)
        for label, strong in NUDENET_LABEL_DEFAULTS.items()
    }
    yolo = {
        label: {"proposal": proposal, "strong": strong}
        for label, (proposal, strong) in YOLO_LABEL_DEFAULTS.items()
    }
    return ThresholdSettings(nudenet_640m=nudenet, yolo11_nsfw_small=yolo)


def sanitize_threshold_tables(raw: object, defaults: ThresholdSettings) -> ThresholdSettings:
    payload = raw if isinstance(raw, dict) else {}
    return ThresholdSettings(
        nudenet_640m=_sanitize_label_table(
            payload.get("nudenet_640m"), defaults.nudenet_640m
        ),
        yolo11_nsfw_small=_sanitize_label_table(
            payload.get("yolo11_nsfw_small"), defaults.yolo11_nsfw_small
        ),
    )


def _sanitize_label_table(
    raw: object,
    defaults: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    incoming = raw if isinstance(raw, dict) else {}
    sanitized: dict[str, dict[str, float]] = {}
    for label, default_pair in defaults.items():
        item = incoming.get(label)
        if not isinstance(item, dict):
            item = {}
        strong = _closest(
            _clamp_float(item.get("strong"), 0.2, 0.9, default_pair["strong"]),
            THRESHOLD_STEPS,
        )
        proposal = _closest(
            _clamp_float(item.get("proposal"), 0.2, 0.9, default_pair["proposal"]),
            THRESHOLD_STEPS,
        )
        if proposal >= strong:
            index = THRESHOLD_STEPS.index(strong)
            if index == 0:
                strong = THRESHOLD_STEPS[1]
                proposal = THRESHOLD_STEPS[0]
            else:
                proposal = THRESHOLD_STEPS[index - 1]
        sanitized[str(label)] = {"proposal": proposal, "strong": strong}
    return sanitized


def default_vision_settings() -> VisionSettings:
    """Return the typed product defaults without a second config source."""

    return VisionSettings(thresholds=default_threshold_tables())


def sanitize_vision_settings(payload: dict[str, Any] | None) -> VisionSettings:
    """Clamp unknown or out-of-range values. Never accept arbitrary numbers."""

    base = default_vision_settings()
    if not isinstance(payload, dict):
        return base

    detector_raw = payload.get("detector") if isinstance(payload.get("detector"), dict) else {}
    capture_raw = payload.get("capture") if isinstance(payload.get("capture"), dict) else {}
    ui_raw = payload.get("ui") if isinstance(payload.get("ui"), dict) else {}
    context_raw = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    tiles_raw = payload.get("tiles") if isinstance(payload.get("tiles"), dict) else {}
    recheck_raw = payload.get("recheck") if isinstance(payload.get("recheck"), dict) else {}
    scan_raw = payload.get("scan") if isinstance(payload.get("scan"), dict) else {}
    temporal_raw = payload.get("temporal") if isinstance(payload.get("temporal"), dict) else {}
    shadow_raw = payload.get("shadow") if isinstance(payload.get("shadow"), dict) else {}
    thresholds = sanitize_threshold_tables(
        payload.get("thresholds"), base.thresholds
    )

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
    temporal_window = _clamp_int(
        temporal_raw.get("window_size"), 2, 8, base.temporal.window_size
    )

    return VisionSettings(
        schema_version=SCHEMA_VERSION,
        preset=preset,
        detector=DetectorSettings(
            primary=primary,
            full_input_size=full_input,
            tile_input_size=tile_input,
        ),
        capture=CaptureSettings(
            monitor_index=(
                None
                if capture_raw.get("monitor_index") is None
                else _clamp_int(capture_raw["monitor_index"], 1, 32, 1)
            ),
        ),
        ui=UISettings(
            cooldown_seconds=_clamp_float(
                ui_raw.get("cooldown_seconds"), 0.0, 120.0,
                base.ui.cooldown_seconds,
            ),
        ),
        context=ContextSettings(
            model=context_model,
            tile_ranking=_bool(
                context_raw.get("tile_ranking"), base.context.tile_ranking
            ),
        ),
        tiles=TileSettings(
            enabled=_bool(tiles_raw.get("enabled"), base.tiles.enabled),
            rows=rows,
            columns=columns,
            overlap=overlap,
            checks_per_scan=_clamp_int(
                tiles_raw.get("checks_per_scan"), 1, 2, base.tiles.checks_per_scan
            ),
            max_skip=_clamp_int(tiles_raw.get("max_skip"), 1, 8, base.tiles.max_skip),
        ),
        recheck=RecheckSettings(
            enabled=_bool(recheck_raw.get("enabled"), base.recheck.enabled),
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
            adaptive=_bool(scan_raw.get("adaptive"), base.scan.adaptive),
            active_monitor_priority=_bool(
                scan_raw.get("active_monitor_priority"), base.scan.active_monitor_priority
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
            periodic_scan_interval=_clamp_int(
                scan_raw.get("periodic_scan_interval"),
                1,
                120,
                base.scan.periodic_scan_interval,
            ),
        ),
        temporal=TemporalSettings(
            min_fresh_hits=_clamp_int(
                temporal_raw.get("min_fresh_hits"),
                1,
                min(3, temporal_window),
                base.temporal.min_fresh_hits,
            ),
            window_size=temporal_window,
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
            confirmation=_choice(
                temporal_raw.get("confirmation", base.temporal.confirmation),
                CONFIRMATION_MODES,
                base.temporal.confirmation,
            ),
        ),
        shadow=ShadowSettings(
            enabled=_bool(shadow_raw.get("enabled"), base.shadow.enabled),
        ),
        thresholds=thresholds,
    )


def merge_vision_settings(
    current: VisionSettings,
    patch: dict[str, Any],
) -> VisionSettings:
    payload = current.to_dict()
    for key, value in patch.items():
        if key == "thresholds" and isinstance(payload.get(key), dict) and isinstance(value, dict):
            payload[key] = _deep_merge_maps(payload[key], value)
        elif key in payload and isinstance(payload[key], dict) and isinstance(value, dict):
            merged = dict(payload[key])
            merged.update(value)
            payload[key] = merged
        elif key in payload or key in {"preset", "schema_version"}:
            payload[key] = value
    return sanitize_vision_settings(payload)


def _deep_merge_maps(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_maps(current, value)
        else:
            merged[key] = value
    return merged
