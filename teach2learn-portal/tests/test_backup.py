import sqlite3
import tarfile

from app.db import Database

from scripts.backup_to_relay import sha256, snapshot_database, snapshot_transcripts


def test_consistent_database_and_transcript_snapshots(tmp_path):
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE participants(id TEXT)")
        connection.execute("CREATE TABLE sessions(id TEXT)")
        connection.execute("CREATE TABLE evaluations(id TEXT)")
        connection.execute("CREATE TABLE survey_responses(id TEXT)")
        connection.execute("INSERT INTO participants VALUES ('participant-1')")

    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "session-1.jsonl").write_text('{"role":"user","content":"hello"}\n', encoding="utf-8")
    database_copy = tmp_path / "portal.sqlite3"
    transcript_copy = tmp_path / "transcripts.tar.gz"

    counts = snapshot_database(source, database_copy)
    transcript_count = snapshot_transcripts(transcripts, transcript_copy)

    assert counts["participants"] == 1
    assert transcript_count == 1
    assert len(sha256(database_copy)) == 64
    with sqlite3.connect(database_copy) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with tarfile.open(transcript_copy) as archive:
        assert archive.getnames() == ["session-1.jsonl"]
    assert database_copy.stat().st_mode & 0o777 == 0o600
    assert transcript_copy.stat().st_mode & 0o777 == 0o600


def test_transcript_archive_can_be_exported_from_database_snapshot(tmp_path):
    source = tmp_path / "source.sqlite3"
    database = Database(source)
    database.initialize()
    participant = database.create_participant("backup-student")
    session = database.create_session(
        participant,
        "OS",
        "Processes",
        {"turn": 0},
        opening_message={"role": "assistant", "content": "Teach me about processes.", "turn": 0},
    )
    copy = tmp_path / "copy.sqlite3"
    archive = tmp_path / "transcripts.tar.gz"
    counts = snapshot_database(source, copy)
    transcript_count = snapshot_transcripts(tmp_path / "unused", archive, database=copy)

    assert counts["messages"] == 1
    assert transcript_count == 1
    with tarfile.open(archive) as stream:
        content = stream.extractfile(f"{session}.jsonl").read().decode("utf-8")
    assert "Teach me about processes." in content
