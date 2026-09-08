"""Framework-independent unit tests for transcription.py.

Ported from teach2learn-portal/tests/test_transcription.py: only the portions that
test TranscriptionService directly. The endpoint/session/mic-button tests from that
file have no Chainlit equivalent (no HTTP test client here) — see the plan notes.
"""

import asyncio

import httpx
import pytest

from transcription import TranscriptionService, TranscriptionUnavailableError


def test_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    service = TranscriptionService()
    assert not service.is_enabled()
    with pytest.raises(TranscriptionUnavailableError):
        asyncio.run(service.transcribe(b"fake-audio", "clip.wav", "audio/wav"))


def test_echo_backend_returns_placeholder(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "echo")
    service = TranscriptionService()
    assert service.is_enabled()
    text = asyncio.run(service.transcribe(b"12345", "clip.wav", "audio/wav"))
    assert "5 bytes" in text


def test_sarvam_api_failure_raises(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    service = TranscriptionService()
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "down"}))
    )
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(service.transcribe(b"fake-audio", "clip.wav", "audio/wav"))
    asyncio.run(service.close())


def test_sarvam_call_hints_a_low_resource_language(monkeypatch):
    """Whisper has no training data for Santali; Sarvam does, so this backend is
    the one that must forward its language_code correctly."""
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
    text = asyncio.run(service.transcribe(b"fake-audio", "clip.wav", "audio/wav", "sat"))
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
    text = asyncio.run(service.transcribe(b"fake-audio", "clip.wav", "audio/wav", "hi"))
    assert text == "Yeh scheduler ka kaam hai."
    assert seen["has_language"]
    asyncio.run(service.close())
