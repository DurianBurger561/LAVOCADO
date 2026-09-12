"""Runtime Linux display-session detection for native capture routing."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class LinuxSessionKind(str, Enum):
    """User-visible Linux environment category."""

    WAYLAND = "wayland"
    X11 = "x11"
    WSL = "wsl"
    UNKNOWN = "unknown"


class LinuxDisplayProtocol(str, Enum):
    """Display protocol that determines the compatible native backend."""

    WAYLAND = "wayland"
    X11 = "x11"
    NONE = "none"


class LinuxCaptureRoute(str, Enum):
    """Primary capture implementation selected for one Linux session."""

    PIPEWIRE_PORTAL = "pipewire_portal"
    XSHM = "xshm"
    MSS = "mss"


@dataclass(frozen=True, slots=True)
class LinuxSessionInfo:
    """Normalized, privacy-safe inputs for the Linux capture factory."""

    kind: LinuxSessionKind
    protocol: LinuxDisplayProtocol
    is_wsl: bool

    @property
    def capture_route(self) -> LinuxCaptureRoute:
        if self.protocol is LinuxDisplayProtocol.WAYLAND:
            return LinuxCaptureRoute.PIPEWIRE_PORTAL
        if self.protocol is LinuxDisplayProtocol.X11:
            return LinuxCaptureRoute.XSHM
        return LinuxCaptureRoute.MSS


def detect_linux_session(
    environ: Mapping[str, str] | None = None,
    release: str | None = None,
) -> LinuxSessionInfo:
    """Detect Wayland/X11 while retaining WSL as a distinct environment."""

    values = os.environ if environ is None else environ
    kernel_release = platform.release() if release is None else release
    wsl = _is_wsl(values, kernel_release)
    protocol = _display_protocol(values)

    if wsl:
        kind = LinuxSessionKind.WSL
    elif protocol is LinuxDisplayProtocol.WAYLAND:
        kind = LinuxSessionKind.WAYLAND
    elif protocol is LinuxDisplayProtocol.X11:
        kind = LinuxSessionKind.X11
    else:
        kind = LinuxSessionKind.UNKNOWN
    return LinuxSessionInfo(kind=kind, protocol=protocol, is_wsl=wsl)


def _display_protocol(environ: Mapping[str, str]) -> LinuxDisplayProtocol:
    declared = environ.get("XDG_SESSION_TYPE", "").strip().casefold()
    if declared == "wayland":
        return LinuxDisplayProtocol.WAYLAND
    if declared == "x11":
        return LinuxDisplayProtocol.X11

    if environ.get("WAYLAND_DISPLAY", "").strip():
        return LinuxDisplayProtocol.WAYLAND
    if environ.get("DISPLAY", "").strip():
        return LinuxDisplayProtocol.X11
    return LinuxDisplayProtocol.NONE


def _is_wsl(environ: Mapping[str, str], release: str) -> bool:
    return bool(environ.get("WSL_DISTRO_NAME") or environ.get("WSL_INTEROP")) or (
        "microsoft" in release.casefold()
    )
