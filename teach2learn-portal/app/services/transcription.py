"""Server-side speech-to-text for the chat composer's voice input.

Two backends are available:

- "sarvam" (default) calls Sarvam AI's own speech-to-text model (Saaras),
  which — unlike Whisper — has real training data for all 22 of the app's
  Indic teaching languages, including the low-resource ones (Bodo, Dogri,
  Konkani, Kashmiri, Maithili, Manipuri, Odia, Santali). Reuses the same
  SARVAM_API_KEY as the translation service.
- "openrouter" calls Whisper large-v3 through OpenRouter, reusing the same
  key already used for feedback/evaluation. Whisper only has meaningful
  training data for ~15 of the 22 languages, so speech in the other 8 will
  transcribe poorly regardless of the language hint.

Both also support "echo" (placeholder, no key needed, for local testing) and
"off" (hides the mic button). Unlike translation there is no safe fallback
text for audio, so failures raise instead of silently returning something
wrong.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import wave
from array import array

import httpx

from app.services.translation import _SARVAM_CODES, normalize_language

logger = logging.getLogger("teach2learn.transcription")

SARVAM_TRANSCRIPTION_URL = "https://api.sarvam.ai/speech-to-text"
OPENROUTER_TRANSCRIPTION_URL = "https://openrouter.ai/api/v1/audio/transcriptions"

# Whisper expects an ISO-639-1 code and only recognises a subset of our
# languages; for the rest we omit the hint and let it auto-detect instead.
_WHISPER_LANGUAGE_HINTS = {"en", "hi", "ta", "te", "kn", "bn", "ml", "mr", "pa", "gu", "ur", "as", "ne", "sa", "sd"}


# Sarvam's synchronous speech-to-text endpoint rejects any clip over 30 seconds with HTTP 400
# ("Audio duration exceeds the maximum limit of 30 seconds"), in every language -- and a
# teacher explaining a concept routinely talks longer than that. Longer recordings are cut
# into clips below the limit, transcribed, and the text joined.
MAX_CLIP_SECONDS = 25.0
# Each cut goes at the quietest 20 ms in the last few seconds before the limit, so it lands in
# a pause between words rather than through one.
_CUT_SEARCH_SECONDS = 5.0
_CUT_WINDOW_SECONDS = 0.02
_MAX_PARALLEL_CLIPS = 3
# A long recording is several requests, so one rate-limit (429) or brief outage on any of them
# would otherwise fail the whole recording; each request gets a couple of delayed retries.
_RETRY_STATUSES = frozenset({429, 502, 503, 504})
_RETRY_DELAYS = (1.0, 2.0)


def _wav_bytes(pcm: bytes, channels: int, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def split_wav(audio: bytes, max_seconds: float = MAX_CLIP_SECONDS) -> list[bytes] | None:
    """Split 16-bit PCM WAV audio into clips of at most ``max_seconds``, cutting at pauses.

    Returns ``[audio]`` untouched when it is already short enough, and None when it is not
    16-bit PCM WAV at all (the caller then sends it as-is and lets the provider decide).
    """
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            channels, width, rate, frames = source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getnframes()
            if width != 2 or source.getcomptype() != "NONE" or channels < 1 or rate < 1:
                return None
            pcm = source.readframes(frames)
    except (wave.Error, EOFError):
        return None
    max_frames = int(max_seconds * rate)
    if frames <= max_frames:
        return [audio]

    frame_bytes = channels * 2
    samples = array("h")
    samples.frombytes(pcm[: frames * frame_bytes])
    window = max(1, int(_CUT_WINDOW_SECONDS * rate))
    search = int(_CUT_SEARCH_SECONDS * rate)
    clips: list[bytes] = []
    start = 0
    while frames - start > max_frames:
        limit = start + max_frames
        cut, quietest = limit, None
        # Never search so far back that clips get short; <= keeps the latest of equally quiet spots.
        for pos in range(max(start + max_frames // 2, limit - search), limit - window + 1, window):
            energy = sum(abs(v) for v in samples[pos * channels : (pos + window) * channels])
            if quietest is None or energy <= quietest:
                cut, quietest = pos + window // 2, energy
        clips.append(_wav_bytes(pcm[start * frame_bytes : cut * frame_bytes], channels, rate))
        start = cut
    clips.append(_wav_bytes(pcm[start * frame_bytes : frames * frame_bytes], channels, rate))
    return clips


class TranscriptionUnavailableError(RuntimeError):
    """Raised when no usable transcription backend is configured."""


class TranscriptionService:
    """Transcribe recorded speech to text, raising on failure rather than guessing."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def backend(self) -> str:
        return os.getenv("T2L_TRANSCRIPTION_BACKEND", "sarvam").strip().lower()

    @property
    def api_key(self) -> str:
        env_name = "SARVAM_API_KEY" if self.backend == "sarvam" else "OPENROUTER_API_KEY"
        return os.getenv(env_name, "").strip()

    @property
    def sarvam_model(self) -> str:
        return os.getenv("SARVAM_STT_MODEL", "saaras:v3").strip() or "saaras:v3"

    @property
    def whisper_model(self) -> str:
        return os.getenv("WHISPER_MODEL", "openai/whisper-large-v3").strip() or "openai/whisper-large-v3"

    @property
    def timeout(self) -> float:
        try:
            return max(5.0, float(os.getenv("WHISPER_TIMEOUT_SECONDS", "30")))
        except ValueError:
            return 30.0

    def is_enabled(self) -> bool:
        if self.backend == "echo":
            return True
        return self.backend in {"sarvam", "openrouter"} and bool(self.api_key)

    async def transcribe(self, audio: bytes, filename: str, content_type: str, language: str | None = None) -> str:
        """Transcribe an audio clip, raising TranscriptionUnavailableError or the underlying error."""
        if not self.is_enabled():
            raise TranscriptionUnavailableError("No transcription backend is configured.")
        if self.backend == "echo":
            return f"(echo transcription — received {len(audio)} bytes)"
        if self.backend == "sarvam":
            return await self._transcribe_sarvam(audio, filename, content_type, language)
        return await self._transcribe_openrouter(audio, filename, content_type, language)

    async def _transcribe_sarvam(self, audio: bytes, filename: str, content_type: str, language: str | None) -> str:
        clips = split_wav(audio) or [audio]
        if len(clips) == 1:
            return await self._sarvam_clip(clips[0], filename, content_type, language)

        gate = asyncio.Semaphore(_MAX_PARALLEL_CLIPS)

        async def one(clip: bytes) -> str:
            async with gate:
                # A pause-only piece can legitimately come back empty without the whole recording failing.
                return await self._sarvam_clip(clip, "recording.wav", "audio/wav", language, allow_empty=True)

        results = await asyncio.gather(*(one(clip) for clip in clips), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        text = " ".join(piece for piece in results if piece)
        if not text:
            raise ValueError("Transcription returned no text")
        return text

    async def _sarvam_clip(
        self, audio: bytes, filename: str, content_type: str, language: str | None, allow_empty: bool = False
    ) -> str:
        data = {"model": self.sarvam_model}
        lang = normalize_language(language) if language else None
        if lang and lang in _SARVAM_CODES:
            data["language_code"] = _SARVAM_CODES[lang]
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                response = await self._get_client().post(
                    SARVAM_TRANSCRIPTION_URL,
                    headers={"api-subscription-key": self.api_key},
                    data=data,
                    files={"file": (filename or "recording.webm", audio, content_type or "audio/webm")},
                )
                response.raise_for_status()
                break
            except Exception as exc:
                self._log_failure(exc)
                retryable = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _RETRY_STATUSES
                if not retryable or attempt == len(_RETRY_DELAYS):
                    raise
                await asyncio.sleep(_RETRY_DELAYS[attempt])
        text = response.json().get("transcript")
        text = text.strip() if isinstance(text, str) else ""
        if not text and not allow_empty:
            raise ValueError("Transcription returned no text")
        return text

    async def _transcribe_openrouter(self, audio: bytes, filename: str, content_type: str, language: str | None) -> str:
        data = {"model": self.whisper_model}
        hint = (language or "").strip().lower()[:5]
        if hint in _WHISPER_LANGUAGE_HINTS:
            data["language"] = hint
        try:
            response = await self._get_client().post(
                OPENROUTER_TRANSCRIPTION_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files={"file": (filename or "recording.webm", audio, content_type or "audio/webm")},
            )
            response.raise_for_status()
        except Exception as exc:
            self._log_failure(exc)
            raise
        text = response.json().get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Transcription returned no text")
        return text.strip()

    def _log_failure(self, exc: Exception) -> None:
        detail = ""
        if isinstance(exc, httpx.HTTPStatusError):
            detail = f" status={exc.response.status_code} body={exc.response.text[:200]!r}"
        logger.warning("transcription_failed backend=%s error=%s%s", self.backend, type(exc).__name__, detail)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client


_transcription_service: TranscriptionService | None = None


def get_transcription_service() -> TranscriptionService:
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = TranscriptionService()
    return _transcription_service
