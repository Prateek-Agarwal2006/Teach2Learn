from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_database(source: Path, target: Path) -> dict[str, int]:
    temporary = target.with_suffix(".part")
    temporary.unlink(missing_ok=True)
    with sqlite3.connect(source) as source_connection, sqlite3.connect(temporary) as target_connection:
        source_connection.backup(target_connection)
        if target_connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite snapshot failed integrity_check")
        if target_connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("SQLite snapshot failed foreign_key_check")
        available_tables = {
            row[0]
            for row in target_connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        counts = {
            table: target_connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("participants", "sessions", "messages", "evaluations", "survey_responses")
            if table in available_tables
        }
        source_connection.execute("PRAGMA optimize")
        source_connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
    temporary.chmod(0o600)
    temporary.replace(target)
    return counts


def snapshot_transcripts(source: Path, target: Path, *, database: Path | None = None) -> int:
    temporary = target.with_suffix(".part")
    temporary.unlink(missing_ok=True)
    with tarfile.open(temporary, "w:gz") as archive:
        if database is not None:
            with sqlite3.connect(database) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """SELECT session_id, sequence, role, turn, content, timestamp, metadata_json
                       FROM messages ORDER BY session_id, sequence"""
                ).fetchall()
            sessions: dict[str, list[dict[str, object]]] = {}
            for row in rows:
                record = {
                    "sequence": row["sequence"],
                    "role": row["role"],
                    "content": row["content"],
                    "turn": row["turn"],
                    "timestamp": row["timestamp"],
                    **json.loads(row["metadata_json"]),
                }
                sessions.setdefault(row["session_id"], []).append(record)
            for session_id, records in sessions.items():
                payload = "".join(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                    for record in records
                ).encode("utf-8")
                info = tarfile.TarInfo(f"{session_id}.jsonl")
                info.size = len(payload)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(payload))
            file_count = len(sessions)
        else:
            files = sorted(source.glob("*.jsonl")) if source.exists() else []
            for path in files:
                archive.add(path, arcname=path.name, recursive=False)
            file_count = len(files)
    temporary.chmod(0o600)
    temporary.replace(target)
    return file_count


def upload(directory: Path, day: str) -> None:
    host = os.environ["T2L_BACKUP_SFTP_HOST"]
    user = os.environ.get("T2L_BACKUP_SFTP_USER", "t2l-backup")
    key = Path(os.environ["T2L_BACKUP_SSH_KEY"]).expanduser().resolve()
    known_hosts = Path(os.environ["T2L_BACKUP_KNOWN_HOSTS"]).expanduser().resolve()
    commands: list[str] = []
    for local_name, remote_name in (
        ("portal.sqlite3", "latest/portal.sqlite3"),
        ("transcripts.tar.gz", "latest/transcripts.tar.gz"),
        ("manifest.json", "latest/manifest.json"),
        ("portal.sqlite3", f"daily/portal-{day}.sqlite3"),
        ("transcripts.tar.gz", f"daily/transcripts-{day}.tar.gz"),
        ("manifest.json", f"daily/manifest-{day}.json"),
    ):
        part = remote_name + ".part"
        commands.extend((f"put {directory / local_name} {part}", f"-rm {remote_name}", f"rename {part} {remote_name}"))
    with tempfile.NamedTemporaryFile("w", dir=directory, prefix="sftp-", suffix=".batch", delete=False) as batch:
        batch.write("\n".join(commands) + "\n")
        batch_path = Path(batch.name)
    batch_path.chmod(0o600)
    try:
        subprocess.run(
            [
                "sftp",
                "-q",
                "-b",
                str(batch_path),
                "-i",
                str(key),
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                f"UserKnownHostsFile={known_hosts}",
                "-o",
                "StrictHostKeyChecking=yes",
                f"{user}@{host}",
            ],
            check=True,
            timeout=180,
        )
    finally:
        batch_path.unlink(missing_ok=True)


def main() -> None:
    data_dir = Path(os.environ.get("T2L_DATA_DIR", "data")).expanduser().resolve()
    database_path = Path(os.environ.get("T2L_DATABASE_PATH", data_dir / "portal.sqlite3")).expanduser().resolve()
    transcript_dir = Path(os.environ.get("T2L_TRANSCRIPT_DIR", data_dir / "transcripts")).expanduser().resolve()
    replica_dir = data_dir / "replica"
    replica_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    replica_dir.chmod(0o700)

    lock_path = replica_dir / "backup.lock"
    with lock_path.open("a+") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        counts = snapshot_database(database_path, replica_dir / "portal.sqlite3")
        transcript_count = snapshot_transcripts(
            transcript_dir,
            replica_dir / "transcripts.tar.gz",
            database=replica_dir / "portal.sqlite3",
        )
        with sqlite3.connect(replica_dir / "portal.sqlite3") as replica_connection:
            schema_version = replica_connection.execute("PRAGMA user_version").fetchone()[0]
        now = datetime.now(timezone.utc)
        manifest = {
            "created_at": now.isoformat(),
            "database_schema_version": schema_version,
            "database_sha256": sha256(replica_dir / "portal.sqlite3"),
            "transcripts_sha256": sha256(replica_dir / "transcripts.tar.gz"),
            "transcript_files": transcript_count,
            "row_counts": counts,
        }
        manifest_path = replica_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        manifest_path.chmod(0o600)
        upload(replica_dir, now.date().isoformat())
        print(json.dumps({"status": "ok", "created_at": manifest["created_at"], "row_counts": counts}))


if __name__ == "__main__":
    main()
