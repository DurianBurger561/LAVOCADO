"""Selectable primary detectors."""

from app.vision.detectors.base import DetectionEvidence, PrimaryDetector
from app.vision.detectors.factory import (
    PRIMARY_NUDENET,
    PRIMARY_YOLO,
    PrimaryBundle,
    load_primary_bundle,
    normalize_primary_name,
)
from app.vision.detectors.nudenet import NudeNetPrimaryDetector
from app.vision.detectors.yolo11_nsfw import Yolo11NsfwDetector

__all__ = (
    "PRIMARY_NUDENET",
    "PRIMARY_YOLO",
    "DetectionEvidence",
    "NudeNetPrimaryDetector",
    "PrimaryBundle",
    "PrimaryDetector",
    "Yolo11NsfwDetector",
    "load_primary_bundle",
    "normalize_primary_name",
)
