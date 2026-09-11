"""Tests for dashboard-owned protection process control."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ui.controller import (
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
        self.exit_code = None

    def poll(self):
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


if __name__ == "__main__":
    unittest.main()
