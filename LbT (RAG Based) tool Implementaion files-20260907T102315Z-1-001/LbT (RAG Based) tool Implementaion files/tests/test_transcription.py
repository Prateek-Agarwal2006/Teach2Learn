"""Framework-independent unit tests for transcription.py.

Ported from teach2learn-portal/tests/test_transcription.py: only the portions that
test TranscriptionService directly. The endpoint/session/mic-button tests from that
file have no Chainlit equivalent (no HTTP test client here) — see the plan notes.
"""

import asyncio
import io
import math
import wave
from array import array

import httpx
import pytest

import transcription
from transcription import MAX_CLIP_SECONDS, TranscriptionService, TranscriptionUnavailableError, split_wav


@pytest.fixture(autouse=True)
def instant_retries(monkeypatch):
    monkeypatch.setattr(transcription, "_RETRY_DELAYS", (0.0, 0.0))


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


def speech_like_wav(seconds: float, rate: int = 16000, channels: int = 1) -> bytes:
    """Loud 3 s tone bursts separated by 0.5 s of digital silence, so a good cut has somewhere to land."""
    tone = array("h", (int(8000 * math.sin(2 * math.pi * 220 * i / rate)) for i in range(int(3.0 * rate))))
    period = b"".join(
        tone[i : i + 1].tobytes() * channels for i in range(len(tone))
    ) + b"\x00\x00" * channels * int(0.5 * rate)
    frame_bytes = 2 * channels
    frames = int(seconds * rate)
    pcm = (period * (frames * frame_bytes // len(period) + 1))[: frames * frame_bytes]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def wav_info(audio: bytes) -> tuple[int, int, int, bytes]:
    with wave.open(io.BytesIO(audio), "rb") as clip:
        return clip.getnchannels(), clip.getframerate(), clip.getnframes(), clip.readframes(clip.getnframes())


def test_split_wav_leaves_short_and_non_wav_audio_alone():
    short = speech_like_wav(10)
    assert split_wav(short) == [short]
    assert split_wav(b"fake-audio") is None
    eight_bit = io.BytesIO()
    with wave.open(eight_bit, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(1)
        out.setframerate(8000)
        out.writeframes(b"\x80" * 8000 * 40)
    assert split_wav(eight_bit.getvalue()) is None


@pytest.mark.parametrize("rate,channels", [(16000, 1), (48000, 2)])
def test_split_wav_cuts_long_audio_into_pieces_under_the_limit_at_pauses(rate, channels):
    original = speech_like_wav(71.3, rate, channels)
    clips = split_wav(original)
    assert len(clips) == 3
    _, _, total_frames, original_pcm = wav_info(original)

    pieces = [wav_info(clip) for clip in clips]
    assert all(frames / clip_rate <= MAX_CLIP_SECONDS for _, clip_rate, frames, _ in pieces)
    # Nothing lost or duplicated: stitching the pieces back reproduces the recording exactly.
    assert sum(frames for _, _, frames, _ in pieces) == total_frames
    assert b"".join(pcm for *_, pcm in pieces) == original_pcm
    # Every cut sits inside a pause, not through a burst of speech.
    ten_ms = int(0.01 * rate) * channels * 2
    for (_, _, _, before), (_, _, _, after) in zip(pieces, pieces[1:]):
        assert before[-ten_ms:] == b"\x00" * ten_ms
        assert after[:ten_ms] == b"\x00" * ten_ms


def _multipart_clip_frames(request: httpx.Request) -> int:
    body = request.content
    return wav_info(body[body.index(b"RIFF") :].rsplit(b"\r\n--", 1)[0])[2]


def test_sarvam_transcribes_a_long_recording_in_pieces_and_joins_them_in_order(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    audio = speech_like_wav(71.3)
    expected_pieces = [wav_info(clip)[2] for clip in split_wav(audio)]
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", errors="ignore")
        seen.append('name="language_code"' in body and "od-IN" in body)
        # Each piece answers with its own length, so the joined text proves the original order.
        return httpx.Response(200, json={"transcript": str(_multipart_clip_frames(request))})

    service = TranscriptionService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    text = asyncio.run(service.transcribe(audio, "recording.wav", "audio/wav", "or"))
    asyncio.run(service.close())
    assert text == " ".join(str(frames) for frames in expected_pieces)
    assert len(seen) == 3 and all(seen)  # every piece carries the language hint


def test_sarvam_short_recording_is_still_a_single_call(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    calls = []
    service = TranscriptionService()
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: calls.append(1) or httpx.Response(200, json={"transcript": "ok"}))
    )
    assert asyncio.run(service.transcribe(speech_like_wav(20), "recording.wav", "audio/wav", "as")) == "ok"
    asyncio.run(service.close())
    assert len(calls) == 1


def test_sarvam_one_failed_piece_fails_the_whole_recording(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return httpx.Response(400 if count["n"] == 2 else 200, json={"transcript": "fine", "error": "bad"})

    service = TranscriptionService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):  # partial text must never pass as the whole answer
        asyncio.run(service.transcribe(speech_like_wav(71.3), "recording.wav", "audio/wav", "or"))
    asyncio.run(service.close())


def test_sarvam_retries_a_rate_limited_request_then_succeeds(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    statuses = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(status, json={"transcript": "finally"})

    service = TranscriptionService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(service.transcribe(speech_like_wav(10), "recording.wav", "audio/wav", "as")) == "finally"
    asyncio.run(service.close())


def test_sarvam_gives_up_after_the_retries_and_does_not_retry_a_bad_request(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    for status, expected_calls in ((429, 3), (400, 1)):
        calls = []
        service = TranscriptionService()
        service._client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request, s=status: calls.append(1) or httpx.Response(s, json={"error": "x"}))
        )
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(service.transcribe(speech_like_wav(10), "recording.wav", "audio/wav", "or"))
        asyncio.run(service.close())
        assert len(calls) == expected_calls, status


def test_sarvam_empty_piece_does_not_fail_the_recording_but_all_empty_does(monkeypatch):
    monkeypatch.setenv("T2L_TRANSCRIPTION_BACKEND", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    answers = iter(["first part", "", "last part"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transcript": next(answers)})

    service = TranscriptionService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    audio = speech_like_wav(71.3)
    text = asyncio.run(service.transcribe(audio, "recording.wav", "audio/wav", "or"))
    assert sorted(text.split(" ")) == sorted("first part last part".split(" "))

    service._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"transcript": ""})))
    with pytest.raises(ValueError, match="no text"):
        asyncio.run(service.transcribe(audio, "recording.wav", "audio/wav", "or"))
    asyncio.run(service.close())
