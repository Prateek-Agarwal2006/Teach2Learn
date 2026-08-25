# Changelog

All notable changes to the EquitableT2L portal, kept in this folder alongside `multilingual_plan.md`.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — 2026-08-25

### Added

- Fourteen more teaching languages, taking the picker to all 22 Indic languages
  `sarvam-translate:v1` accepts plus English: Gujarati, Odia, Urdu, Assamese, Bodo, Dogri,
  Konkani, Kashmiri, Maithili, Manipuri, Nepali, Sanskrit, Santali, Sindhi.
  Only `SUPPORTED_LANGUAGES` and `_SARVAM_CODES` in `app/services/translation.py` changed —
  the picker, session metadata, and every render path read from those maps, so no route,
  template, or test needed modification.
- `tests/test_translation.py::test_every_supported_language_has_a_sarvam_code` — locks the two
  maps to the same key set. A language offered in the picker with no entry in `_SARVAM_CODES`
  raises `KeyError` inside `_translate_chunk`, which `translate()` catches and turns into a
  silent untranslated passthrough, so map drift is invisible at runtime.

### Notes

- The earlier eight-language set was a scope choice in `multilingual_plan.md`, not a Sarvam
  limitation; the plan's description of it as "Sarvam AI's supported Indic languages" was wrong.
- Sarvam spells Odia **`od-IN`**, not the ISO 639-1 `or-IN`, which is rejected with a 400.
  Codes are therefore kept as an explicit map rather than derived as `f"{key}-IN"`.
- Sindhi (`sd-IN`) comes back in Devanagari rather than Perso-Arabic script.
- Translation quality for the lower-resource additions is unverified beyond round-tripping one
  sentence. Because the judge reads the translated-to-English answer, poor inbound translation
  degrades evaluation and therefore Bloom completion. Worth a quality check per language before
  enrolling participants in one.

### Verification

- Full suite: **61 passed** (60 before, +1 new test).
- Live call to `sarvam-translate:v1` for all 22 non-English codes: every one returned translated
  text in the expected script, **zero** silent passthroughs.

## [Unreleased] — 2026-08-18

Multilingual expansion, implementing `multilingual_plan.md`. Participants can now teach in
Hindi, Tamil, Telugu, Kannada, Bengali, Malayalam, Marathi, or Punjabi. Translation wraps only
participant-visible text; inference, evaluation, and stored research data remain English.

### Added

- `app/services/translation.py` — `TranslationService` wrapping the Sarvam AI translate API.
  Never raises into callers: on missing key, HTTP error, timeout, or malformed response it
  returns the original text and logs a warning. Includes an in-process cache keyed on
  `(text, source, target)` and sentence-boundary splitting for text above the model input limit.
- Teaching-language picker on the topic-selection form (`app/templates/select.html`); the chosen
  code is stored as `lang` in session metadata.
- Language name shown in the chat session header (`app/templates/chat.html`).
- `T2L_TRANSLATION_BACKEND=echo` mode, which prefixes text with the target language code so the
  translation boundary can be verified locally without a Sarvam API key.
- Local development setup that does not disturb the existing production `.env`:
  `.env.local`, `scripts/run-local.sh`, and a `/dev/login` route that signs in a throwaway
  participant. The route is only registered when `APP_ENV` is not `production` **and**
  `T2L_DEV_LOGIN_ENABLED` is true.
- `tests/test_translation.py` — 8 test functions (11 cases with parametrization) covering
  language-code normalization, passthrough with no
  key, echo mode, API-failure fallback, caching, chunk splitting, the language picker, and an
  end-to-end Hindi session asserting that transcripts stay English.
- `default_language` setting in `app/config.py`, from `T2L_DEFAULT_LANGUAGE`.
- `scripts/check_keys.py` — verifies the Sarvam and OpenRouter keys in `.env.local` with one live
  call each, so a bad key fails loudly here instead of silently degrading a session to English.

### Changed

