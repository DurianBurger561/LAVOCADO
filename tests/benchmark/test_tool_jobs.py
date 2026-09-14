"""Packaged worker IPC and scalar result history."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from developer.benchmark.hardware_ipc import read_json, worker_command, write_json
from developer.benchmark.jobs import (
    LabProcessJob,
    export_tool_run,
    list_tool_runs,
    save_scalar_report,
)


class FinishedProcess:
    returncode = 0

    def poll(self):
        return self.returncode


class ToolJobTests(unittest.TestCase):
    def test_source_worker_completes_synthetic_job_through_file_ipc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = LabProcessJob(
                "diagnostic",
                ["--mode", "preprocessor", "--iterations", "2", "--width", "32", "--height", "24", "--size", "16"],
                Path(temporary),
            )
            try:
                deadline = time.monotonic() + 15
                while job.running and time.monotonic() < deadline:
                    time.sleep(0.05)
                snapshot = job.snapshot()
                self.assertEqual(snapshot["status"], "completed")
                self.assertTrue(snapshot["record"]["result"]["synthetic_pixels_only"])
            finally:
                job.close()

    def test_source_and_frozen_worker_commands(self) -> None:
        source = worker_command("capture", "--backend", "native")
        self.assertEqual(Path(source[1]).name, "developer_main.py")
        self.assertEqual(source[2:4], ["--benchmark-worker", "capture"])
        with patch("developer.benchmark.hardware_ipc.sys.frozen", True, create=True):
            frozen = worker_command("stability", "--backend", "auto")
        self.assertEqual(frozen[1:3], ["--benchmark-worker", "stability"])

    def test_job_reads_file_result_and_exports_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def finished_worker(command, **_kwargs):
                result_file = Path(command[command.index("--result-file") + 1])
                write_json(result_file, {"ok": True, "metric_kind": "synthetic", "latency_ms": 2.5})
                return FinishedProcess()

            job = LabProcessJob("diagnostic", ["--mode", "preprocessor"], root, process_factory=finished_worker)
            snapshot = job.snapshot()
            self.assertEqual(snapshot["status"], "completed")
            self.assertEqual(snapshot["record"]["result"]["latency_ms"], 2.5)
            runs = list_tool_runs(root)
            self.assertEqual(len(runs), 1)
            destination = export_tool_run(runs[0], root / "export.csv")
            self.assertIn("latency_ms", destination.read_text(encoding="utf-8"))
            self.assertEqual(read_json(root / "missing.json"), None)

    def test_history_uses_run_time_not_random_file_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            older = save_scalar_report(root, "ranking_fixture", {"quality": 1})
            newer = save_scalar_report(root, "high_recall_cases", {"recall": 0.5})
            for record, timestamp in ((older, "2024-01-01T00:00:00+00:00"), (newer, "2025-01-01T00:00:00+00:00")):
                record["created_at"] = timestamp
                write_json(root / "benchmark_data" / "lab_runs" / f"{record['id']}.json", record)
            self.assertEqual(
                [item["id"] for item in list_tool_runs(root, limit=1)],
                [newer["id"]],
            )
