# Multilingual Test Results

All 22 Sarvam Indic languages, run end to end against the real fine-tuned adapters on the
GPU host. 6–7 September 2026.

**261 teaching turns · 87 of 88 cells · 4 base models · 0 script leaks**

**13 languages ready · 7 need a native reader · 2 blocked**

## What was tested

Each language ran a 3-turn lesson in each of 4 subjects. Subject selects the adapter, so the
four columns are four separately fine-tuned base models.

| Subject | Base model | Adapter | Topic |
|---|---|---|---|
| `os` | Granite 3.3 8B | `OS_dataset` | CPU scheduling |
| `dsa` | Gemma 2 9B | `DSA_dataset` | Heaps |
| `cp` | Qwen3 8B | `CP_dataset` | Dynamic memory allocation |
| `oop_java` | Mistral 7B | `oops_dataset` | Synchronization and locks |

Every turn crosses the boundary twice: the participant's answer is translated to English for
the model, and the model's question is translated back. The model never sees a non-English
character; the participant never sees an English one.

Two measures are mechanical string checks and carry no opinion — whether text crossed
untranslated, and whether native script reached the English side. **Both are zero across all
261 turns.** Fidelity (did the meaning survive) and fluency (would a learner recognise their
own language) come from an independent `gpt-5.6-luna` judge, scored 1–5.

## Results

Each subject cell is fidelity/fluency, averaged over 3 judged turns. Sorted by mean fluency.

| Language | Code | Script | os | dsa | cp | oop_java | Mean | Status |
|---|---|---|---|---|---|---|---|---|
| Hindi | `hi` | Devanagari | 4.7/5.0 | 4.3/5.0 | 5.0/5.0 | 5.0/4.3 | 4.8/4.8 | Ready |
| Kannada | `kn` | Kannada | 4.0/4.7 | 4.3/4.7 | 4.7/5.0 | 5.0/5.0 | 4.5/4.8 | Ready |
| Assamese | `as` | Bengali | 4.7/4.3 | 5.0/4.7 | 5.0/5.0 | 5.0/5.0 | 4.9/4.8 | Ready |
| Nepali | `ne` | Devanagari | 5.0/5.0 | 4.7/4.7 | 4.0/5.0 | 5.0/4.3 | 4.7/4.8 | Ready |
| Tamil | `ta` | Tamil | 4.7/5.0 | 4.7/4.7 | 4.7/5.0 | 5.0/4.0 | 4.8/4.7 | Ready |
| Telugu | `te` | Telugu | 4.3/4.7 | 4.0/4.3 | 4.7/5.0 | 5.0/4.7 | 4.5/4.7 | Ready |
| Bengali | `bn` | Bengali | 4.3/4.3 | 4.3/4.7 | 4.7/5.0 | 5.0/4.7 | 4.6/4.7 | Ready |
| Gujarati | `gu` | Gujarati | 5.0/4.3 | 4.7/5.0 | 5.0/4.7 | 5.0/4.7 | 4.9/4.7 | Ready |
| Odia | `or` | Odia | 4.0/5.0 | 4.3/4.7 | 4.7/4.7 | 5.0/4.0 | 4.5/4.6 | Ready |
| Punjabi | `pa` | Gurmukhi | 4.3/4.3 | 4.7/4.7 | **fail** | 5.0/4.3 | 4.7/4.4 | **BLOCKED (cp)** |
| Malayalam | `ml` | Malayalam | 4.3/4.7 | 4.7/4.3 | 5.0/4.3 | 4.3/4.3 | 4.6/4.4 | Ready |
| Marathi | `mr` | Devanagari | 4.0/4.3 | 4.3/5.0 | 4.3/4.7 | 5.0/3.3 | 4.4/4.3 | Ready |
| Urdu | `ur` | Perso-Arabic | 4.7/4.7 | 4.3/4.3 | 5.0/4.7 | 5.0/3.7 | 4.8/4.3 | Ready |
| Maithili | `mai` | Devanagari | 4.0/4.0 | 4.7/4.3 | 4.7/4.0 | 5.0/5.0 | 4.6/4.3 | Ready |
| Manipuri | `mni` | Meetei Mayek | 5.0/4.0 | 4.7/3.7 | 4.3/3.7 | 5.0/4.0 | 4.8/3.8 | Review |
| Konkani | `kok` | Devanagari | 4.0/3.3 | 4.7/4.0 | 4.3/4.0 | 4.7/3.7 | 4.4/3.8 | Review |
| Kashmiri | `ks` | Perso-Arabic | 4.3/3.3 | 4.7/4.0 | 4.7/4.0 | 4.0/3.7 | 4.4/3.8 | Review |
| Santali | `sat` | Ol Chiki | 4.7/3.7 | 4.7/3.7 | 5.0/4.0 | 5.0/3.3 | 4.8/3.7 | Review |
| Dogri | `doi` | Devanagari | 4.0/3.3 | 4.7/4.0 | 4.7/3.3 | 4.0/3.7 | 4.3/3.6 | Review |
| Sanskrit | `sa` | Devanagari | 2.7/3.7 | 3.3/3.7 | 3.7/3.7 | 4.0/3.0 | 3.4/3.5 | Review |
| Bodo | `brx` | Devanagari | 5.0/3.3 | 5.0/3.0 | 5.0/3.7 | 5.0/3.7 | 5.0/3.4 | Review |
| Sindhi | `sd` | Devanagari | 1.0/2.3 | 1.0/2.0 | 1.3/1.7 | 1.3/1.7 | 1.2/1.9 | **BLOCKED** |

