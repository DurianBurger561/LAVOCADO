"""Validate monitor geometry passed to the isolated macOS overlay child."""

from __future__ import annotations

import json
from dataclasses import asdict

from app.platforms.capture import MonitorInfo


def encode_monitor(monitor: MonitorInfo) -> str:
    validate_monitor(monitor)
    return json.dumps(asdict(monitor), separators=(",", ":"))


def decode_monitor(raw: str) -> MonitorInfo:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid overlay monitor payload") from error
    if not isinstance(payload, dict) or set(payload) != {
        "id", "index", "left", "top", "width", "height", "is_primary"
    }:
        raise ValueError("Invalid overlay monitor payload")
    try:
        monitor = MonitorInfo(**payload)
    except TypeError as error:
        raise ValueError("Invalid overlay monitor payload") from error
    validate_monitor(monitor)
    return monitor


def validate_monitor(monitor: MonitorInfo) -> None:
    if not isinstance(monitor.id, str) or not monitor.id:
        raise ValueError("Overlay monitor id must be nonempty")
    for name in ("index", "left", "top", "width", "height"):
        if type(getattr(monitor, name)) is not int:
            raise ValueError(f"Overlay monitor {name} must be an integer")
    if monitor.index < 1 or monitor.width < 1 or monitor.height < 1:
        raise ValueError("Overlay monitor dimensions and index must be positive")
    if type(monitor.is_primary) is not bool:
        raise ValueError("Overlay monitor is_primary must be a boolean")
