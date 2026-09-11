"""Manage the protection service as a child process for the dashboard."""

from __future__ import annotations

import subprocess
import sys
from enum import Enum
from pathlib import Path


class ProtectionStatus(str, Enum):
    """States displayed by the local dashboard."""

    STOPPED = "Stopped"
    RUNNING = "Running"
    STOPPING = "Stopping"
    FAILED = "Failed"


def default_protection_command() -> tuple[str, ...]:
    """Return a command that works from any current working directory."""

    if getattr(sys, "frozen", False):
        return (sys.executable, "protect", "--control-stdin")

    project_root = Path(__file__).resolve().parents[2]
    return (
        sys.executable,
        str(project_root / "main.py"),
        "protect",
        "--control-stdin",
    )


class ProtectionController:
    """Start and gracefully stop one dashboard-owned protection process."""

    def __init__(self, command=None, process_factory=subprocess.Popen) -> None:
        self.command = tuple(command or default_protection_command())
        self._process_factory = process_factory
        self._process = None
        self._stop_requested = False
        self._last_exit_code = None

    @property
    def status(self) -> ProtectionStatus:
        self.refresh()
        if self._process is not None:
            if self._stop_requested:
                return ProtectionStatus.STOPPING
            return ProtectionStatus.RUNNING
        if self._last_exit_code not in (None, 0):
            return ProtectionStatus.FAILED
        return ProtectionStatus.STOPPED

    @property
    def last_exit_code(self):
        self.refresh()
        return self._last_exit_code

    def start(self) -> bool:
        """Start protection, returning False if it is already running."""

        self.refresh()
        if self._process is not None:
            return False

        self._process = self._process_factory(
            self.command,
            stdin=subprocess.PIPE,
            text=True,
        )
        self._stop_requested = False
        self._last_exit_code = None
        return True

    def stop(self) -> bool:
        """Ask the child service to stop without platform-specific signals."""

        self.refresh()
        if self._process is None or self._stop_requested:
            return False

        stream = self._process.stdin
        if stream is None:
            return False

        try:
            stream.write("stop\n")
            stream.flush()
        except (BrokenPipeError, OSError, ValueError):
            self.refresh()
            return False

        self._stop_requested = True
        return True

    def refresh(self):
        """Collect an exited child process without blocking the dashboard."""

        if self._process is None:
            return self._last_exit_code

        exit_code = self._process.poll()
        if exit_code is None:
            return None

        stream = self._process.stdin
        if stream is not None and not stream.closed:
            stream.close()
        self._last_exit_code = exit_code
        self._process = None
        self._stop_requested = False
        return exit_code

    def close(self) -> None:
        """Request shutdown when the dashboard itself closes."""

        self.stop()
