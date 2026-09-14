"""Tests for dashboard-owned protection process control."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.settings.schema import default_vision_settings, merge_vision_settings
from app.settings.storage import save_vision_settings
from app.ui.controller import (
    DIAGNOSTICS_PREFIX,
    ProtectionController,
    ProtectionStatus,
    default_protection_command,
)


class FakeInput:
    def __init__(self) -> None:
        self.content = ""
        self.flushes = 0
        self.closed = False

    def write(self, value: str) -> None:
        self.content += value

    def flush(self) -> None:
        self.flushes += 1

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = FakeInput()
        self.stdout = []
        self.exit_code = None
        self.wait_timeouts = []

    def poll(self):
        return self.exit_code

    def wait(self, timeout: float):
        self.wait_timeouts.append(timeout)
        self.exit_code = 0
        return self.exit_code


class FakeProcessFactory:
    def __init__(self) -> None:
        self.calls = []
        self.process = FakeProcess()

    def __call__(self, command, **options):
        self.calls.append((command, options))
        return self.process


class ProtectionControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = FakeProcessFactory()
        self.controller = ProtectionController(
            command=("python", "main.py", "protect"),
            process_factory=self.factory,
        )

    def test_starts_only_one_process(self) -> None:
        self.assertTrue(self.controller.start())
        self.assertFalse(self.controller.start())

        self.assertEqual(len(self.factory.calls), 1)
        self.assertEqual(self.controller.status, ProtectionStatus.RUNNING)

    def test_stop_sends_portable_control_message(self) -> None:
        self.controller.start()

        self.assertTrue(self.controller.stop())
        self.assertEqual(self.factory.process.stdin.content, "stop\n")
        self.assertEqual(self.factory.process.stdin.flushes, 1)
        self.assertEqual(self.controller.status, ProtectionStatus.STOPPING)
        self.assertFalse(self.controller.stop())

    def test_test_intervention_sends_fixed_control_message(self) -> None:
        self.controller.start()

        self.assertTrue(self.controller.test_intervention())
        self.assertEqual(
            self.factory.process.stdin.content,
            "test-intervention\n",
        )

    def test_accepts_only_prefixed_json_diagnostics(self) -> None:
        payload = {"protection_state": "MONITORING", "temporal": [1, 0, 1]}
        self.controller.start()

        self.assertFalse(self.controller._handle_output_line("ordinary output\n"))
        self.assertFalse(
            self.controller._handle_output_line(f"{DIAGNOSTICS_PREFIX}not-json\n")
        )
        self.assertTrue(
            self.controller._handle_output_line(
                f"{DIAGNOSTICS_PREFIX}{json.dumps(payload)}\n"
            )
        )
        self.assertEqual(self.controller.snapshot(timeout=0), payload)

    def test_collects_successful_exit(self) -> None:
        self.controller.start()
        self.factory.process.exit_code = 0

        self.assertEqual(self.controller.status, ProtectionStatus.STOPPED)
        self.assertTrue(self.factory.process.stdin.closed)

    def test_reports_failed_exit(self) -> None:
        self.controller.start()
        self.factory.process.exit_code = 7

        self.assertEqual(self.controller.status, ProtectionStatus.FAILED)
        self.assertEqual(self.controller.last_exit_code, 7)

    def test_close_waits_for_the_owned_child(self) -> None:
        self.controller.start()

        self.controller.close(timeout=1.5)

        self.assertEqual(self.factory.process.stdin.content, "stop\n")
        self.assertEqual(self.factory.process.wait_timeouts, [1.5])
        self.assertEqual(self.controller.status, ProtectionStatus.STOPPED)

    def test_restart_waits_for_old_child_before_starting_new_one(self) -> None:
        processes = []

        def factory(_command, **_options):
            process = FakeProcess()
            processes.append(process)
            return process

        controller = ProtectionController(command=("protect",), process_factory=factory)
        self.assertTrue(controller.start())

        self.assertTrue(controller.restart(timeout=1.5))

        self.assertEqual(len(processes), 2)
        self.assertEqual(processes[0].stdin.content, "stop\n")
        self.assertEqual(processes[0].wait_timeouts, [1.5])
        self.assertTrue(processes[0].stdin.closed)
        self.assertIs(controller._process, processes[1])
        self.assertEqual(controller.status, ProtectionStatus.RUNNING)

    def test_restart_timeout_does_not_start_overlapping_child(self) -> None:
        self.controller.start()
        with patch.object(
            self.factory.process,
            "wait",
            side_effect=subprocess.TimeoutExpired("protect", 0.01),
        ):
            self.assertFalse(self.controller.restart(timeout=0.01))

        self.assertEqual(len(self.factory.calls), 1)
        self.assertEqual(self.controller.status, ProtectionStatus.STOPPING)

    def test_initial_diagnostics_use_persisted_detector_selection(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            settings = merge_vision_settings(
                default_vision_settings(),
                {"detector": {"primary": "yolo11_nsfw_small"},
                 "context": {"model": "off"}},
            )
            save_vision_settings(settings, data_dir)
            controller = ProtectionController(
                command=("protect",), data_dir=data_dir,
            )

            snapshot = controller.snapshot(timeout=0)

        self.assertEqual(snapshot["primary_detector"], "yolo11_nsfw_small")
        self.assertEqual(snapshot["context_model"], "off")

    def test_default_command_uses_absolute_main_path(self) -> None:
        command = default_protection_command()

        self.assertTrue(Path(command[1]).is_absolute())
        self.assertEqual(command[-2:], ("protect", "--control-stdin"))

    def test_frozen_command_restarts_the_packaged_executable(self) -> None:
        with patch.object(sys, "frozen", True, create=True):
            command = default_protection_command()

        self.assertEqual(
            command,
            (sys.executable, "protect", "--control-stdin"),
        )

    def test_round_trips_diagnostics_through_a_real_child_process(self) -> None:
        script = (
            "import json, sys\n"
            f"prefix = {DIAGNOSTICS_PREFIX!r}\n"
            "for line in sys.stdin:\n"
            "    command = line.strip()\n"
            "    if command == 'diagnostics':\n"
            "        print(prefix + json.dumps({\n"
            "            'protection_state': 'MONITORING',\n"
            "            'last_scan_ms': 42.5,\n"
            "        }), flush=True)\n"
            "    elif command == 'stop':\n"
            "        break\n"
        )
        controller = ProtectionController(
            command=(sys.executable, "-u", "-c", script),
        )

        try:
            self.assertTrue(controller.start())
            snapshot = controller.snapshot(timeout=2.0)
            self.assertEqual(snapshot["protection_state"], "MONITORING")
            self.assertEqual(snapshot["last_scan_ms"], 42.5)
            self.assertTrue(controller.restart(timeout=2.0))
            self.assertEqual(controller.status, ProtectionStatus.RUNNING)
            self.assertTrue(controller.stop())
            controller._process.wait(timeout=2.0)
            self.assertEqual(controller.status, ProtectionStatus.STOPPED)
        finally:
            controller.close()


if __name__ == "__main__":
    unittest.main()