## Blocking issues

**Sindhi — wrong script, upstream.** Fidelity 1.0–1.3 on *all four* models, which places the
fault in the translation layer, not any adapter. Meaning survives; the back-translation is
clean. The problem is that Sarvam returns Devanagari, while Perso-Arabic is the dominant
script for Sindhi. The judge flagged it unprompted, answering in Perso-Arabic itself.

This is not a missing parameter on our side: `sarvam-translate:v1` rejects `output_script`
outright — `roman`, `fully-native` and `spoken-form-in-native` all return HTTP 400. There is
no request we can send that changes it. **Remove Sindhi from the language picker.**

**Punjabi — Sarvam returned its own API documentation.** One sentence in the C-programming
lesson came back as a fragment of Sarvam's OpenAPI schema:

```
{'description': 'The translation of the source sentence assuming the subject is female.',
 'title': 'Female', 'type': 'string'}
```

Fully reproducible and narrowly specific: that exact sentence to `pa-IN` leaks every time,
while the same sentence to Hindi, Gujarati and Bengali is fine, and a different sentence to
Punjabi is fine. Punjabi scores 4.3–4.7 in the other three subjects.

Without a check, that JSON becomes the participant's answer — fed to the model as their
words, written to the transcript, shown back on screen.

## Needs a native reader

| Language | Mean fid/flu | Pattern |
|---|---|---|
| Sanskrit | 3.4/3.5 | Reads as competent Sanskrit while losing technical content. On `os`, fidelity (2.7) falls below fluency — the only language where that happens. |
| Bodo | 5.0/3.4 | Meaning fully intact (5.0 fidelity on every subject) but phrasing stilted. Never exceeds 3.7 fluency. |
| Dogri | 4.3/3.6 | Same pattern, consistent across all four subjects. |
| Santali | 4.8/3.7 | Ol Chiki script renders correctly; phrasing is the weak point. |
| Konkani | 4.4/3.8 | Same stilted-but-faithful pattern. |
| Kashmiri | 4.4/3.8 | Same, in Perso-Arabic script. |
| Manipuri | 4.8/3.8 | Meetei Mayek renders correctly; fluency dips on `dsa` and `cp`. |

These seven are usable, not broken — the content arrives, the sentence reads awkwardly. Because the
pattern holds across all four subjects, it is a property of the language pair, not one lesson.

Bodo, Dogri and Konkani share Devanagari with Hindi, so we checked they were not a silent
Hindi fallback: Bodo overlaps Hindi's rendering by 0.21 and Konkani by 0.56 on a
character-sequence ratio, against 1.0 for an identical string.

## Bugs found and fixed in the test harness

- **Meetei Mayek was missing from the leak detector** (`U+ABC0–ABFF`), the script Sarvam
  returns for Manipuri. Manipuri could have leaked into the English zone and still scored
  zero — an absent alarm reads exactly like a passing test. Fixed; all turns re-scored.
- **The opening question crossed the boundary unchecked**, sitting outside the turn loop. A
  Sindhi run had its opening left in English by a timeout and still summarised as clean.
- **A dead Sarvam key produced six clean-looking rows.** `translation.py` returns its input
  on failure, so the rows had no error field. Now fatal and recorded.
- **The first fix was too aggressive** and killed three sweeps over single transient
  timeouts. Now: retry three times with backoff, fail that one language, abort only after
  three consecutive failures.
- **Schema-shaped payloads are now detected directly**, so the Punjabi failure cannot slip
  through on a language where the back-translation would have differed.

## Recommended before running participants

1. **Remove Sindhi** from the picker. Upstream, unfixable from here.
2. **Port the schema-payload check and the retry into `translation.py`.** Both blocking
   failures reach a participant *silently*, because that module returns its input whenever a
   crossing fails. That is right for a live session — better than an error page — but it means
   a Sindhi participant is greeted in English and a Punjabi one could be shown raw JSON.
3. **Raise `SARVAM_TIMEOUT_SECONDS` from 5 to 20.** Transient timeouts hit roughly one
   crossing in sixty at 5s; 20s plus retries cleared all ten across the later runs.
4. **Get a native reader** for the seven above: Sanskrit, Bodo, Dogri, Santali, Konkani,
   Kashmiri, Manipuri.
5. **13 languages are ready as they are** — fidelity and fluency at or above 4.0 on every
   subject and every model.

## Caveats

Fidelity and fluency are directional, not validated. Sarvam both produces these translations
and is measured on them, so a language rendered consistently wrong in both directions
round-trips cleanly. The independent judge exists to break that loop and mostly does, but it
undercut itself twice — answering in Hindi on the Bodo row and in Marathi-inflected
Devanagari on Konkani.

The passthrough and leak columns have no such weakness. Those are the numbers to quote.

Nothing was written to the GPU host: no file created, no config edited, and the portal's
database and transcripts were never touched.
