from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS participants (
    id TEXT PRIMARY KEY,
    external_id TEXT UNIQUE,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    subtopic TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'abandoned')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sessions_participant ON sessions(participant_id);
CREATE INDEX IF NOT EXISTS idx_sessions_participant_started ON sessions(participant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK(sequence >= 0),
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    turn INTEGER NOT NULL CHECK(turn >= 0),
    content TEXT NOT NULL CHECK(length(content) > 0),
    timestamp TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    UNIQUE(session_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_messages_session_turn ON messages(session_id, turn, sequence);
CREATE TABLE IF NOT EXISTS evaluations (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    result_json TEXT,
    error TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS survey_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
    response_json TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluations_status_updated ON evaluations(status, updated_at);
"""

SCHEMA_VERSION = 3


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_messages_schema(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.execute("PRAGMA optimize=0x10002")
        self.path.chmod(0o600)

    @staticmethod
    def _migrate_messages_schema(connection: sqlite3.Connection) -> None:
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
        ).fetchone()[0]
        if "UNIQUE(session_id, role, turn)" not in table_sql:
            return
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            DROP INDEX IF EXISTS idx_messages_session_turn;
            ALTER TABLE messages RENAME TO messages_v2;
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL CHECK(sequence >= 0),
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                turn INTEGER NOT NULL CHECK(turn >= 0),
                content TEXT NOT NULL CHECK(length(content) > 0),
                timestamp TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
                UNIQUE(session_id, sequence)
            );
            INSERT INTO messages(id, session_id, sequence, role, turn, content, timestamp, metadata_json)
                SELECT id, session_id, sequence, role, turn, content, timestamp, metadata_json FROM messages_v2;
            DROP TABLE messages_v2;
            CREATE INDEX idx_messages_session_turn ON messages(session_id, turn, sequence);
            COMMIT;
            """
        )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA wal_autocheckpoint = 1000")
        connection.execute("PRAGMA journal_size_limit = 67108864")
        connection.execute("PRAGMA secure_delete = FAST")
        connection.execute("PRAGMA cache_size = -32768")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA mmap_size = 134217728")
        try:
            yield connection
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def create_participant(self, external_id: str | None = None, metadata: Mapping[str, Any] | None = None, *, participant_id: str | None = None) -> str:
        participant_id = participant_id or str(uuid.uuid4())
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO participants(id, external_id, created_at, metadata_json) VALUES (?, ?, ?, ?)",
                (participant_id, external_id, utc_now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )
        return participant_id

    def get_participant(self, participant_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM participants WHERE id=?", (participant_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json"))
        return value

    def get_participant_by_external_id(self, external_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM participants WHERE external_id=?", (external_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json"))
        return value

    def get_or_create_participant(
        self,
        external_id: str,
        name: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata_updates = {"name": name, **dict(metadata or {})}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM participants WHERE external_id=?",
                (external_id,),
            ).fetchone()
            if row:
                existing = dict(row)
                merged_metadata = {
                    **json.loads(existing["metadata_json"]),
                    **metadata_updates,
                }
                connection.execute(
                    "UPDATE participants SET metadata_json=? WHERE id=?",
                    (json.dumps(merged_metadata, ensure_ascii=False), existing["id"]),
                )
                connection.commit()
                existing.pop("metadata_json")
                existing["metadata"] = merged_metadata
                return existing
            participant_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO participants(id, external_id, created_at, metadata_json) VALUES (?, ?, ?, ?)",
                (participant_id, external_id, utc_now(), json.dumps(metadata_updates, ensure_ascii=False)),
            )
            connection.commit()
        return self.get_participant(participant_id)  # type: ignore[return-value]

    def create_session(
        self,
        participant_id: str,
        subject: str,
        subtopic: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        *,
        session_id: str | None = None,
        opening_message: Mapping[str, Any] | None = None,
    ) -> str:
        session_id = session_id or str(uuid.uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO sessions(id, participant_id, subject, subtopic, started_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, participant_id, subject, subtopic, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            connection.execute(
                "INSERT INTO evaluations(session_id, status, updated_at) VALUES (?, 'pending', ?)",
                (session_id, now),
            )
            if opening_message is not None:
                self._insert_message(connection, session_id, 0, opening_message)
            connection.commit()
        return session_id

    def complete_session(self, session_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET status='completed', completed_at=COALESCE(completed_at, ?) WHERE id=? AND status='active'",
                (utc_now(), session_id),
            )
        return cursor.rowcount == 1

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json"))
        return value

    def list_sessions(self, participant_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions WHERE participant_id=? ORDER BY started_at DESC",
                (participant_id,),
            ).fetchall()
        sessions: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["metadata"] = json.loads(value.pop("metadata_json"))
            sessions.append(value)
        return sessions

    def list_participants_with_session_counts(self) -> list[dict[str, Any]]:
        """Return participants with aggregate activity for the read-only admin UI."""
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT p.*, COUNT(s.id) AS session_count,
                          SUM(CASE WHEN s.status='completed' THEN 1 ELSE 0 END) AS completed_count,
                          SUM(CASE WHEN s.status='active' THEN 1 ELSE 0 END) AS active_count,
                          (SELECT COUNT(*) FROM messages m
                           JOIN sessions ms ON ms.id=m.session_id
                           WHERE ms.participant_id=p.id AND m.role='user') AS turn_count,
                          MAX(s.started_at) AS last_session_at
                   FROM participants p
                   LEFT JOIN sessions s ON s.participant_id=p.id
                   GROUP BY p.id
                   ORDER BY COALESCE(MAX(s.started_at), p.created_at) DESC"""
            ).fetchall()
        participants: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["metadata"] = json.loads(value.pop("metadata_json"))
            participants.append(value)
        return participants

    def update_session_metadata(self, session_id: str, updates: Mapping[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT metadata_json FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown session: {session_id}")
            metadata = {**json.loads(row[0]), **dict(updates)}
            connection.execute(
                "UPDATE sessions SET metadata_json=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), session_id),
            )
            connection.commit()
        return metadata

    @staticmethod
    def _message_values(message: Mapping[str, Any]) -> tuple[str, int, str, str, str]:
        record = dict(message)
        role = str(record.pop("role", "")).strip()
        content = str(record.pop("content", "")).strip()
        turn = int(record.pop("turn", 0))
        timestamp = str(record.pop("timestamp", utc_now()))
        if role not in {"user", "assistant"}:
            raise ValueError(f"invalid message role: {role}")
        if not content:
            raise ValueError("message content cannot be empty")
        if turn < 0:
            raise ValueError("message turn cannot be negative")
        return role, turn, content, timestamp, json.dumps(record, ensure_ascii=False)

    @classmethod
    def _insert_message(
        cls,
        connection: sqlite3.Connection,
        session_id: str,
        sequence: int,
        message: Mapping[str, Any],
    ) -> None:
        role, turn, content, timestamp, metadata_json = cls._message_values(message)
        connection.execute(
            """INSERT INTO messages(session_id, sequence, role, turn, content, timestamp, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, sequence, role, turn, content, timestamp, metadata_json),
        )

    def append_message(self, session_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        record = dict(message)
        record.setdefault("timestamp", utc_now())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), -1) + 1 FROM messages WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            self._insert_message(connection, session_id, sequence, record)
            connection.commit()
        return {"sequence": sequence, **record}

    def import_messages(self, session_id: str, messages: Sequence[Mapping[str, Any]]) -> int:
        """Import a legacy JSONL transcript only when the database has no messages."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session_exists = connection.execute(
                "SELECT 1 FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if not session_exists:
                raise KeyError(f"unknown session: {session_id}")
            existing = connection.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            if existing:
                connection.rollback()
                return 0
            for sequence, message in enumerate(messages):
                self._insert_message(connection, session_id, sequence, message)
            connection.commit()
        return len(messages)

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT sequence, role, turn, content, timestamp, metadata_json
                   FROM messages WHERE session_id=? ORDER BY sequence""",
                (session_id,),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            records.append(
                {
                    "sequence": row["sequence"],
                    "role": row["role"],
                    "content": row["content"],
                    "turn": row["turn"],
                    "timestamp": row["timestamp"],
                    **metadata,
                }
            )
        return records

    def record_turn(
        self,
        session_id: str,
        user_message: Mapping[str, Any],
        assistant_message: Mapping[str, Any],
        metadata_updates: Mapping[str, Any],
        *,
        complete: bool = False,
    ) -> None:
        """Atomically persist a complete user/assistant turn and session state."""
        user_record = dict(user_message)
        assistant_record = dict(assistant_message)
        timestamp = utc_now()
        user_record.setdefault("timestamp", timestamp)
        assistant_record.setdefault("timestamp", timestamp)
        turn = int(user_record.get("turn", -1))
        if int(assistant_record.get("turn", -2)) != turn:
            raise ValueError("user and assistant messages must have the same turn")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, metadata_json FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown session: {session_id}")
            if row["status"] != "active":
                raise ValueError("only active sessions can accept a turn")
            metadata = json.loads(row["metadata_json"])
            expected_turn = int(metadata.get("turn", 0)) + 1
            if turn != expected_turn:
                raise ValueError(f"expected turn {expected_turn}, received {turn}")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), -1) + 1 FROM messages WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            self._insert_message(connection, session_id, sequence, user_record)
            self._insert_message(connection, session_id, sequence + 1, assistant_record)
            metadata.update(dict(metadata_updates))
            connection.execute(
                """UPDATE sessions
                   SET metadata_json=?, status=?, completed_at=CASE WHEN ? THEN COALESCE(completed_at, ?) ELSE completed_at END
                   WHERE id=?""",
                (
                    json.dumps(metadata, ensure_ascii=False),
                    "completed" if complete else "active",
                    complete,
                    timestamp,
                    session_id,
                ),
            )
            connection.commit()

    def session_ids(self) -> list[str]:
        with self.connect() as connection:
            return [row[0] for row in connection.execute("SELECT id FROM sessions ORDER BY started_at")]

    def storage_report(self) -> dict[str, Any]:
        with self.connect() as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("participants", "sessions", "messages", "evaluations", "survey_responses")
            }
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
            turn_mismatches = connection.execute(
                """SELECT COUNT(*) FROM sessions s
                   WHERE CAST(COALESCE(json_extract(s.metadata_json, '$.turn'), 0) AS INTEGER)
                         != COALESCE((SELECT MAX(m.turn) FROM messages m WHERE m.session_id=s.id), 0)"""
            ).fetchone()[0]
            incomplete_turns = connection.execute(
                """SELECT COUNT(*) FROM (
                       SELECT session_id, turn FROM messages WHERE turn > 0 GROUP BY session_id, turn
                       HAVING SUM(role='user') = 0 OR SUM(role='assistant') = 0
                           OR SUM(role='user') != SUM(role='assistant')
                   )"""
            ).fetchone()[0]
            sessions_without_messages = connection.execute(
                """SELECT COUNT(*) FROM sessions s
                   WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.session_id=s.id)"""
            ).fetchone()[0]
            pragmas = {
                "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
                "synchronous": connection.execute("PRAGMA synchronous").fetchone()[0],
                "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
                "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            }
        return {
            "status": "ok" if integrity == "ok" and foreign_key_errors == 0 and turn_mismatches == 0 and incomplete_turns == 0 and sessions_without_messages == 0 else "error",
            "integrity_check": integrity,
            "foreign_key_errors": foreign_key_errors,
            "turn_mismatches": turn_mismatches,
            "incomplete_turns": incomplete_turns,
            "sessions_without_messages": sessions_without_messages,
            "counts": counts,
            "pragmas": pragmas,
        }

    def set_evaluation(self, session_id: str, status: str, result: Mapping[str, Any] | None = None, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO evaluations(session_id, status, result_json, error, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET status=excluded.status,
                   result_json=excluded.result_json, error=excluded.error, updated_at=excluded.updated_at""",
                (session_id, status, json.dumps(result, ensure_ascii=False) if result is not None else None, error, utc_now()),
            )

    def get_evaluation(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM evaluations WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        result_json = value.pop("result_json")
        value["result"] = json.loads(result_json) if result_json else None
        return value

    def save_survey(self, session_id: str, response: Mapping[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO survey_responses(session_id, response_json, submitted_at) VALUES (?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET response_json=excluded.response_json, submitted_at=excluded.submitted_at""",
                (session_id, json.dumps(response, ensure_ascii=False), utc_now()),
            )

    def get_survey(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT response_json FROM survey_responses WHERE session_id=?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else None
