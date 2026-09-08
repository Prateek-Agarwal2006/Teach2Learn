# Changelog

All notable changes to this Teach2Learn RAG implementation.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — 2026-09-08

Real course textbooks ingested into the vector store for all four subjects, replacing
the single small placeholder fixture (`data/os/scheduling.txt`) that every prior test in
this file ran against. Source: the actual BITS Pilani course materials (course handouts
name these as the Text Books/Reference Books for CS F111/F211/F213/F372).

### Added

- `vectorstore/` committed to the repo, pre-built — 21,564 chunks across ~7,100 pages:

  | Subject | Source | Pages | Chunks |
  |---|---|---|---|
  | `cp` | Hanly & Koffman + 3 reference books | 2,289 | 7,530 |
  | `dsa` | CLRS + Goodrich/Tamassia/Mount | 2,033 | 5,605 |
  | `oop_java` | Schildt + Horstmann | 1,788 | 5,148 |
  | `os` | Silberschatz & Galvin | 983 | 3,281 |

  Committed so a collaborator can `git clone` and start testing immediately, without
  needing to run embeddings (real OpenRouter API calls) themselves. The raw source PDFs
  (~150MB, copyrighted textbooks) are **not** committed, only the derived vector store —
  see `.gitignore`.
- `vectorstore/catalog.json` topic lists for all four subjects (11/11/10/10 topics),
  drawn from the real course handout module breakdowns rather than an invented
  taxonomy — this is the first time `cp`/`dsa`/`oop_java` have had any topics at all;
  previously only `os` did (the placeholder fixture's one hand-typed entry).
- `README.md` — didn't exist before this project had any documentation of its own.

### Fixed

- `OpenAIEmbeddings` (used by `ingest.py`, `qa_generator.py`, `student_chain.py`) has no
  built-in OpenRouter override; pointing `OPENAI_API_KEY`/`OPENAI_BASE_URL` at
  OpenRouter's endpoint instead of requiring a separate real OpenAI account works
  (confirmed live) and is now documented in `.env.example`/`README.md`.
- `ingest.py`'s `DATA_DIR` wasn't wrapped in `Path()` when set via the env var (only the
  default value was ever a `Path`), so `DATA_DIR.exists()` raised `AttributeError` the
  moment anyone actually used the documented env var. One-line fix.

### Known gaps

- `CP_r2.pdf` (Forouzan & Gilberg) failed to parse — `EI stream not found`, a malformed
  PDF stream — and was skipped by `ingest.py`'s per-file error handling. `cp` is grounded
  in the other 4 of 5 CP sources; a fresh copy of that file would need re-ingesting to
  close this gap.
- Requires a real MongoDB instance and OpenRouter/Sarvam keys to actually run — this
  entry only covers the vector store; see the "2026-09-07" entry below for the
  multilingual/voice port, and its own verification notes for what was and wasn't tested
  end-to-end against a live Chainlit process.

### Verification

- Live smoke test: `build_student_chain` + `generate_qa_for_subtopic` against the real
  `cp` vectorstore for "Dynamic memory allocation" produced five Bloom's-taxonomy-ordered
  questions with textbook-accurate answers (correctly distinguishing `malloc` or
  `calloc`'s zero-initialization, discussing memory leaks and linked-list-based dynamic
  structures) — confirming retrieval is actually grounded in the ingested textbook
  content, not just the LLM's general knowledge.

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
