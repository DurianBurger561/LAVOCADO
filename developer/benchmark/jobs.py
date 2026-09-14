"""Run one Developer Lab tool in a disposable, isolated worker process."""

from __future__ import annotations

import csv
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Any
from uuid import uuid4

from developer.benchmark.hardware_ipc import read_json, worker_command, write_json


def _history_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "benchmark_data" / "lab_runs"


class LabProcessJob:
    """Keep pixels in the worker; persist only its scalar JSON result."""

    def __init__(
        self,
        kind: str,
        arguments: list[str],
        data_dir: Path,
        *,
        process_factory=subprocess.Popen,
    ) -> None:
        if kind not in {"capture", "stability", "diagnostic"}:
            raise ValueError(f"Unknown Lab tool: {kind}")
        self.id = uuid4().hex[:16]
        self.kind = kind
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.data_dir = Path(data_dir)
        self._temporary = TemporaryDirectory(prefix="lavocado-lab-")
        work_dir = Path(self._temporary.name)
        self._result_file = work_dir / "result.json"
        self._progress_file = work_dir / "progress.json"
        command = worker_command(
            kind,
            *arguments,
            "--result-file",
            str(self._result_file),
            "--progress-file",
            str(self._progress_file),
        )
        try:
            self._process = process_factory(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=os.name != "nt",
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
            )
        except Exception:
            self._temporary.cleanup()
            raise
        self._record: dict[str, Any] | None = None
        self._cancelled = False
        self._lock = RLock()

    @property
    def running(self) -> bool:
        return self._record is None and self._process.poll() is None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._record is None and self._process.poll() is not None:
                result = read_json(self._result_file)
                status = (
                    "cancelled"
                    if self._cancelled
                    else "completed"
                    if self._process.returncode == 0 and result and result.get("ok") is True
                    else "failed"
                )
                self._record = {
                    "id": self.id,
                    "kind": self.kind,
                    "created_at": self.created_at,
                    "status": status,
                    "result": result or {"ok": False, "error": "worker_failed"},
                }
                try:
                    write_json(_history_dir(self.data_dir) / f"{self.id}.json", self._record)
                finally:
                    self._temporary.cleanup()
            return {
                "status": "running" if self._record is None else self._record["status"],
                "kind": self.kind,
                "progress": read_json(self._progress_file) if self._record is None else None,
                "record": self._record,
            }

    def cancel(self) -> None:
        with self._lock:
            if not self.running:
                return
            self._cancelled = True
            import psutil

            try:
                parent = psutil.Process(self._process.pid)
                descendants = parent.children(recursive=True)
                for child in reversed(descendants):
                    child.terminate()
                parent.terminate()
                _, alive = psutil.wait_procs([*descendants, parent], timeout=3)
                for process in alive:
                    process.kill()
                self._process.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.AccessDenied, subprocess.TimeoutExpired):
                if self._process.poll() is None:
                    self._process.kill()
                    self._process.wait(timeout=5)

    def close(self) -> None:
        self.cancel()
        self.snapshot()


def list_tool_runs(data_dir: Path, limit: int = 25) -> list[dict[str, Any]]:
    root = _history_dir(data_dir)
    if not root.is_dir():
        return []
    records = [read_json(path) for path in root.glob("*.json")]
    valid = [record for record in records if record is not None]
    valid.sort(
        key=lambda record: (str(record.get("created_at") or ""), str(record.get("id") or "")),
        reverse=True,
    )
    return valid[:limit]


def save_scalar_report(data_dir: Path, kind: str, result: dict[str, Any]) -> dict[str, Any]:
    record = {
        "id": uuid4().hex[:16],
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "result": result,
    }
    write_json(_history_dir(data_dir) / f"{record['id']}.json", record)
    return record


def export_tool_run(record: dict[str, Any], destination: Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".json":
        write_json(target, record)
    elif target.suffix.lower() == ".csv":
        rows = _flatten(record)
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("field", "value"))
            writer.writerows(rows)
    else:
        raise ValueError("Export must use .json or .csv")
    return target


def _flatten(payload: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for key, value in payload.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            rows.extend(_flatten(value, name))
        else:
            rows.append((name, json.dumps(value, ensure_ascii=True)))
    return rows
