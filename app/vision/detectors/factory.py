"""Load the configured primary detector, falling back to NudeNet."""

from __future__ import annotations

import logging
from pathlib import Path

from app.vision.detectors.base import PrimaryDetector
from app.vision.detectors.nudenet import NudeNetPrimaryDetector
from app.vision.detectors.yolo11_nsfw import load_yolo11_nsfw_detector

LOGGER = logging.getLogger(__name__)

PRIMARY_NUDENET = "nudenet_640m"
PRIMARY_YOLO = "yolo11_nsfw_small"
KNOWN_PRIMARIES = frozenset({PRIMARY_NUDENET, PRIMARY_YOLO})


class PrimaryBundle:
    """Runtime primary detector and its selection status."""

    def __init__(
        self,
        *,
        primary: PrimaryDetector,
        requested: str,
        fallback_from: str | None = None,
        yolo_status: str,
    ) -> None:
        self.primary = primary
        self.requested = requested
        self.fallback_from = fallback_from
        self.yolo_status = yolo_status

    @property
    def name(self) -> str:
        return self.primary.name


def normalize_primary_name(name: str | None) -> str:
    raw = str(name or PRIMARY_NUDENET).strip().lower().replace("-", "_")
    aliases = {
        "nudenet": PRIMARY_NUDENET,
        "nudenet_640": PRIMARY_NUDENET,
        "nudenet_640m": PRIMARY_NUDENET,
        "yolo": PRIMARY_YOLO,
        "yolo11": PRIMARY_YOLO,
        "yolo11_nsfw": PRIMARY_YOLO,
        "yolo11_nsfw_small": PRIMARY_YOLO,
    }
    return aliases.get(raw, PRIMARY_NUDENET if raw not in KNOWN_PRIMARIES else raw)


def load_primary_bundle(
    name: str | None = None,
    *,
    yolo_enabled: bool | None = None,
    full_input_size: int = 640,
    data_dir: Path | None = None,
) -> PrimaryBundle:
    """Load the selected primary. YOLO failure always falls back to NudeNet."""

    requested = normalize_primary_name(name)
    if requested == PRIMARY_YOLO:
        yolo = load_yolo11_nsfw_detector(
            enabled=True if yolo_enabled is None else yolo_enabled,
            default_input_size=full_input_size,
            data_dir=data_dir,
        )
        if yolo is not None:
            return PrimaryBundle(
                primary=yolo,
                requested=requested,
                yolo_status="available",
            )
        LOGGER.warning(
            "YOLO11 NSFW Small is unavailable; falling back to NudeNet 640m"
        )
        nudenet = NudeNetPrimaryDetector(data_dir=data_dir)
        return PrimaryBundle(
            primary=nudenet,
            requested=requested,
            fallback_from=PRIMARY_YOLO,
            yolo_status="unavailable",
        )

    nudenet = NudeNetPrimaryDetector(data_dir=data_dir)
    return PrimaryBundle(
        primary=nudenet,
        requested=requested,
        yolo_status="disabled",
    )
