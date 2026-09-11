"""Privacy-preserving local SQLite event recording."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.paths import default_database_path


@dataclass(frozen=True, slots=True)
class ProtectionEvent:
    """Metadata for one confirmed trigger; no captured content is retained."""

    occurred_at: str
    trigger_type: str
    label: str | None
    confidence: float | None
    monitor_index: int
    intervention_shown: bool = False


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """A stored event including its database identifier."""

    id: int
    occurred_at: str
    trigger_type: str
    label: str | None
    confidence: float | None
    monitor_index: int
    intervention_shown: bool


class EventRecorder:
    """Store minimal event metadata on one background worker."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path or default_database_path())
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="lavocado-recorder",
        )
        self._close_lock = Lock()
        self._closed = False
        self._initialize_database()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS protection_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    label TEXT,
                    confidence REAL,
                    monitor_index INTEGER NOT NULL,
                    intervention_shown INTEGER NOT NULL DEFAULT 0
                        CHECK (intervention_shown IN (0, 1))
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    protection_events_occurred_at_index
                ON protection_events (occurred_at DESC)
                """
            )

    def record(self, event: ProtectionEvent) -> int:
        """Synchronously store an event and return its database id."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO protection_events (
                    occurred_at,
                    trigger_type,
                    label,
                    confidence,
                    monitor_index,
                    intervention_shown
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.occurred_at,
                    event.trigger_type,
                    event.label,
                    event.confidence,
                    event.monitor_index,
                    int(event.intervention_shown),
                ),
            )
            event_id = cursor.lastrowid

        if event_id is None:
            raise RuntimeError("SQLite did not return an event id")
        return event_id

    def record_async(self, event: ProtectionEvent) -> Future[int]:
        """Queue an event write so the protection overlay is not delayed."""

        return self._submit(self.record, event)

    def mark_intervention_shown(self, event_id: int) -> None:
        """Mark that the blocking interface was successfully displayed."""

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE protection_events
                SET intervention_shown = 1
                WHERE id = ?
                """,
                (event_id,),
            )

    def recent(self, limit: int = 100) -> list[RecordedEvent]:
        """Return newest events first."""

        if limit < 1:
            raise ValueError("limit must be at least 1")

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    occurred_at,
                    trigger_type,
                    label,
                    confidence,
                    monitor_index,
                    intervention_shown
                FROM protection_events
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            RecordedEvent(
                id=int(row["id"]),
                occurred_at=str(row["occurred_at"]),
                trigger_type=str(row["trigger_type"]),
                label=row["label"],
                confidence=row["confidence"],
                monitor_index=int(row["monitor_index"]),
                intervention_shown=bool(row["intervention_shown"]),
            )
            for row in rows
        ]

    def close(self) -> None:
        """Flush queued writes and release the background worker."""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True)

    def _submit(
        self,
        function: Callable[..., int],
        *args: object,
    ) -> Future[int]:
        with self._close_lock:
            if self._closed:
                raise RuntimeError("EventRecorder is closed")
            return self._executor.submit(function, *args)
