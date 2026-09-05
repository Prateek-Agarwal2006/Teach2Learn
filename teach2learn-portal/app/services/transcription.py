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

import logging
import os

import httpx

from app.services.translation import _SARVAM_CODES, normalize_language

logger = logging.getLogger("teach2learn.transcription")

SARVAM_TRANSCRIPTION_URL = "https://api.sarvam.ai/speech-to-text"
OPENROUTER_TRANSCRIPTION_URL = "https://openrouter.ai/api/v1/audio/transcriptions"

# Whisper expects an ISO-639-1 code and only recognises a subset of our
# languages; for the rest we omit the hint and let it auto-detect instead.
_WHISPER_LANGUAGE_HINTS = {"en", "hi", "ta", "te", "kn", "bn", "ml", "mr", "pa", "gu", "ur", "as", "ne", "sa", "sd"}


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
        data = {"model": self.sarvam_model}
        lang = normalize_language(language) if language else None
        if lang and lang in _SARVAM_CODES:
            data["language_code"] = _SARVAM_CODES[lang]
        try:
            response = await self._get_client().post(
                SARVAM_TRANSCRIPTION_URL,
                headers={"api-subscription-key": self.api_key},
                data=data,
                files={"file": (filename or "recording.webm", audio, content_type or "audio/webm")},
            )
            response.raise_for_status()
        except Exception as exc:
            self._log_failure(exc)
            raise
        text = response.json().get("transcript")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Transcription returned no text")
        return text.strip()

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
