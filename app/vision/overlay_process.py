"""Run the macOS intervention window outside the screen-monitoring process."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import Future
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Thread
from typing import TextIO

from app.intervention.intervene import LOCAL_FALLBACK_MESSAGE
from app.platforms.capture import MonitorInfo
from app.ui.overlay.monitor_payload import encode_monitor

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 0.05
HEARTBEAT_TIMEOUT_SECONDS = 5.0
STARTUP_TIMEOUT_SECONDS = 30.0
HEARTBEAT_TOKEN = "LAVOCADO_OVERLAY_HEARTBEAT"


def overlay_process_command(monitor: MonitorInfo) -> list[str]:
    """Build a source or PyInstaller command for the short-lived overlay app."""

    if getattr(sys, "frozen", False):
        command = [sys.executable]
    else:
        project_root = Path(__file__).resolve().parents[2]
        command = [sys.executable, str(project_root / "main.py")]

    command.append("--overlay-process")
    command.extend(("--overlay-monitor", encode_monitor(monitor)))
    return command


def show_overlay_process(
    monitor: MonitorInfo,
    support_message: Future[str] | None,
    *,
    process_factory=subprocess.Popen,
    sleeper=time.sleep,
    clock=time.monotonic,
    heartbeat_timeout: float = HEARTBEAT_TIMEOUT_SECONDS,
    startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    stop_event: Event | None = None,
) -> None:
    """Wait for the isolated overlay and forward its message when available."""

    process = process_factory(
        overlay_process_command(monitor),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    message_sent = False
    output_stream = getattr(process, "stdout", None)
    heartbeat_events: SimpleQueue[bool] = SimpleQueue()
    heartbeat_reader: Thread | None = None
    started_at = clock()
    last_heartbeat = started_at
    received_heartbeat = False

    try:
        if output_stream is not None:
            heartbeat_reader = Thread(
                target=_read_heartbeat_stream,
                args=(output_stream, heartbeat_events),
                daemon=True,
                name="lavocado-overlay-heartbeat-reader",
            )
            heartbeat_reader.start()

        while process.poll() is None:
            if stop_event is not None and stop_event.is_set():
                break
            if _consume_heartbeat(heartbeat_events):
                last_heartbeat = clock()
                received_heartbeat = True
            now = clock()
            if received_heartbeat and now - last_heartbeat > heartbeat_timeout:
                LOGGER.error("macOS overlay stopped responding; closing its window")
                break
            if not received_heartbeat and now - started_at > startup_timeout:
                LOGGER.error("macOS overlay did not start responding; closing it")
                break
            if not message_sent:
                message = _ready_message(support_message)
                if message is not None:
                    _send_message(process.stdin, message)
                    message_sent = True
            sleeper(POLL_INTERVAL_SECONDS)
    finally:
        _close_stdin(process.stdin)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        _close_output(output_stream)
        if heartbeat_reader is not None:
            heartbeat_reader.join(timeout=1.0)

    if process.returncode:
        LOGGER.warning("macOS overlay process exited with status %s", process.returncode)


def run_overlay_process_child(
    monitor: MonitorInfo,
    input_stream: TextIO,
) -> None:
    """Show the overlay and close it if the monitoring process disappears."""

    from app.ui.overlay.tk_backend import TkOverlayBackend

    support_message: Future[str] = Future()
    parent_closed = Event()
    Thread(
        target=_read_parent_messages,
        args=(input_stream, support_message, parent_closed),
        daemon=True,
        name="lavocado-overlay-parent-watch",
    ).start()
    overlay = TkOverlayBackend("Darwin")
    overlay.show(
        monitor,
        support_message=support_message,
        parent_closed_event=parent_closed,
        heartbeat_callback=_write_heartbeat,
    )


def _read_parent_messages(
    input_stream: TextIO,
    support_message: Future[str],
    parent_closed: Event,
) -> None:
    """Receive one message, then watch the pipe for parent-process shutdown."""

    try:
        line = input_stream.readline()
        message = LOCAL_FALLBACK_MESSAGE
        if line:
            try:
                payload = json.loads(line)
                received = payload.get("message") if isinstance(payload, dict) else None
                if isinstance(received, str) and received.strip():
                    message = received
            except (json.JSONDecodeError, TypeError):
                LOGGER.warning("Ignoring an invalid overlay message")
        if not support_message.done():
            support_message.set_result(message)

        while input_stream.readline():
            pass
    except (OSError, ValueError):
        if not support_message.done():
            support_message.set_result(LOCAL_FALLBACK_MESSAGE)
    finally:
        parent_closed.set()


def _ready_message(support_message: Future[str] | None) -> str | None:
    if support_message is None:
        return LOCAL_FALLBACK_MESSAGE
    if not support_message.done():
        return None
    try:
        return support_message.result() or LOCAL_FALLBACK_MESSAGE
    except Exception:
        LOGGER.exception("Could not prepare the overlay support message")
        return LOCAL_FALLBACK_MESSAGE


def _read_heartbeat_stream(
    output_stream: TextIO,
    heartbeat_events: SimpleQueue[bool],
) -> None:
    """Read child output without blocking the overlay process monitor."""

    try:
        for line in output_stream:
            if line.strip() == HEARTBEAT_TOKEN:
                heartbeat_events.put(True)
    except (OSError, ValueError):
        return


def _consume_heartbeat(heartbeat_events: SimpleQueue[bool]) -> bool:
    received = False
    while True:
        try:
            heartbeat_events.get_nowait()
        except Empty:
            return received
        received = True


def _write_heartbeat() -> None:
    try:
        os.write(1, f"{HEARTBEAT_TOKEN}\n".encode("ascii"))
    except OSError:
        return


def _send_message(input_stream: TextIO | None, message: str) -> None:
    if input_stream is None:
        return
    try:
        input_stream.write(json.dumps({"message": message}, ensure_ascii=True) + "\n")
        input_stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        return


def _close_stdin(input_stream: TextIO | None) -> None:
    if input_stream is None:
        return
    try:
        input_stream.close()
    except OSError:
        return


def _close_output(output_stream: TextIO | None) -> None:
    if output_stream is None:
        return
    try:
        output_stream.close()
    except OSError:
        return
