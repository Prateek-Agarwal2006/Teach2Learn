"""Framework-independent unit tests for translation.py.

Ported from teach2learn-portal/tests/test_translation.py: only the portions that
test TranslationService directly (no FastAPI TestClient, no HTTP endpoints — this
project has no equivalent test harness for its Chainlit UI, see the plan notes).
"""

import asyncio
import json

import httpx
import pytest

from translation import (
    SUPPORTED_LANGUAGES,
    TranslationService,
    _SARVAM_CODES,
    _split_for_limit,
    normalize_language,
)


def test_normalize_language_rejects_unknown_codes():
    assert normalize_language("hi") == "hi"
    assert normalize_language("HI") == "hi"
    assert normalize_language("klingon") == "en"
    assert normalize_language(None) == "en"


def test_every_supported_language_has_a_sarvam_code():
    """A language offered with no entry in _SARVAM_CODES raises KeyError inside
    _translate_chunk, which translate() catches and turns into a silent
    untranslated passthrough, so map drift is invisible at runtime."""
    assert SUPPORTED_LANGUAGES.keys() == _SARVAM_CODES.keys()
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
    calls = []

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


def test_speaker_gender_is_sent_only_when_given(monkeypatch):
    """Hindi (and other gendered languages) need a hint for verb agreement the AI
    student persona's own lines don't get from English -- but only when a caller
    asks for it, since blindly gendering the teacher's own words would be wrong."""
    monkeypatch.setenv("T2L_TRANSLATION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"translated_text": "अगला प्रश्न"})

    service = TranslationService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(service.from_english("Next question", "hi", speaker_gender="Female"))
    asyncio.run(service.from_english("Your explanation", "hi"))
    assert calls[0]["speaker_gender"] == "Female"
    assert "speaker_gender" not in calls[1]
    asyncio.run(service.close())


@pytest.mark.parametrize("limit", [40, 1000, 2000])
def test_split_for_limit_never_exceeds_the_limit(limit):
    text = "This is a sentence about scheduling. " * 200
    chunks = _split_for_limit(text, limit)
    assert "".join(chunks) == text
    assert all(len(chunk) <= limit for chunk in chunks)


def test_schema_fragment_is_rejected_rather_than_returned(monkeypatch):
    """The real Punjabi payload must not reach the participant as their own words.

    translated_text is a non-empty string here, so the existing isinstance check passes
    it through. Only the schema guard stops it, and the participant then reads their
    sentence in English -- the same fallback as any other failure. Ported from
    teach2learn-portal's fix for the identical Sarvam defect (byte-identical translation.py).
    """
    leak = (
        "{'description': 'The translation of the source sentence assuming the subject is "
        "female.', 'title': 'Female', 'type': 'string'}"
    )
    monkeypatch.setenv("T2L_TRANSLATION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    service = TranslationService()
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"translated_text": leak}))
    )
    original = "Every successful malloc must be matched by exactly one free."
    result = asyncio.run(service.translate(original, "en", "pa"))
    assert result == original
    assert "description" not in result


def test_ordinary_text_beginning_with_a_bracket_is_not_rejected():
    """A bare leading bracket is not a leak; requiring a quoted key after it is the test."""
    from translation import looks_like_schema

    assert not looks_like_schema("[hi] Round-robin gives each process a fixed time quantum.")
    assert not looks_like_schema("[1] The scheduler decides which process runs next.")
    assert looks_like_schema("{'description': 'x', 'type': 'string'}")
