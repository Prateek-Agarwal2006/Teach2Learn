"""Sarvam AI translation boundary with passthrough fallback.

Only participant-visible text crosses this boundary. Inference, the inline
<evaluation> block, Bloom completion logic, and everything stored in the
database stay English so research analysis and adapter prompts are unaffected.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx

logger = logging.getLogger("teach2learn.translation")

SARVAM_TRANSLATE_URL = "https://api.sarvam.ai/translate"

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "bn": "Bengali",
    "ml": "Malayalam",
    "mr": "Marathi",
    "pa": "Punjabi",
    "gu": "Gujarati",
    "or": "Odia",
    "ur": "Urdu",
    "as": "Assamese",
    "brx": "Bodo",
    "doi": "Dogri",
    "kok": "Konkani",
    "ks": "Kashmiri",
    "mai": "Maithili",
    "mni": "Manipuri",
    "ne": "Nepali",
    "sa": "Sanskrit",
    "sat": "Santali",
    "sd": "Sindhi",
}

# Sarvam's own code for a language is not always the ISO 639-1 one: Odia is
# "od-IN", not "or-IN". Sending the ISO code is rejected with a 400, which the
# service would swallow into an untranslated passthrough, so keep this mapping
# authoritative rather than deriving codes as f"{key}-IN".
_SARVAM_CODES = {
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "bn": "bn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "pa": "pa-IN",
    "gu": "gu-IN",
    "or": "od-IN",
    "ur": "ur-IN",
    "as": "as-IN",
    "brx": "brx-IN",
    "doi": "doi-IN",
    "kok": "kok-IN",
    "ks": "ks-IN",
    "mai": "mai-IN",
    "mni": "mni-IN",
    "ne": "ne-IN",
    "sa": "sa-IN",
    "sat": "sat-IN",
    "sd": "sd-IN",
}

# sarvam-translate:v1 accepts 2000 input characters, mayura:v1 only 1000.
_MODEL_INPUT_LIMITS = {"sarvam-translate:v1": 2000, "mayura:v1": 1000}
_DEFAULT_MODEL = "sarvam-translate:v1"
_CACHE_LIMIT = 512


def normalize_language(value: str | None) -> str:
    """Return a supported language code, falling back to English."""
    code = str(value or "").strip().lower()[:5]
    return code if code in SUPPORTED_LANGUAGES else "en"


# Sarvam has returned fragments of its own OpenAPI schema in translated_text instead of a
# translation -- reproducibly, for particular (sentence, language) pairs (a Punjabi sentence
# in the CP lesson does it on every attempt). The payload is a non-empty string, so it would
# otherwise reach the model as the participant's own words, be stored, and be shown back on
# screen. Ported from teach2learn-portal/app/services/translation.py so the two systems'
# live paths cannot disagree about what a leak looks like.
#
# The opening bracket must be followed by a quoted key. Matching a bare leading bracket also
# matches ordinary prose beginning with one, including every line the echo backend produces.
_SCHEMA_LEAK = re.compile(
    r"^\s*[\{\[]\s*['\"]|['\"](?:type|title|description|properties|\$ref)['\"]\s*:", re.I
)


def looks_like_schema(text: str) -> bool:
    """True when Sarvam returned API documentation where a translation belongs."""
    return bool(_SCHEMA_LEAK.search(text or ""))


class TranslationService:
    """Translate participant-visible text, never raising into the caller."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[tuple[str, str, str], str] = {}

    @property
    def api_key(self) -> str:
        return os.getenv("SARVAM_API_KEY", "").strip()

    @property
    def backend(self) -> str:
        return os.getenv("T2L_TRANSLATION_BACKEND", "sarvam").strip().lower()

    @property
    def model(self) -> str:
        value = os.getenv("SARVAM_MODEL", _DEFAULT_MODEL).strip()
        return value if value in _MODEL_INPUT_LIMITS else _DEFAULT_MODEL

    @property
    def timeout(self) -> float:
        try:
            return max(1.0, float(os.getenv("SARVAM_TIMEOUT_SECONDS", "5")))
        except ValueError:
            return 5.0

    def is_enabled(self) -> bool:
        """Translation only runs when a backend is actually usable."""
        if self.backend == "echo":
            return True
        return self.backend == "sarvam" and bool(self.api_key)

    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        speaker_gender: str | None = None,
    ) -> str:
        """Translate text, returning the original on any failure.

        speaker_gender ("Male"/"Female") tells Sarvam which grammatical gender to use
        for verb forms that many target languages require even when English gave no
        hint (Hindi "समझ गई" vs "समझ गया" for "I understood"). Only pass this for text
        the AI student persona itself is speaking -- never for translating the
        teacher's own words back to them, since that would put words in their mouth
        in a gender they may not be.
        """
        source_lang = normalize_language(source_lang)
        target_lang = normalize_language(target_lang)
        if not text.strip() or source_lang == target_lang or not self.is_enabled():
            return text

        cache_key = (text, source_lang, target_lang, speaker_gender)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            chunks = _split_for_limit(text, _MODEL_INPUT_LIMITS[self.model])
            translated = "".join(
                await asyncio.gather(
                    *(
                        self._translate_chunk(chunk, source_lang, target_lang, speaker_gender)
                        for chunk in chunks
                    )
                )
            )
        except Exception as exc:
            # This warning is the only signal a misconfigured key ever produces,
            # because the participant silently keeps going in English.
            detail = ""
            if isinstance(exc, httpx.HTTPStatusError):
                detail = f" status={exc.response.status_code} body={exc.response.text[:200]!r}"
            logger.warning(
                "translation_failed source=%s target=%s error=%s%s",
                source_lang,
                target_lang,
                type(exc).__name__,
                detail,
            )
            return text

        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        self._cache[cache_key] = translated
        return translated

    async def to_english(self, text: str, source_lang: str) -> str:
        return await self.translate(text, source_lang, "en")

    async def from_english(
        self, text: str, target_lang: str, speaker_gender: str | None = None
    ) -> str:
        return await self.translate(text, "en", target_lang, speaker_gender=speaker_gender)

    async def all_from_english(
        self, texts: list[str], target_lang: str, speaker_gender: str | None = None
    ) -> list[str]:
        return list(
            await asyncio.gather(
                *(self.from_english(item, target_lang, speaker_gender=speaker_gender) for item in texts)
            )
        )

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _translate_chunk(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        speaker_gender: str | None = None,
    ) -> str:
        if self.backend == "echo":
            return f"[{target_lang}] {text}"
        payload = {
            "input": text,
            "source_language_code": _SARVAM_CODES[source_lang],
            "target_language_code": _SARVAM_CODES[target_lang],
            "model": self.model,
        }
        if speaker_gender:
            payload["speaker_gender"] = speaker_gender
        response = await self._get_client().post(
            SARVAM_TRANSLATE_URL,
            headers={"api-subscription-key": self.api_key},
            json=payload,
        )
        response.raise_for_status()
        translated = response.json().get("translated_text")
        if not isinstance(translated, str) or not translated.strip():
            raise ValueError("Sarvam returned no translated text")
        if looks_like_schema(translated):
            # Raising routes this into translate()'s handler, which logs and returns the
            # original text -- the participant reads their own sentence in English, the
            # same fallback as a dead key, rather than a wall of JSON.
            raise ValueError(f"Sarvam returned a schema fragment: {translated[:120]!r}")
        return translated


def _split_for_limit(text: str, limit: int) -> list[str]:
    """Split on sentence boundaries so no chunk exceeds the model input limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for piece in re.findall(r"[^.!?\n]*(?:[.!?\n]+|$)", text):
        if not piece:
            continue
        while len(piece) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece[:limit])
            piece = piece[limit:]
        if len(current) + len(piece) > limit:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current:
        chunks.append(current)
    return chunks


_translation_service: TranslationService | None = None


def get_translation_service() -> TranslationService:
    global _translation_service
    if _translation_service is None:
        _translation_service = TranslationService()
    return _translation_service
