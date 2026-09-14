"""Tests for the isolated macOS overlay process protocol."""

import io
import json
import os
import sys
import unittest
from concurrent.futures import Future
from pathlib import Path
from queue import SimpleQueue
from threading import Event
from unittest.mock import patch

from app.intervention.intervene import LOCAL_FALLBACK_MESSAGE
from app.platforms.capture import MonitorInfo
from app.ui.overlay.monitor_payload import encode_monitor
from app.vision.overlay_process import (
    HEARTBEAT_TOKEN,
    _consume_heartbeat,
    _read_heartbeat_stream,
    _read_parent_messages,
    overlay_process_command,
    run_overlay_process_child,
    show_overlay_process,
)


class CapturedInput(io.StringIO):
    def close(self) -> None:
        self.captured = super().getvalue()
        super().close()


class FakeProcess:
    def __init__(self, polls_before_exit: int = 3) -> None:
        self.stdin = CapturedInput()
        self.returncode = None
        self.poll_count = 0
        self.polls_before_exit = polls_before_exit
        self.terminated = False

    def poll(self):
        self.poll_count += 1
        if self.poll_count >= self.polls_before_exit and not self.terminated:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode


class OverlayProcessTests(unittest.TestCase):
    monitor = MonitorInfo("display-b", 2, -1200, 0, 1200, 900)

    def test_source_command_uses_project_entry_point(self) -> None:
        with (
            patch.object(sys, "frozen", False, create=True),
            patch.object(sys, "executable", "/python"),
        ):
            command = overlay_process_command(self.monitor)

        self.assertEqual(command[0], "/python")
        self.assertEqual(Path(command[1]).name, "main.py")
        self.assertEqual(
            command[2:],
            ["--overlay-process", "--overlay-monitor", encode_monitor(self.monitor)],
        )

    def test_packaged_command_relaunches_the_frozen_executable(self) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", "/Applications/LAVOCADO"),
        ):
            command = overlay_process_command(self.monitor)

        self.assertEqual(
            command,
            ["/Applications/LAVOCADO", "--overlay-process",
             "--overlay-monitor", encode_monitor(self.monitor)],
        )

    def test_support_message_is_forwarded_to_child(self) -> None:
        process = FakeProcess()
        message: Future[str] = Future()
        message.set_result("Take one breath, then close that tab.")

        show_overlay_process(
            self.monitor,
            message,
            process_factory=lambda *_args, **_kwargs: process,
            sleeper=lambda _delay: None,
        )

        payload = json.loads(process.stdin.captured)
        self.assertEqual(payload["message"], "Take one breath, then close that tab.")
        self.assertTrue(process.stdin.closed)

    def test_child_shows_passed_monitor_without_rediscovery(self) -> None:
        with (
            patch("app.ui.overlay.tk_backend.TkOverlayBackend") as backend_class,
            patch("app.vision.overlay_process.Thread"),
        ):
            run_overlay_process_child(self.monitor, io.StringIO(""))

        backend_class.assert_called_once_with("Darwin")
        shown = backend_class.return_value.show.call_args
        self.assertEqual(shown.args[0], self.monitor)

    def test_parent_pipe_closure_is_detected_after_message_delivery(self) -> None:
        message: Future[str] = Future()
        parent_closed = Event()

        _read_parent_messages(
            io.StringIO('{"message":"A small next step is enough."}\n'),
            message,
            parent_closed,
        )

        self.assertEqual(message.result(), "A small next step is enough.")
        self.assertTrue(parent_closed.is_set())

    def test_missing_parent_message_uses_local_fallback(self) -> None:
        message: Future[str] = Future()
        parent_closed = Event()

        _read_parent_messages(io.StringIO(""), message, parent_closed)

        self.assertEqual(message.result(), LOCAL_FALLBACK_MESSAGE)
        self.assertTrue(parent_closed.is_set())

    def test_interrupted_wait_terminates_the_overlay_child(self) -> None:
        process = FakeProcess(polls_before_exit=100)

        with self.assertRaises(KeyboardInterrupt):
            show_overlay_process(
                self.monitor,
                None,
                process_factory=lambda *_args, **_kwargs: process,
                sleeper=lambda _delay: (_ for _ in ()).throw(KeyboardInterrupt()),
            )

        self.assertTrue(process.terminated)
        self.assertTrue(process.stdin.closed)

    def test_missing_startup_heartbeat_terminates_unresponsive_child(self) -> None:
        process = FakeProcess(polls_before_exit=100)
        now = [0.0]

        show_overlay_process(
            self.monitor,
            None,
            process_factory=lambda *_args, **_kwargs: process,
            sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
            clock=lambda: now[0],
            startup_timeout=0.075,
        )

        self.assertTrue(process.terminated)

    def test_hide_signal_terminates_the_isolated_child(self) -> None:
        process = FakeProcess(polls_before_exit=100)
        stop_event = Event()
        stop_event.set()

        show_overlay_process(
            self.monitor,
            None,
            process_factory=lambda *_args, **_kwargs: process,
            sleeper=lambda _delay: None,
            stop_event=stop_event,
        )

        self.assertTrue(process.terminated)

    def test_ui_heartbeat_is_detected_through_the_child_pipe(self) -> None:
        read_fd, write_fd = os.pipe()
        heartbeat_events: SimpleQueue[bool] = SimpleQueue()
        with os.fdopen(write_fd, "w", encoding="utf-8") as writer:
            writer.write(f"{HEARTBEAT_TOKEN}\n")
            writer.flush()
        with os.fdopen(read_fd, "r", encoding="utf-8") as reader:
            _read_heartbeat_stream(reader, heartbeat_events)

        self.assertTrue(_consume_heartbeat(heartbeat_events))


if __name__ == "__main__":
    unittest.main()
