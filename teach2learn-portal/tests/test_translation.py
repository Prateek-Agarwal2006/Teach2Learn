import asyncio
import json
import uuid
from base64 import b64encode

import httpx
import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from app.main import app, database, transcripts
from app.services.translation import (
    SUPPORTED_LANGUAGES,
    TranslationService,
    _SARVAM_CODES,
    _split_for_limit,
    normalize_language,
)


def set_participant_session(client: TestClient, participant_id: str) -> None:
    session = b64encode(json.dumps({"participant_id": participant_id}).encode("utf-8"))
    client.cookies.set("session", TimestampSigner("local-development-change-me").sign(session).decode("utf-8"))


def make_participant() -> dict:
    return database.get_or_create_participant(
        f"test-{uuid.uuid4().hex[:10]}",
        "Translation Tester",
        {
            "auth_provider": "google",
            "email": "tester@pilani.bits-pilani.ac.in",
            "hosted_domain": "pilani.bits-pilani.ac.in",
        },
    )


def test_normalize_language_rejects_unknown_codes():
    assert normalize_language("hi") == "hi"
    assert normalize_language("HI") == "hi"
    assert normalize_language("klingon") == "en"
    assert normalize_language(None) == "en"


def test_every_supported_language_has_a_sarvam_code():
    """A language in the picker with no code raises KeyError inside _translate_chunk,
    which the caller swallows into a silent untranslated passthrough."""
    assert SUPPORTED_LANGUAGES.keys() == _SARVAM_CODES.keys()
    # Sarvam spells Odia "od-IN"; the ISO 639-1 "or-IN" is rejected with a 400.
    assert _SARVAM_CODES["or"] == "od-IN"
    for code in SUPPORTED_LANGUAGES:
        assert normalize_language(code) == code


def test_passthrough_when_no_api_key(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    service = TranslationService()
    assert not service.is_enabled()
    assert asyncio.run(service.to_english("some text", "hi")) == "some text"


def test_echo_backend_translates_without_a_key(monkeypatch):
    monkeypatch.setenv("T2L_TRANSLATION_BACKEND", "echo")
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    service = TranslationService()
    assert asyncio.run(service.from_english("Give me an example.", "hi")) == "[hi] Give me an example."
    assert asyncio.run(service.from_english("Give me an example.", "en")) == "Give me an example."


def test_api_failure_falls_back_to_original_text(monkeypatch):
    monkeypatch.setenv("T2L_TRANSLATION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    service = TranslationService()
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "down"}))
    )
    assert asyncio.run(service.to_english("मुझे समझाओ", "hi")) == "मुझे समझाओ"
    asyncio.run(service.close())


def test_successful_call_is_cached(monkeypatch):
    monkeypatch.setenv("T2L_TRANSLATION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"translated_text": "What does this do?"})

    service = TranslationService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    for _ in range(3):
        assert asyncio.run(service.to_english("यह क्या करता है?", "hi")) == "What does this do?"
    assert len(calls) == 1
    assert calls[0]["source_language_code"] == "hi-IN"
    assert calls[0]["target_language_code"] == "en-IN"
    asyncio.run(service.close())


@pytest.mark.parametrize("limit", [40, 1000, 2000])
def test_split_for_limit_never_exceeds_the_limit(limit):
    text = "This is a sentence about scheduling. " * 200
    chunks = _split_for_limit(text, limit)
    assert "".join(chunks) == text
    assert all(len(chunk) <= limit for chunk in chunks)


def test_selection_form_offers_every_supported_language():
    with TestClient(app) as client:
        set_participant_session(client, make_participant()["id"])
        page = client.get("/study")
        assert page.status_code == 200
        for name in SUPPORTED_LANGUAGES.values():
            assert f">{name}</option>" in page.text


def test_session_stores_language_and_keeps_transcripts_english(monkeypatch):
    monkeypatch.setenv("T2L_TRANSLATION_BACKEND", "echo")
    with TestClient(app) as client:
        set_participant_session(client, make_participant()["id"])
        started = client.post(
            "/study/start",
            data={
                "model": "qwen3",
                "subject": "os",
                "topic": "foundations",
                "subtopic": "Purpose and services",
                "lang": "hi",
            },
            follow_redirects=False,
        )
        assert started.status_code == 303
        session_id = started.headers["location"].rsplit("/", 1)[-1]
        assert database.get_session(session_id)["metadata"]["lang"] == "hi"

        with client.websocket_connect(f"/ws/chat/{session_id}") as socket:
            socket.send_json({"message": "[hi] A scheduler decides which process runs next."})
            response = socket.receive_json()
            assert response["status"] == "evaluating"
            assert response["content"].startswith("[hi] ")
            assert socket.receive_json()["done"] is True

        stored = transcripts.read(session_id)
        teacher_turn = next(item for item in stored if item["role"] == "user")
        assert teacher_turn["content"] == "[en] [hi] A scheduler decides which process runs next."
        assert not any(item["content"].startswith("[hi] ") for item in stored)

        page = client.get(f"/sessions/{session_id}")
        assert page.status_code == 200
        assert "Hindi" in page.text


def test_invalid_language_falls_back_to_english():
    with TestClient(app) as client:
        set_participant_session(client, make_participant()["id"])
        started = client.post(
            "/study/start",
            data={
                "model": "qwen3",
                "subject": "os",
                "topic": "foundations",
                "subtopic": "Purpose and services",
                "lang": "klingon",
            },
            follow_redirects=False,
        )
        session_id = started.headers["location"].rsplit("/", 1)[-1]
        assert database.get_session(session_id)["metadata"]["lang"] == "en"


def test_schema_fragment_is_rejected_rather_than_returned(monkeypatch):
    """The real Punjabi payload must not reach the participant as their own words.

    translated_text is a non-empty string here, so the existing isinstance check passes
    it through. Only the schema guard stops it, and the participant then reads their
    sentence in English -- the same fallback as any other failure.
    """
    leak = (
        "{'description': 'The translation of the source sentence assuming the subject is "
        "female.', 'title': 'Female', 'type': 'string'}"
    )
    monkeypatch.setenv("T2L_TRANSLATION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    service = TranslationService()
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"translated_text": leak})
        )
    )
    original = "Every successful malloc must be matched by exactly one free."
    result = asyncio.run(service.translate(original, "en", "pa"))
    assert result == original
    assert "description" not in result


def test_ordinary_text_beginning_with_a_bracket_is_not_rejected(monkeypatch):
    """A bare leading bracket is not a leak; requiring a quoted key after it is the test."""
    from app.services.translation import looks_like_schema

    assert not looks_like_schema("[hi] Round-robin gives each process a fixed time quantum.")
    assert not looks_like_schema("[1] The scheduler decides which process runs next.")
    assert looks_like_schema("{'description': 'x', 'type': 'string'}")
