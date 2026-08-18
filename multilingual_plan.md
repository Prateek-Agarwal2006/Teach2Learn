# Multilingual Support — Implementation Plan

## Goal

Add an opt-in translation layer so participants can teach in **Hindi, Tamil, Telugu, Kannada, Bengali, Malayalam, Marathi, or Punjabi** (Sarvam AI's supported Indic languages). The core inference, evaluation, and completion pipelines remain **English-only** — translation wraps only user-visible I/O.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BROWSER                                     │
│  User types in Hindi/Tamil/etc.                                     │
│  User reads AI questions in Hindi/Tamil/etc.                        │
└──────────────────┬──────────────────────────────────────────────────┘
                   │  WebSocket / HTTP
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   TRANSLATION BOUNDARY (NEW)                        │
│  app/services/translation.py — SarvamTranslationService             │
│                                                                     │
│  translate_to_english(text, source_lang) → english_text             │
│  translate_from_english(text, target_lang) → localized_text         │
│  detect_language(text) → lang_code  (optional auto-detect)          │
└──────────────────┬──────────────────────────────────────────────────┘
                   │ Always English from here down
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│              EXISTING PIPELINE (UNCHANGED INTERNALS)                │
│                                                                     │
│  inference.py ──► training_contract_messages() [English format]     │
│       │                                                             │
│       ▼                                                             │
│  LoRA adapter (English fine-tuned) → raw English output             │
│       │                                                             │
│       ├──► parse_inline_evaluation()  ← NEVER TRANSLATED            │
│       │         Level / Score / Strength / Improvement              │
│       │         (Bloom completion logic reads this)                 │
│       │                                                             │
│       └──► public_content (English question)                        │
│                   │                                                 │
└───────────────────┼─────────────────────────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────────────────────────┐
│              TRANSLATION BOUNDARY (NEW) — OUT                       │
│  public_content → translate_from_english() → localized question     │
│  final_feedback (strengths/improvements/summary) → translated       │
└─────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
              Browser displays in user's language
```

---

## What Gets Translated vs. What Stays English

| Field | Direction | Translate? | Reason |
|-------|-----------|-----------|--------|
| User's typed answer | → English | ✅ YES | Adapters trained on English |
| AI follow-up question (`public_content`) | → User lang | ✅ YES | User-visible |
| Opening message (session start) | → User lang | ✅ YES | User-visible |
| `completion_message()` text | → User lang | ✅ YES | User-visible |
| `teaching_feedback.strengths/improvements/summary` | → User lang | ✅ YES | User-visible |
| Survey questions & Likert labels | Static | ✅ pre-translated strings | UI text |
| `inline_evaluation` block | Internal | ❌ NEVER | Bloom parsing depends on it |
| `raw_content` field | Internal | ❌ NEVER | Internal storage |
| `TURN_EVALUATOR_PROMPT` | Internal | ❌ NEVER | Feeds OpenRouter/local judge |
| `FINAL_EVALUATOR_PROMPT` | Internal | ❌ NEVER | Feeds OpenRouter/local judge |
| DB storage of messages | Storage | Store English | Research analysis needs English |

---

## All Problems & How to Solve Them

### Problem 1: `training_contract_messages()` expects English prefixes
The function in `inference.py` hardcodes:
```python
content = f"Previous Question: {previous_question}\nTeacher's Answer: {content}"
```
The LoRA adapters were fine-tuned to recognise these exact English prefixes.

**Fix:** Translate user input to English **before** the history list is built in the WebSocket handler (line 728–735), not after.

---

### Problem 2: Bloom completion logic matches English strings
`completion.py` line 72:
```python
levels = ("remember", "understand", "apply", "analy", "evaluat", "create")
```
And `_score()` matches `"high"`, `"medium"`, `"low"`. If any translated text reaches `parse_inline_evaluation()`, the session never auto-completes early.

**Fix:** The `<evaluation>` block is already stripped from public output by `clean_output()`. Never translate it. Keep the full evaluation pipeline post-inference in English.

---

### Problem 3: WebSocket turn counter is atomic — translation must be synchronous
The turn counter is validated against the DB atomically. A translation call that raises or hangs mid-turn would leave the session in an inconsistent state.

**Fix:** Wrap translation in a `try/except` with a **passthrough fallback** — if Sarvam API fails, use the original text (English input still works, user gets English output). Log the failure. Never raise into the turn-counting logic.

---

### Problem 4: The opening message is generated before DB session is created
In `start_study()` (line 641–671), the opening message is generated and stored in the DB as `content=opening`. The user hasn't picked a language at this point (or they have, via the form).

**Fix:** Add a `language` field to the `/study/start` form. Store `session_lang` in session metadata. Translate the opening message before storing it (or store English and translate at display time — storing English is cleaner for research).

> **Design choice:** Store English in DB always; translate at display/send time. This keeps research data clean.

---

### Problem 5: Final feedback is generated asynchronously in background
`schedule_final_feedback()` (line 535–546) launches an `asyncio.Task`. The feedback fields (`strengths`, `improvements`, `summary`) are parsed and stored in the DB in English. They're only displayed when the user hits `/sessions/{id}/complete`.

**Fix:** Translate these fields **at display time** in the `complete()` route (line 861–875), not at generation time. Read `session_lang` from `session["metadata"]`.

---

### Problem 6: History reconstruction for inference uses stored content
In the WebSocket handler (line 728–734):
```python
history = [{"role": item["role"], "content": item["content"]} for item in transcripts.read(session_id)]
```
Since we store English in the DB, this history is already English — feeding it to the model works correctly. ✅ No problem here.

---

### Problem 7: Sarvam API latency adds to turn time
Each turn already takes inference time (1–10s). Sarvam translation adds ~200–500ms per API call. We need two calls per turn (input → EN, output → user lang).

**Fix:**
- Run both translation calls concurrently with `asyncio.gather` where possible.
- Cache translations for identical strings (opening messages, `completion_message()` which is templated).
- Set a short timeout (3–5s) on Sarvam calls; fall back to English on timeout.

---

### Problem 8: `visible_transcript_for_evaluator()` must stay English
Line 310–317 in `main.py` builds a transcript fed to OpenRouter's final evaluator. Since we store English in DB, `transcripts.read()` returns English — no change needed. ✅

---

### Problem 9: UI static text (buttons, labels, headings)
All Jinja2 templates have hardcoded English strings ("Start teaching", "Strengths", "Improvements", etc.).

**Fix (pragmatic):** Use a lightweight `gettext`-style dict approach. Add a `ui_strings` dict per language passed to all templates via the `render()` helper. No need for a full i18n framework.

---

## New File

### `app/services/translation.py` (~120 lines)

```python
"""Sarvam AI translation wrapper with fallback passthrough."""

import asyncio, logging, os, time
import httpx
from functools import lru_cache

logger = logging.getLogger("teach2learn.translation")

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_TIMEOUT = float(os.getenv("SARVAM_TIMEOUT_SECONDS", "5"))
SARVAM_TRANSLATE_URL = "https://api.sarvam.ai/translate"

SUPPORTED_LANGUAGES: dict[str, str] = {
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "bn": "Bengali",
    "ml": "Malayalam",
    "mr": "Marathi",
    "pa": "Punjabi",
    "en": "English",
}

# Language code → Sarvam language_code format
_SARVAM_CODES = {
    "hi": "hi-IN", "ta": "ta-IN", "te": "te-IN",
    "kn": "kn-IN", "bn": "bn-IN", "ml": "ml-IN",
    "mr": "mr-IN", "pa": "pa-IN", "en": "en-IN",
}


class TranslationService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=SARVAM_TIMEOUT)
        return self._client

    def is_enabled(self) -> bool:
        return bool(SARVAM_API_KEY)

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate text. Returns original text on any failure."""
        if not text.strip() or source_lang == target_lang or not self.is_enabled():
            return text
        try:
            client = self._get_client()
            response = await client.post(
                SARVAM_TRANSLATE_URL,
                headers={"api-subscription-key": SARVAM_API_KEY},
                json={
                    "input": text,
                    "source_language_code": _SARVAM_CODES.get(source_lang, source_lang),
                    "target_language_code": _SARVAM_CODES.get(target_lang, target_lang),
                    "speaker_gender": "Male",
                    "mode": "formal",
                    "model": "mayura:v1",
                    "enable_preprocessing": True,
                },
            )
            response.raise_for_status()
            return response.json().get("translated_text", text)
        except Exception as exc:
            logger.warning("translation_failed %s→%s error=%s", source_lang, target_lang, type(exc).__name__)
            return text  # graceful passthrough

    async def to_english(self, text: str, source_lang: str) -> str:
        return await self.translate(text, source_lang, "en")

    async def from_english(self, text: str, target_lang: str) -> str:
        return await self.translate(text, "en", target_lang)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


_translation_service: TranslationService | None = None

def get_translation_service() -> TranslationService:
    global _translation_service
    if _translation_service is None:
        _translation_service = TranslationService()
    return _translation_service
```

---

## File-by-File Changes

---

### 1. `.env.example` — Add 3 new variables

```diff
+ # --- Multilingual / Translation ---
+ SARVAM_API_KEY=                        # Get from sarvam.ai dashboard; leave empty to disable
+ SARVAM_TIMEOUT_SECONDS=5               # Per-request timeout; falls back to English on timeout
+ T2L_DEFAULT_LANGUAGE=en               # Default language for new sessions (en = English only)
```

---

### 2. `app/config.py` — Expose default language setting

**Add after line 39** (inside `from_env` classmethod):
```diff
+ default_language: str = "en"

  @classmethod
  def from_env(cls) -> "Settings":
      ...
+     return cls(
+         ...
+         default_language=os.getenv("T2L_DEFAULT_LANGUAGE", "en").strip()[:5],
      )
```

**Add field to dataclass** (after line 25):
```diff
  student_questionnaire_enabled: bool = False
+ default_language: str = "en"
```

---

### 3. `app/services/translation.py` — **NEW FILE**

Full content shown in "New File" section above (~120 lines).

---

### 4. `app/main.py` — Core changes (~50 lines added/changed)

#### 4a. Import translation service (after line 34)
```diff
  from app.services.transcripts import TranscriptStore
+ from app.services.translation import SUPPORTED_LANGUAGES, get_translation_service
```

#### 4b. Add helper to get session language (after `admin_for` function, ~line 237)
```diff
+ def session_lang(session: dict) -> str:
+     """Return the BCP-47 language code stored in session metadata."""
+     return str(session.get("metadata", {}).get("lang", "en"))
```

#### 4c. Shutdown translation client in lifespan (after line 139)
```diff
  await service.unload_all()
+ await get_translation_service().close()
  logger.info("portal_stopped")
```

#### 4d. Add `lang` field to `render()` context (line 240–255)
```diff
  def render(request: Request, template: str, **context):
      participant = participant_for(request)
      return templates.TemplateResponse(
          request=request,
          name=template,
          context={
              "participant": participant,
              "is_admin": is_admin(participant),
              "min_turns": MIN_TURNS,
              "max_turns": MAX_TURNS,
              "google_oauth_enabled": google_auth.enabled,
              "app_name": APP_NAME,
              "student_questionnaire_enabled": settings.student_questionnaire_enabled,
+             "supported_languages": SUPPORTED_LANGUAGES,
+             "default_language": settings.default_language,
              **context,
          },
      )
```

#### 4e. `start_study` — accept `lang` form field and translate opening message (lines 624–675)
```diff
  @app.post("/study/start")
  async def start_study(
      request: Request,
      model: str = Form(...),
      subject: str = Form(...),
      topic: str = Form(...),
      subtopic: str = Form(...),
+     lang: str = Form(default="en"),
  ):
      ...
+     lang = lang if lang in SUPPORTED_LANGUAGES else "en"
      ...
      # After opening message is generated (after line 647):
+     translator = get_translation_service()
+     opening_localized = await translator.from_english(opening, lang) if lang != "en" else opening
      session_id = database.create_session(
          participant["id"],
          subject,
          subtopic_name,
          {
              "model": model,
              "model_name": model_name,
              "topic": topic_name,
              "topic_id": topic,
              "turn": 0,
              "study_variant": "hci",
+             "lang": lang,                           # store chosen language
              "survey_instrument": INSTRUMENT_ID if settings.student_questionnaire_enabled else None,
          },
-         opening_message={"role": "assistant", "content": opening, "turn": 0},
+         opening_message={"role": "assistant", "content": opening, "turn": 0},  # store English
      )
+     # If localized differs from English, store it separately for display
+     # (Opening message in DB stays English for research integrity)
```

> **Note on opening message storage:** Store English in DB. The `chat.html` template receives `messages` from `transcripts.read()` (always English). We translate them at render time by passing `lang` to the template and doing JS-side or server-side translation. The simpler approach: **translate at send time** — see 4f.

#### 4f. WebSocket handler — two translation points (lines 716 and 811–848)

**Point 1 — Translate IN: user's answer → English** (after line 716):
```diff
  content = str(payload.get("message", "")).strip()[:2000]
+ user_lang = session_lang(session)
+ if user_lang != "en":
+     translator = get_translation_service()
+     content_en = await translator.to_english(content, user_lang)
+ else:
+     content_en = content
```

**Update history append** (line 735):
```diff
- history.append({"role": "user", "content": content})
+ history.append({"role": "user", "content": content_en})  # always English to model
```

**Update user message stored in DB** (line 838):
```diff
  transcripts.record_turn(
      session_id,
-     {"role": "user", "content": content, "turn": turn},
+     {"role": "user", "content": content_en, "turn": turn},  # English stored
```

**Point 2 — Translate OUT: English AI question → user lang** (between lines 810 and 846):
```diff
  public_content = completion_message(session["subtopic"]) if decision.reason == "knowledge_threshold" else generation.content
+ if user_lang != "en":
+     public_content_display = await translator.from_english(public_content, user_lang)
+ else:
+     public_content_display = public_content
```

**Update WebSocket send** (line 846–854):
```diff
  await websocket.send_json(
      {
-         "content": None if preview_sent else public_content,
+         "content": None if preview_sent else public_content_display,
          "turn": turn,
          "done": True,
          "complete": decision.complete,
          "completion_reason": decision.reason,
      }
  )
```

**Also update the early preview send** (lines 768–776):
```diff
  if preview_sent:
+     preview_content = await translator.from_english(generation.content, user_lang) if user_lang != "en" else generation.content
      await websocket.send_json(
          {
              "status": "evaluating",
-             "content": generation.content,
+             "content": preview_content,
              "turn": turn,
              "done": False,
          }
      )
```

#### 4g. `complete()` route — translate final feedback before display (lines 861–875)
```diff
  @app.get("/sessions/{session_id}/complete", response_class=HTMLResponse)
  async def complete(request: Request, session_id: str):
      session = owned_session(participant_for(request), session_id)
      ...
      result = await final_feedback_result(session)
+     lang = session_lang(session)
+     if lang != "en" and result and result.get("teaching_feedback"):
+         translator = get_translation_service()
+         fb = result["teaching_feedback"]
+         strengths, improvements, summary = await asyncio.gather(
+             asyncio.gather(*[translator.from_english(s, lang) for s in fb.get("strengths", [])]),
+             asyncio.gather(*[translator.from_english(s, lang) for s in fb.get("improvements", [])]),
+             translator.from_english(fb.get("summary", ""), lang),
+         )
+         result = {**result, "teaching_feedback": {**fb, "strengths": list(strengths), "improvements": list(improvements), "summary": summary}}
      return render(request, "complete.html", **complete_page_context(session, result))
```

#### 4h. `history_detail()` route — translate messages for display (line 927–939)
```diff
  @app.get("/history/{session_id}", response_class=HTMLResponse)
  async def history_detail(request: Request, session_id: str):
      ...
      messages = transcripts.read(session_id)
+     lang = session_lang(session)
+     # Pass lang to template; template can show "(translated from English)" note
      return render(
          request, "history_detail.html",
          session=session_view(session),
          messages=messages,
+         session_lang=lang,
          ...
      )
```

---

### 5. `app/templates/select.html` — Add language picker

**Add a new field after the model selector** (after line 41, before the summary div):
```diff
+     <div class="field">
+       <label for="lang"><span class="field-number">5</span> Teaching language</label>
+       <select id="lang" name="lang">
+         {% for code, name in supported_languages.items() %}
+         <option value="{{ code }}" {% if code == default_language %}selected{% endif %}>{{ name }}</option>
+         {% endfor %}
+       </select>
+       <p class="field-hint">The AI will ask questions in this language. You can teach in it too.</p>
+     </div>
```

---

### 6. `app/templates/chat.html` — Show language badge

Add a small badge near the session header so the user knows what language mode is active:
```diff
+ {% if session.lang and session.lang != "en" %}
+ <span class="lang-badge">🌐 {{ supported_languages.get(session.lang, session.lang) }}</span>
+ {% endif %}
```

Pass `session_lang` to this template via the `render()` call in `session_page()`:
```diff
  return render(request, "chat.html",
      session=view,
      messages=transcripts.read(session_id),
-     turn=view["turn"]
+     turn=view["turn"],
+     session_lang=view.get("lang", "en"),
  )
```

---

### 7. `app/templates/complete.html` — No structural changes

The template already renders `teaching_feedback.strengths`, `teaching_feedback.improvements`, and `teaching_feedback.summary` as plain strings — it will automatically show translated content once the route passes translated values. ✅

---

### 8. `pyproject.toml` — No new dependency

Sarvam is called over HTTP with `httpx`, which is already a dependency. ✅

---

### 9. `tests/test_app.py` — Add translation tests

```diff
+ # New test: translation disabled when SARVAM_API_KEY is empty
+ def test_translation_passthrough_when_disabled():
+     from app.services.translation import TranslationService
+     svc = TranslationService()
+     import asyncio
+     result = asyncio.run(svc.to_english("some text", "hi"))
+     assert result == "some text"  # passthrough when no API key

+ # New test: lang stored in session metadata
+ def test_session_lang_stored(client, ...):
+     # POST /study/start with lang=hi
+     # assert session metadata contains "lang": "hi"
```

---

## Data Flow Summary (One Turn)

```
1. User types "यह algorithm क्या करती है?" in browser
2. WebSocket receives payload
3. content = "यह algorithm क्या करती है?"
4. user_lang = "hi"
5. content_en = await translator.to_english(content, "hi")
   → "What does this algorithm do?"
6. history.append({"role": "user", "content": content_en})
7. LoRA adapter receives English history → generates English question
   → raw: "<evaluation>Level: Understand...</evaluation>\nCan you give me an example?"
8. parse_inline_evaluation() runs on raw output (English ✅)
9. clean_output() strips evaluation → public_content = "Can you give me an example?"
10. decide_completion() runs on English evaluation fields ✅
11. public_content_display = await translator.from_english("Can you give me an example?", "hi")
    → "क्या आप मुझे एक उदाहरण दे सकते हैं?"
12. DB stores: user="What does this algorithm do?", assistant="Can you give me an example?" (English)
13. Browser receives: "क्या आप मुझे एक उदाहरण दे सकते हैं?" → displayed in Hindi
```

---

## Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Sarvam API down | Medium | Low | Passthrough fallback → session continues in English |
| Translation latency >5s | Low | Medium | 5s timeout; parallel gather for multi-field |
| Technical CS terms mistranslated | Medium | Medium | `enable_preprocessing=True` in Sarvam; expected, acceptable degradation |
| User types Hinglish (code-mix) | High | Low | Sarvam handles code-mixing well; adapter still gets some English |
| Evaluation parsing breaks | Very Low | High | Evaluation block never translated; `clean_output()` already strips it |
| DB has mixed-language data | Low | High | Design rule: always store English; translate at display time only |

---

## Implementation Order

- [x] Phase 0: Read codebase
- [x] Phase 1: Create `app/services/translation.py` + update `.env.example`
- [x] Phase 2: Update `app/config.py` (add `default_language`)
- [x] Phase 3: Update `app/main.py` — imports, lifespan, `render()`, `start_study()`, `chat_socket()`, `complete()`
- [x] Phase 4: Update `app/templates/select.html` — language picker
- [x] Phase 5: Update `app/templates/chat.html` — language badge
- [x] Phase 6: Add tests (landed in a new `tests/test_translation.py` rather than `tests/test_app.py`)
- [x] Phase 7: Update `README.md`
- [x] Phase 8: Smoke test end-to-end in Hindi using the `echo` translation backend
- [x] Phase 8b: Repeated end-to-end in Hindi with live `SARVAM_API_KEY` and `OPENROUTER_API_KEY`.
      Real Devanagari in and out, English-only storage, zero `translation_failed` warnings.

## Deviations from this plan during implementation

1. **Stored transcripts are re-rendered at display time.** The plan translated only the live WebSocket payloads, which would have shown English on every chat reload and in session history. `localized_messages()` translates stored English content when the page is rendered.
2. **No `if lang != "en"` guards at call sites.** `TranslationService.translate()` already short-circuits when source equals target or no backend is configured, so callers invoke it unconditionally. This avoids the `UnboundLocalError` latent in plan section 4f.
3. **`SARVAM_MODEL` defaults to `sarvam-translate:v1`, not `mayura:v1`.** Mayura caps input at 1000 characters while the portal accepts 2000, so long explanations would have silently fallen through to untranslated text. Text above the model limit is split on sentence boundaries.
4. **The helper is `language_for(session)`,** not `session_lang()`, which collided with the template variable of the same name.
5. **Added `T2L_TRANSLATION_BACKEND=echo`** so the boundary can be verified locally without a Sarvam key.
6. **Added a local-only `/dev/login` route** and `.env.local` / `scripts/run-local.sh`, because there was otherwise no way to sign in without Google OAuth. The route is not registered when `APP_ENV=production`.
7. **API-key reads happen per call, not at module import,** so tests and `.env` reloads can toggle them.
8. **`docs/production-operations.md` was left unchanged** — it covers systemd and GPU startup, which this change does not affect.