- `app/main.py`:
  - `/study/start` accepts an optional `lang` form field, normalized against the supported set,
    and stores it in session metadata.
  - The WebSocket turn handler translates the participant's answer into English before building
    the inference history, and translates the learner's question (both the early preview and the
    final payload) back into the participant's language before sending.
  - `/sessions/{id}`, `/sessions/{id}/complete`, and `/history/{id}` translate stored English
    content at render time.
  - The translation client is closed during application shutdown.
  - The survey validation-error path re-renders feedback in the participant's language rather than
    flipping back to English.
- `.env.example`, `README.md`, `.gitignore` updated for the new settings and local-run files.

### Unchanged by design

- Transcripts and the database always store English. The private `<evaluation>` block,
  `raw_content`, Bloom completion logic, and the OpenRouter judge prompts are never translated,
  so early completion and research analysis behave exactly as before.
- Admin views render the stored English text.
- No new Python dependency; Sarvam is called over the existing `httpx`.

### Known limitations

- **Interface chrome is still English.** Plan Problem 9 (a `ui_strings` dict for buttons, headings,
  survey questions, and Likert labels) was deliberately not implemented. A participant teaching in
  Tamil gets a Tamil conversation and Tamil feedback inside an English interface. Worth deciding on
  before participant enrollment.
- **`localized_messages` issues one API call per message, concurrently.** Opening a completed
  six-turn session on a cold cache fires roughly a dozen simultaneous Sarvam requests. Fine at
  study scale; revisit if many participants browse history at once.

### Verification

- Full suite: **60 passed**. Baseline before this work was 49 passed; the 11 added cases all come
  from `tests/test_translation.py`. No existing test needed modification.
- Manual end-to-end Hindi session against the running app with `T2L_TRANSLATION_BACKEND=echo`:
  language picker renders, session metadata records `lang=hi`, outbound questions arrive
  translated, stored transcript rows contain no translated markers, inline evaluations parse
  in English, and the session still auto-completed at turn 4 on `knowledge_threshold` — matching
  the English-only baseline.

### Required before production use

- **`SARVAM_API_KEY`** from the sarvam.ai dashboard is the only *new* credential. Without it the
  language picker still appears but every session runs in English.
- **`OPENROUTER_API_KEY`** is a pre-existing requirement, not new, and is already set in the
  production `.env`. It is worth re-stating here because the judge now sits *inside* the English
  zone: it reads the translated-to-English answer and returns English feedback that is then
  translated back out. Two consequences:
  - Judge quality now depends on inbound translation quality.
  - If Sarvam fails and passes through, the judge receives raw Hindi/Tamil. Its evaluation
    degrades, and because that evaluation drives Bloom completion, affected sessions may run to
    `max_turns` instead of completing early. Watch for `translation_failed` warnings alongside
    `openrouter_turn_evaluation_failed` — that pairing is the compounding failure mode.
  - Without the key the app still runs: both judge roles fall back to the local adapter. Under
    `INFERENCE_BACKEND=fake` that fallback is scripted filler, so locally observed feedback text
    is not representative.
- Keep `SARVAM_MODEL=sarvam-translate:v1`. It accepts 2000 input characters, matching the
  portal's 2000-character input cap; `mayura:v1` accepts only 1000 and would silently drop
  long explanations back to untranslated text.
### Live verification with real keys (plan Phase 8b — done)

Full Hindi session against the running portal with live `SARVAM_API_KEY` and `OPENROUTER_API_KEY`:

- Opening message, every learner question, and all five feedback fields rendered in Devanagari.
- Stored transcript rows were English throughout; Hindi input round-tripped correctly
  (`शेड्यूलर ऑपरेटिंग सिस्टम का वह हिस्सा है…` → `The scheduler is the part of the operating system which
  decides which process to run on the CPU`).
- **Zero** `translation_failed` and **zero** `openrouter_*_failed` warnings across the session.
- Confirmed the request payload against the live API. Dropping the plan's `"mode": "formal"` field
  was necessary: `sarvam-translate:v1` supports only formal mode, and sending model-scoped
  parameters risks a 400 that would degrade silently to untranslated text.
