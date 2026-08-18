from __future__ import annotations

import json
import logging
import os
import re
import threading
import fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from app.db import Database


_VALID_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
logger = logging.getLogger("teach2learn.transcripts")


class TranscriptStore:
    """Database-backed transcripts with private JSONL mirrors for portability."""

    def __init__(self, directory: str | Path, database: Database | None = None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self.database = database

    def _path(self, session_id: str) -> Path:
        if not _VALID_ID.fullmatch(session_id):
            raise ValueError("invalid session id")
        return self.directory / f"{session_id}.jsonl"

    def _lock(self, session_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(session_id, threading.Lock())

    def append(self, session_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        record = dict(message)
        record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        if self.database is not None:
            record = self.database.append_message(session_id, record)
            self.sync_session(session_id)
            return record
        self._append_file(session_id, record)
        return record

    def _append_file(self, session_id: str, record: Mapping[str, Any]) -> None:
        encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        path = self._path(session_id)
        with self._lock(session_id):
            descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                view = memoryview(encoded)
                while view:
                    view = view[os.write(descriptor, view):]
                os.fsync(descriptor)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def read(self, session_id: str) -> list[dict[str, Any]]:
        if self.database is not None:
            return self.database.list_messages(session_id)
        return self._read_file(session_id)

    def _read_file(self, session_id: str) -> list[dict[str, Any]]:
        path = self._path(session_id)
        with self._lock(session_id):
            if not path.exists():
                return []
            with path.open(encoding="utf-8") as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
                try:
                    return [json.loads(line) for line in stream if line.strip()]
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def exists(self, session_id: str) -> bool:
        if self.database is not None and self.database.list_messages(session_id):
            return True
        return self._path(session_id).exists()

    def record_turn(
        self,
        session_id: str,
        user_message: Mapping[str, Any],
        assistant_message: Mapping[str, Any],
        metadata_updates: Mapping[str, Any],
        *,
        complete: bool = False,
    ) -> None:
        if self.database is None:
            self.append(session_id, user_message)
            self.append(session_id, assistant_message)
            return
        self.database.record_turn(
            session_id,
            user_message,
            assistant_message,
            metadata_updates,
            complete=complete,
        )
        self.sync_session(session_id)

    def synchronize(self) -> dict[str, int]:
        """Import legacy JSONL once, then make every mirror match SQLite."""
        if self.database is None:
            return {"sessions": 0, "imported_messages": 0, "mirrors_rebuilt": 0}
        imported = 0
        rebuilt = 0
        session_ids = self.database.session_ids()
        for session_id in session_ids:
            path = self._path(session_id)
            if not self.database.list_messages(session_id) and path.exists():
                imported += self.database.import_messages(session_id, self._read_file(session_id))
            self._sync_session(session_id)
            rebuilt += 1
        return {
            "sessions": len(session_ids),
            "imported_messages": imported,
            "mirrors_rebuilt": rebuilt,
        }

    def mirror_report(self) -> dict[str, int | str]:
        if self.database is None:
            return {"status": "ok", "missing": 0, "mismatched": 0, "unreadable": 0}
        missing = 0
        mismatched = 0
        unreadable = 0
        for session_id in self.database.session_ids():
            path = self._path(session_id)
            if not path.exists():
                missing += 1
                continue
            try:
                if self._read_file(session_id) != self.database.list_messages(session_id):
                    mismatched += 1
            except (OSError, json.JSONDecodeError):
                unreadable += 1
        return {
            "status": "ok" if missing == mismatched == unreadable == 0 else "error",
            "missing": missing,
            "mismatched": mismatched,
            "unreadable": unreadable,
        }

    def _sync_session(self, session_id: str) -> None:
        if self.database is None:
            return
        path = self._path(session_id)
        temporary = path.with_suffix(".jsonl.part")
        records = self.database.list_messages(session_id)
        with self._lock(session_id):
            descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            try:
                for record in records:
                    encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                    view = memoryview(encoded)
                    while view:
                        view = view[os.write(descriptor, view):]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, path)
            path.chmod(0o600)

    def sync_session(self, session_id: str) -> None:
        try:
            self._sync_session(session_id)
        except OSError:
            logger.exception("transcript_mirror_sync_failed session_id=%s", session_id)
