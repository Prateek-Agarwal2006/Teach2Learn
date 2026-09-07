# Multilingual Expansion — EquitableT2L Portal

Participants can now teach in 22 Indic languages. The inference, evaluation, and
research pipeline still runs entirely in English.

---

## The Translation Boundary

Put a boundary around the existing English system, and cross it exactly twice per turn.

```
Participant                 |  ENGLISH ZONE  (unchanged)
types & reads Hindi         |
                            |  model inference
    typed answer  ──────────>  OpenRouter judge
                            |  Bloom completion
    question, feedback  <───|  SQLite + transcripts
                            |
              translation boundary
```

Everything to the right of the line was already built and was left untouched. Nothing
inside it knows the participant chose a language at all.

---

## What Crosses, and What Never Does

| Content | Translated? |
|---|---|
| Participant's typed answer | Yes — into English on the way in |
| Learner's follow-up question | Yes — into the participant's language |
| Opening message | Yes |
| Final feedback: summary, strengths, improvements | Yes |
| Private evaluation block | **Never** |
| Judge prompts | **Never** |
| Database and transcripts | **Never — always stored in English** |

The consequence worth stating plainly: **a Hindi session produces an English
transcript.** Admin views, exports, and analysis never had to learn about languages.

---

## How We Built It

Built in phases, each verified before moving on:

| Phase | Work |
|---|---|
| 1 | Translation service wrapping the Sarvam AI API |
| 2 | Wired the two crossing points into the session flow |
| 3 | Language picker on the topic form; language shown in the chat header |
| 4 | Tests |
| 5 | Documentation |
| 6 | Expanded from 8 languages to all 22 |

---

## Failing Safely

If the API is down, times out, or the key is missing, the original text passes through
and the session continues in English. A participant's run is never lost to an outage.

The trade-off is that failure is quiet rather than loud: a session that degrades to
English still looks like a working session. Everything else in this design follows from
taking that trade seriously.

---

## The Judge Sits Inside the English Zone

The judge never sees the participant's Hindi. It reads the translated-to-English answer
and returns English feedback, which is translated back out.

This means translation quality feeds evaluation quality — and since evaluation drives
session completion, a translation problem becomes a **session-length** problem. This is
the main thing we watch for during a study.

---

## Storing English Before Generating

The English answer is written to the transcript before the model responds.

That ordering is deliberate: a later translation failure can cost readability, but it
can never contaminate the research data.

---

## Expanding to 22 Languages

The original eight were a scope choice in the plan, not a limitation of the API.

Hindi · Tamil · Telugu · Kannada · Bengali · Malayalam · Marathi · Punjabi ·
**Gujarati · Odia · Urdu · Assamese · Bodo · Dogri · Konkani · Kashmiri · Maithili ·
Manipuri · Nepali · Sanskrit · Santali · Sindhi**

Because the picker, session metadata, and every display path read from the same
language map, the expansion changed **two dictionaries in one file** — no routes and no
templates.

---

## Why the Expansion Was Cheap

That a fourteen-language addition touched one file is not luck. It is what a boundary
drawn in the right place buys: the language is known at the edge and nowhere else, so
there was no per-language logic scattered through the system to find and update.

---

## Results

| | |
|---|---|
| Tests passing | **61 of 61** |
| Languages confirmed against the live API | **22 of 22** |
| Translation failures in the live Hindi session | **0** |

---

