from __future__ import annotations

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database
from app.services.evaluation import EvaluationService
from app.services.transcripts import TranscriptStore


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "portal.sqlite3")
    db.initialize()
    return db


def test_session_evaluation_and_survey_round_trip(database):
    participant = database.create_participant("student-1", {"cohort": "A"})
    session = database.create_session(participant, "DSA", "Trees")
    assert database.get_session(session)["status"] == "active"
    assert database.complete_session(session)

    service = EvaluationService(database, lambda messages: {"score": len(messages)}, enabled=True)
    result = asyncio.run(service.evaluate(session, [{"role": "user", "content": "Explain trees"}]))
    assert result == {"score": 1}
    assert database.get_evaluation(session)["status"] == "completed"

    database.save_survey(session, {"rating": 5, "comment": "Useful"})
    assert database.get_survey(session)["rating"] == 5


def test_active_session_cannot_be_evaluated(database):
    participant = database.create_participant()
    session = database.create_session(participant, "OS")
    service = EvaluationService(database, lambda _: {"score": 1}, enabled=True)
    with pytest.raises(ValueError, match="completed"):
        asyncio.run(service.evaluate(session, []))


def test_transcript_concurrent_append_is_valid_jsonl(tmp_path):
    store = TranscriptStore(tmp_path / "transcripts")
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda number: store.append("session-1", {"number": number}), range(100)))
    records = store.read("session-1")
    assert len(records) == 100
    assert {record["number"] for record in records} == set(range(100))


def test_transcript_rejects_path_traversal(tmp_path):
    store = TranscriptStore(tmp_path)
    with pytest.raises(ValueError):
        store.append("../outside", {"content": "no"})


def test_database_backed_transcript_turn_is_atomic(database, tmp_path):
    participant = database.create_participant("student-atomic")
    session = database.create_session(
        participant,
        "OS",
        "Processes",
        {"turn": 0},
        opening_message={"role": "assistant", "content": "What is a process?", "turn": 0},
    )
    store = TranscriptStore(tmp_path / "transcripts", database)
    store.sync_session(session)
    store.record_turn(
        session,
        {"role": "user", "content": "A running program.", "turn": 1},
        {
            "role": "assistant",
            "content": "How does it differ from a thread?",
            "turn": 1,
            "latency_ms": 123,
            "inline_evaluation": {"score": 4},
        },
        {"turn": 1, "completion_reason": "max_turns"},
        complete=True,
    )

    records = store.read(session)
    assert [record["role"] for record in records] == ["assistant", "user", "assistant"]
    assert records[-1]["latency_ms"] == 123
    assert database.get_session(session)["status"] == "completed"
    assert database.get_session(session)["metadata"]["turn"] == 1
    assert store.mirror_report()["status"] == "ok"
    assert database.storage_report()["status"] == "ok"


def test_legacy_jsonl_is_imported_once(database, tmp_path):
    participant = database.create_participant("student-legacy")
    session = database.create_session(participant, "DSA", "Trees", {"turn": 1})
    directory = tmp_path / "transcripts"
    legacy = TranscriptStore(directory)
    legacy.append(session, {"role": "assistant", "content": "Start", "turn": 0})
    legacy.append(session, {"role": "user", "content": "Trees connect nodes.", "turn": 1})
    legacy.append(session, {"role": "assistant", "content": "What is the root?", "turn": 1})
    legacy.append(session, {"role": "user", "content": "A second legacy retry.", "turn": 1})
    legacy.append(session, {"role": "assistant", "content": "A second recorded reply.", "turn": 1})

    backed = TranscriptStore(directory, database)
    first = backed.synchronize()
    second = backed.synchronize()
    assert first["imported_messages"] == 5
    assert second["imported_messages"] == 0
    assert len(database.list_messages(session)) == 5
    assert database.storage_report()["status"] == "ok"
