import asyncio
import json
import uuid
from base64 import b64encode

import httpx
import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from app.main import app, database
from app.services.transcription import TranscriptionService, TranscriptionUnavailableError


def set_participant_session(client: TestClient, participant_id: str) -> None:
    session = b64encode(json.dumps({"participant_id": participant_id}).encode("utf-8"))
    client.cookies.set("session", TimestampSigner("local-development-change-me").sign(session).decode("utf-8"))


def make_participant() -> dict:
    return database.get_or_create_participant(
        f"test-{uuid.uuid4().hex[:10]}",
        "Transcription Tester",
        {
            "auth_provider": "google",
            "email": "tester@pilani.bits-pilani.ac.in",
            "hosted_domain": "pilani.bits-pilani.ac.in",
        },
    )


def start_session(client: TestClient) -> str:
    started = client.post(
        "/study/start",
        data={
            "model": "qwen3",
            "subject": "os",
            "topic": "foundations",
            "subtopic": "Purpose and services",
            "lang": "en",
        },
        follow_redirects=False,
    )
    assert started.status_code == 303
    return started.headers["location"].rsplit("/", 1)[-1]


def test_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    service = TranscriptionService()
    assert not service.is_enabled()
    with pytest.raises(TranscriptionUnavailableError):
        asyncio.run(service.transcribe(b"fake-audio", "clip.webm", "audio/webm"))


def test_echo_backend_returns_placeholder(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "echo")
    service = TranscriptionService()
    assert service.is_enabled()
    text = asyncio.run(service.transcribe(b"12345", "clip.webm", "audio/webm"))
    assert "5 bytes" in text


def test_sarvam_api_failure_raises(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    service = TranscriptionService()
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "down"}))
    )
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(service.transcribe(b"fake-audio", "clip.webm", "audio/webm"))
    asyncio.run(service.close())


def test_sarvam_call_hints_a_low_resource_language(monkeypatch):
    """Whisper has no training data for Santali; Sarvam does, so this backend
    is the one that must forward its language_code correctly."""
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", errors="ignore")
        assert request.headers["api-subscription-key"] == "test-key"
        seen["has_language_code"] = 'name="language_code"' in body and "sat-IN" in body
        return httpx.Response(200, json={"transcript": "Santali speech here."})

    service = TranscriptionService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    text = asyncio.run(service.transcribe(b"fake-audio", "clip.webm", "audio/webm", "sat"))
    assert text == "Santali speech here."
    assert seen["has_language_code"]
    asyncio.run(service.close())


def test_openrouter_call_hints_the_session_language(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", errors="ignore")
        seen["has_language"] = 'name="language"' in body and "hi" in body
        return httpx.Response(200, json={"text": "Yeh scheduler ka kaam hai."})

    service = TranscriptionService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    text = asyncio.run(service.transcribe(b"fake-audio", "clip.webm", "audio/webm", "hi"))
    assert text == "Yeh scheduler ka kaam hai."
    assert seen["has_language"]
    asyncio.run(service.close())


def test_openrouter_omits_hint_for_languages_whisper_does_not_know(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", errors="ignore")
        assert 'name="language"' not in body
        return httpx.Response(200, json={"text": "ok"})

    service = TranscriptionService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(service.transcribe(b"fake-audio", "clip.webm", "audio/webm", "brx"))
    asyncio.run(service.close())


def test_endpoint_requires_an_owned_active_session():
    with TestClient(app) as client:
        set_participant_session(client, make_participant()["id"])
        response = client.post(
            "/api/transcribe",
            data={"session_id": "does-not-exist"},
            files={"audio": ("clip.webm", b"fake-audio", "audio/webm")},
        )
        assert response.status_code == 404


def test_endpoint_transcribes_with_echo_backend(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "echo")
    with TestClient(app) as client:
        set_participant_session(client, make_participant()["id"])
        session_id = start_session(client)
        response = client.post(
            "/api/transcribe",
            data={"session_id": session_id},
            files={"audio": ("clip.webm", b"fake-audio-bytes", "audio/webm")},
        )
        assert response.status_code == 200
        assert "bytes" in response.json()["text"]


def test_chat_page_hides_mic_when_transcription_disabled(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "off")
    with TestClient(app) as client:
        set_participant_session(client, make_participant()["id"])
        session_id = start_session(client)
        page = client.get(f"/sessions/{session_id}")
        assert page.status_code == 200
        assert "data-mic-button" not in page.text


def test_chat_page_shows_mic_when_transcription_enabled(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "echo")
    with TestClient(app) as client:
        set_participant_session(client, make_participant()["id"])
        session_id = start_session(client)
        page = client.get(f"/sessions/{session_id}")
        assert page.status_code == 200
        assert "data-mic-button" in page.text
