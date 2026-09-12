"""Developer-only capture backend selection."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from enum import Enum

DEVELOPER_BUILD_ENV = "LAVOCADO_DEVELOPER_BUILD"
CAPTURE_BACKEND_ENV = "LAVOCADO_CAPTURE_BACKEND"
_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})


class CaptureBackendMode(str, Enum):
    """Capture routing modes available to developer runs."""

    AUTO = "auto"
    NATIVE = "native"
    MSS = "mss"


def developer_capture_override_enabled(
    environ: Mapping[str, str],
    *,
    frozen: bool | None = None,
) -> bool:
    """Return whether this process explicitly identifies as a developer run."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        return False
    value = environ.get(DEVELOPER_BUILD_ENV, "")
    return value.strip().casefold() in _ENABLED_VALUES


def resolve_capture_backend_mode(
    environ: Mapping[str, str],
) -> CaptureBackendMode:
    """Resolve the override, ignoring it outside an explicit developer run."""

    if not developer_capture_override_enabled(environ):
        return CaptureBackendMode.AUTO

    value = environ.get(CAPTURE_BACKEND_ENV, CaptureBackendMode.AUTO.value)
    try:
        return CaptureBackendMode(value.strip().casefold())
    except ValueError as error:
        choices = ", ".join(mode.value for mode in CaptureBackendMode)
        raise ValueError(
            f"{CAPTURE_BACKEND_ENV} must be one of: {choices}"
        ) from error
