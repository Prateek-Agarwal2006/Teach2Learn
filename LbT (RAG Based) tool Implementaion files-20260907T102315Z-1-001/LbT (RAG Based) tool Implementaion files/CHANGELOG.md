# Changelog

All notable changes to this Teach2Learn RAG implementation.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — 2026-09-07

Multilingual teaching sessions and voice dictation, ported from the sibling
`teach2learn-portal` (FastAPI) implementation of Teach2Learn — closing the
"support multilingual learners" item named in the paper's Future Work section.
Only these two capabilities were ported; the RAG pipeline, agent chains, and
MongoDB data model are unchanged.

### Added

- `translation.py` — `TranslationService` wrapping Sarvam AI's translate API.
  Ported verbatim from `teach2learn-portal/app/services/translation.py`. Supports
  all 22 official Indic languages plus English (`SUPPORTED_LANGUAGES`). Never
  raises into callers: on missing key, HTTP error, timeout, or malformed response
  it returns the original text and logs a warning (`T2L_TRANSLATION_BACKEND=echo`
  exercises the boundary locally without a key).
- `transcription.py` — `TranscriptionService` for the voice-dictation feature.
  Ported verbatim from `teach2learn-portal/app/services/transcription.py`.
  `T2L_TRANSCRIPTION_BACKEND=sarvam` (default) calls Sarvam's Saaras v3
  speech-to-text model — full 22-language coverage, including the low-resource
  languages (Bodo, Dogri, Konkani, Kashmiri, Maithili, Manipuri, Odia, Santali)
  that Whisper has little to no training data for. `openrouter` calls Whisper
  large-v3 via OpenRouter instead (~15 languages transcribe well). Unlike
  translation, failures raise rather than silently passing through, since there
  is no safe fallback text for audio.
- Teaching-language picker in `main.py`'s `start()` (`cl.AskActionMessage`, same
  mechanism as the existing subject/subtopic pickers) — picked once per session,
  stored as `lang` in the Mongo `session` document (`memory.py:create_session`).
- Voice input via Chainlit's native microphone control (`on_audio_start` /
  `on_audio_chunk` / `on_audio_end` in `main.py`), enabled by
  `.chainlit/config.toml`'s `[features.audio]`. Unlike `teach2learn-portal`
  (which hand-builds a mic button and browser-side `MediaRecorder`/WAV-encoder
  in raw JS, because it fully controls its own HTML), Chainlit renders its own
  fixed UI — there is no template to inject a custom control into, so this is
  the only way to get microphone input into a Chainlit app at all. Recorded
  PCM16 chunks are wrapped into a WAV container with the stdlib `wave` module
  and handed to `TranscriptionService.transcribe()` unchanged.
- `on_message`'s body refactored into `handle_teacher_turn(teacher_explanation)`,
  called by both typed messages and the audio pipeline — dictated text flows
  through the exact same student/evaluator/scorer pipeline as typed text.
- `requirements.txt`, `.env.example`, `.chainlit/config.toml`, and `tests/`
  scaffolding, none of which existed in this project before (see Notes).

### Notes

- **No pre-existing scaffolding.** This project had no `requirements.txt`,
  `.env.example`, `.chainlit/config.toml`, or test suite before this change —
  all four are new, not modified.
- Only participant-visible text crosses the translation boundary: the teacher's
  explanation is translated to English before reaching `student_chain`,
  `evaluator_chain`, and `scorer_chain`, and only the translated-to-English text
  is what gets stored in Mongo (`TeacherResponse`) — mirroring
  `teach2learn-portal`'s "stored data always English" principle. The evaluator
  and scorer agents, and everything they produce, never see anything but
  English; only the student's follow-up question, the next QA-pool question,
  and the final summary's three comment lists are translated back out for
  display.
- Language coverage differs sharply by transcription backend (see Added above);
  `sarvam` is the default specifically because it is the only one of the two
  that covers all 22 of this app's teaching languages.
- The mic transcribes speech to text in whatever language was spoken — it does
  not translate. Translation to English happens afterward through the same
  `translation.py` boundary as a typed answer.
- No new third-party dependency beyond `httpx` (used by both ported services)
  and `pytest` (tests only) — both were already implied by the project's
  LangChain/Chainlit stack but never pinned anywhere until this change.

### Verification

- `pytest tests/` — 14 passed, covering both services with `echo`/mock-transport
  backends (no real API keys needed).
- Not yet run end-to-end against a live Chainlit process (needs Mongo reachable
  and the course-material vectorstore already ingested) — do this before
  enrolling participants: pick a non-English language at session start, confirm
  the opening question and student follow-ups render translated, confirm a
  Mongo `teacher` document stores the English-translated text (not the
  original), confirm the final summary is translated, and confirm a spoken
  explanation transcribes and feeds into the same flow as typed text.
