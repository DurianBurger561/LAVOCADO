"""Validate Linux capture routing or live frames without retaining pixels."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.platforms import create_platform_adapter
from app.platforms.capture import (
    CaptureError,
    CapturePermissionDeniedError,
    LinuxSessionInfo,
    ScreenCaptureBackend,
    create_linux_capture,
    detect_linux_session,
)

EXIT_CAPTURE_FAILED = 1
EXIT_PERMISSION_DENIED = 2


def route_self_check() -> dict[str, Any]:
    """Validate all Linux routing branches without accessing a display."""

    cases = (
        (
            "wayland",
            {
                "XDG_SESSION_TYPE": "wayland",
                "WAYLAND_DISPLAY": "wayland-0",
                "DISPLAY": ":0",
            },
            "generic-linux",
            "linux_pipewire_portal",
        ),
        (
            "x11",
            {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
            "generic-linux",
            "linux_xshm",
        ),
        (
            "wslg",
            {
                "WSL_DISTRO_NAME": "Ubuntu",
                "WAYLAND_DISPLAY": "wayland-0",
                "DISPLAY": ":0",
            },
            "microsoft-standard-WSL2",
            "linux_pipewire_portal",
        ),
        ("headless", {}, "generic-linux", "mss"),
    )
    results: list[dict[str, Any]] = []
    for name, environment, release, expected in cases:
        session = detect_linux_session(environment, release)
        backend = create_linux_capture(
            session,
            display=environment.get("DISPLAY"),
        )
        actual = backend.status().preferred_backend
        results.append(
            {
                "case": name,
                "session": session.kind.value,
                "route": session.capture_route.value,
                "preferred_backend": actual,
                "ok": actual == expected,
            }
        )
    return {
        "ok": all(result["ok"] for result in results),
        "mode": "route_self_check",
        "cases": results,
    }


def validate_live_capture(
    backend: ScreenCaptureBackend,
    session: LinuxSessionInfo,
    *,
    frames: int = 2,
    fresh_frame_timeout: float = 5.0,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Validate live frames and return only privacy-safe scalar metadata."""

    if frames < 1:
        raise ValueError("frames must be at least 1")
    try:
        backend.start()
        monitors = backend.monitors()
        if not monitors:
            raise RuntimeError("Capture backend returned no physical displays")
        last_sequences = {monitor.id: 0 for monitor in monitors}
        samples: list[dict[str, Any]] = []
        for sample_number in range(1, frames + 1):
            for monitor in monitors:
                frame = _next_fresh_frame(
                    backend,
                    monitor.id,
                    last_sequences[monitor.id],
                    timeout=fresh_frame_timeout,
                    clock=clock,
                    sleeper=sleeper,
                )
                _validate_frame(frame.image, monitor.width, monitor.height)
                last_sequences[monitor.id] = frame.sequence
                samples.append(
                    {
                        "sample": sample_number,
                        "monitor_index": monitor.index,
                        "width": int(frame.image.shape[1]),
                        "height": int(frame.image.shape[0]),
                        "sequence": frame.sequence,
                        "backend": frame.backend,
                    }
                )
        return {
            "ok": True,
            "mode": "live_capture",
            "session": {
                "kind": session.kind.value,
                "protocol": session.protocol.value,
                "is_wsl": session.is_wsl,
                "route": session.capture_route.value,
            },
            "capture": _status_payload(backend),
            "samples": samples,
            "privacy": {
                "frames_saved": False,
                "frames_uploaded": False,
            },
        }
    finally:
        backend.stop()


def _next_fresh_frame(
    backend: ScreenCaptureBackend,
    monitor_id: str,
    previous_sequence: int,
    *,
    timeout: float,
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
):
    deadline = clock() + timeout
    while True:
        frame = backend.get_latest_frame(monitor_id)
        if frame is None:
            raise RuntimeError("Capture backend returned no frame")
        if frame.sequence > previous_sequence:
            return frame
        if clock() >= deadline:
            raise RuntimeError(
                f"Capture sequence stopped advancing for monitor {monitor_id}"
            )
        sleeper(0.05)


def _validate_frame(image: np.ndarray, width: int, height: int) -> None:
    if image.dtype != np.uint8:
        raise RuntimeError(f"Capture dtype must be uint8, got {image.dtype}")
    if image.ndim != 3 or image.shape[2] != 3:
        raise RuntimeError(f"Capture shape must be H x W x 3, got {image.shape}")
    if image.shape[:2] != (height, width):
        raise RuntimeError(
            "Capture dimensions do not match monitor metadata: "
            f"frame={image.shape[1]}x{image.shape[0]}, monitor={width}x{height}"
        )
    if not image.flags.c_contiguous:
        raise RuntimeError("Capture frame must be C-contiguous")


def _status_payload(backend: ScreenCaptureBackend) -> dict[str, Any]:
    status = backend.status()
    return {
        "preferred_backend": status.preferred_backend,
        "active_backend": status.active_backend,
        "fallback": status.fallback,
        "fallback_reason": status.fallback_reason,
        "healthy": status.healthy,
        "error": status.error,
        "session": status.session,
        "monitor_count": status.monitor_count,
        "frame_age_ms": status.frame_age_ms,
    }


def _error_payload(category: str, error: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "mode": "live_capture",
        "error": category,
        "error_type": type(error).__name__,
        "privacy": {
            "frames_saved": False,
            "frames_uploaded": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="validate Wayland, X11, WSLg, and MSS routing without capture",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=2,
        help="fresh frames required from each selected display (default: 2)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_check:
        result = route_self_check()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else EXIT_CAPTURE_FAILED
    if platform.system() != "Linux":
        result = _error_payload(
            "unsupported_platform",
            RuntimeError("Live validation is Linux-only"),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return EXIT_CAPTURE_FAILED

    adapter = create_platform_adapter("Linux")
    session = adapter.desktop_session()
    backend = adapter.create_screen_capture()
    try:
        result = validate_live_capture(backend, session, frames=args.frames)
    except CapturePermissionDeniedError as error:
        result = _error_payload("permission_denied", error)
        print(json.dumps(result, indent=2, sort_keys=True))
        return EXIT_PERMISSION_DENIED
    except (CaptureError, RuntimeError, ValueError) as error:
        result = _error_payload("capture_failed", error)
        print(json.dumps(result, indent=2, sort_keys=True))
        return EXIT_CAPTURE_FAILED
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
