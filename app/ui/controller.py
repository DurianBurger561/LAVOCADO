"""Manage the protection service as a child process for the dashboard."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from enum import Enum
from pathlib import Path
from threading import Condition, Lock, Thread

from app.diagnostics import DiagnosticsStore
from app.settings.storage import load_vision_settings

DIAGNOSTICS_PREFIX = "LAVOCADO_DIAGNOSTICS "


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

    def __init__(
        self, command=None, process_factory=subprocess.Popen, *, data_dir: Path | None = None
    ) -> None:
        self.command = tuple(command or default_protection_command())
        self._data_dir = data_dir
        self._process_factory = process_factory
        self._process = None
        self._stop_requested = False
        self._last_exit_code = None
        self._diagnostics = self._new_diagnostics()
        self._diagnostics_version = 0
        self._diagnostics_condition = Condition()
        self._command_lock = Lock()
        self._reader_thread = None

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
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._stop_requested = False
        self._last_exit_code = None
        with self._diagnostics_condition:
            self._diagnostics = self._new_diagnostics()
            self._diagnostics["protection_state"] = "RUNNING"
        output = self._process.stdout
        if output is not None:
            self._reader_thread = Thread(
                target=self._read_output,
                args=(output,),
                daemon=True,
                name="lavocado-diagnostics-reader",
            )
            self._reader_thread.start()
        return True

    def stop(self) -> bool:
        """Ask the child service to stop without platform-specific signals."""

        self.refresh()
        if self._process is None or self._stop_requested:
            return False

        if not self._send_command("stop"):
            return False

        self._stop_requested = True
        return True

    def restart(self, timeout: float = 2.0) -> bool:
        """Restart only after the old child has exited; never overlap protection."""

        if not self.stop():
            return False
        process = self._process
        if process is None:
            return False
        try:
            process.wait(timeout=max(0.0, timeout))
        except subprocess.TimeoutExpired:
            return False
        self.refresh()
        return self.start()

    def test_intervention(self) -> bool:
        """Ask the child to show a test overlay on its main thread."""

        self.refresh()
        if self._process is None or self._stop_requested:
            return False
        return self._send_command("test-intervention")

    def snapshot(self, timeout: float = 0.25) -> dict[str, object]:
        """Return the latest child diagnostics using a bounded IPC wait."""

        self.refresh()
        with self._diagnostics_condition:
            version = self._diagnostics_version

        if (
            self._process is not None
            and not self._stop_requested
            and self._send_command("diagnostics")
        ):
            with self._diagnostics_condition:
                self._diagnostics_condition.wait_for(
                    lambda: self._diagnostics_version > version,
                    timeout=max(0.0, timeout),
                )

        with self._diagnostics_condition:
            snapshot = deepcopy(self._diagnostics)
        if self._stop_requested:
            snapshot["protection_state"] = "STOPPING"
        elif self._process is None:
            snapshot["protection_state"] = "STOPPED"
        return snapshot

    def refresh(self):
        """Collect an exited child process without blocking the dashboard."""

        if self._process is None:
            return self._last_exit_code

        exit_code = self._process.poll()
        if exit_code is None:
            return None

        self._close_stream(self._process.stdin)
        self._close_stream(getattr(self._process, "stdout", None))
        self._last_exit_code = exit_code
        self._process = None
        self._reader_thread = None
        self._stop_requested = False
        with self._diagnostics_condition:
            self._diagnostics["protection_state"] = "STOPPED"
            self._diagnostics_condition.notify_all()
        return exit_code

    def close(self, timeout: float = 2.0) -> None:
        """Stop and collect the dashboard-owned child within a short bound."""

        self.refresh()
        if self._process is None:
            return
        self.stop()
        process = self._process
        wait = getattr(process, "wait", None)
        if not callable(wait):
            return
        try:
            wait(timeout=max(0.0, timeout))
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                wait(timeout=1.0)
        finally:
            self.refresh()

    def _send_command(self, command: str) -> bool:
        if self._process is None:
            return False
        stream = self._process.stdin
        if stream is None:
            return False
        try:
            with self._command_lock:
                stream.write(f"{command}\n")
                stream.flush()
        except (BrokenPipeError, OSError, ValueError):
            self.refresh()
            return False
        return True

    def _read_output(self, output) -> None:
        try:
            for line in output:
                self._handle_output_line(line)
        except (OSError, ValueError):
            pass

    def _handle_output_line(self, line: str) -> bool:
        if not line.startswith(DIAGNOSTICS_PREFIX):
            return False
        try:
            payload = json.loads(line.removeprefix(DIAGNOSTICS_PREFIX))
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(payload, dict):
            return False
        with self._diagnostics_condition:
            self._diagnostics = payload
            self._diagnostics_version += 1
            self._diagnostics_condition.notify_all()
        return True

    @staticmethod
    def _close_stream(stream) -> None:
        if stream is None or not hasattr(stream, "close"):
            return
        if not getattr(stream, "closed", False):
            stream.close()

    def _new_diagnostics(self) -> dict[str, object]:
        settings = load_vision_settings(self._data_dir)
        return DiagnosticsStore(
            model_variant=settings.detector.primary,
            inference_resolution=settings.detector.full_input_size,
            context_model=settings.context.model,
            context_status="not_started",
            yolo_status="not_started",
            primary_detector=settings.detector.primary,
        ).snapshot()
