"""Build edition flag. User bundles stay on user; Developer entry sets developer.

This module is not Benchmark Lab. User code may read the flag for window titles
and routing. It must never import developer.*.
"""

from __future__ import annotations

USER_EDITION = "user"
DEVELOPER_EDITION = "developer"
USER_APP_NAME = "LAVOCADO"
DEVELOPER_APP_NAME = "LAVOCADO Developer"

BUILD_EDITION = USER_EDITION


def set_build_edition(edition: str) -> None:
    """Set the process edition. Called only from developer_main."""

    global BUILD_EDITION
    normalized = str(edition or USER_EDITION).strip().lower()
    if normalized not in {USER_EDITION, DEVELOPER_EDITION}:
        raise ValueError(f"Unknown build edition: {edition}")
    BUILD_EDITION = normalized


def is_developer_edition() -> bool:
    return BUILD_EDITION == DEVELOPER_EDITION


def app_display_name() -> str:
    return DEVELOPER_APP_NAME if is_developer_edition() else USER_APP_NAME
