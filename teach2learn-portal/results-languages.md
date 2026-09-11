# Results

## Test bed

| | |
|---|---|
| Subjects | 4 — Computer Programming, Data Structures and Algorithms, OOP with Java, Operating Systems |
| Lessons | 8 |
| Repeats per lesson | 1 |
| Languages | 22 |
| Backend | transformers |
| Decoding | temperature 0.2, top-p 0.9 |
| Judge | openai/gpt-5.6-luna |
| Lesson bank | packed by pack_for_server.py v1 |
| Run at | 2026-09-08T11:55:31+00:00 |
| Total runs | 11 |

## Mechanical checks

No judgement involved. These are the figures to quote.

| | Count | Over |
|---|---:|---:|
| Untranslated participant text | 0 | 525 turns |
| Untranslated text shown back | 0 | 525 turns |
| Native script reaching the English zone | 0 | 525 turns |
| Crossings needing a retry | 4 | 1575 crossings |

## Language by subject

Each cell is fidelity/fluency, averaged over that language's judged turns for
that subject. Subject also selects the model, so a language weak in one column
and strong in the others is a problem with that pair; weak in every column is
upstream in the translation layer.

Status is a judgement about the language, so it is computed from scores alone:
**Blocked** if mean fidelity is under 2.0, **Review** if mean fidelity is under 3.5
or mean fluency under 4.0, else Ready. A dagger marks a language with a cell that
did not run; that is missing data needing a re-run, not a verdict about the
language, and the scores shown come from its remaining cells.

| Language | Code | cp | dsa | oop_java | os | Mean | Status |
|---|---|---|---|---|---|---|---|
| Punjabi † | `pa` | 5.0/5.0 | 4.7/4.8 | 4.7/4.8 | 4.5/4.8 | 4.7/4.9 | Ready |
| Bengali | `bn` | 4.2/5.0 | 4.3/4.8 | 4.8/4.8 | 4.2/4.7 | 4.4/4.8 | Ready |
| Telugu | `te` | 4.5/5.0 | 4.3/4.7 | 4.7/4.8 | 4.5/4.7 | 4.5/4.8 | Ready |
| Gujarati | `gu` | 4.8/5.0 | 4.7/4.8 | 4.5/4.5 | 4.8/4.8 | 4.7/4.8 | Ready |
| Tamil | `ta` | 4.2/4.8 | 4.8/4.8 | 4.7/4.5 | 4.3/4.5 | 4.5/4.7 | Ready |
| Kannada | `kn` | 4.7/5.0 | 4.3/4.5 | 4.7/4.5 | 4.3/4.5 | 4.5/4.6 | Ready |
| Malayalam | `ml` | 5.0/4.8 | 4.7/4.5 | 4.5/4.5 | 4.8/4.7 | 4.8/4.6 | Ready |
| Marathi | `mr` | 4.3/4.7 | 4.5/4.5 | 4.5/4.5 | 4.5/4.8 | 4.5/4.6 | Ready |
| Hindi | `hi` | 5.0/4.5 | 4.2/4.3 | 4.8/4.8 | 4.3/4.7 | 4.6/4.6 | Ready |
| Assamese | `as` | 4.5/4.8 | 3.8/4.5 | 4.3/4.5 | 4.2/4.5 | 4.2/4.6 | Ready |
| Nepali | `ne` | 3.8/4.8 | 4.7/4.5 | 4.7/4.3 | 4.5/4.7 | 4.4/4.6 | Ready |
| Odia | `or` | 4.8/4.8 | 4.7/4.3 | 4.8/4.3 | 4.7/4.7 | 4.8/4.5 | Ready |
| Urdu | `ur` | 5.0/4.7 | 4.5/4.3 | 4.7/4.5 | 4.5/4.3 | 4.7/4.5 | Ready |
| Maithili | `mai` | 4.7/4.7 | 4.7/4.7 | 4.7/4.0 | 4.5/4.3 | 4.6/4.4 | Ready |
| Dogri | `doi` | 4.2/4.5 | 4.8/3.7 | 4.5/4.3 | 4.0/4.2 | 4.4/4.2 | Ready |
| Bodo | `brx` | 4.8/4.0 | 5.0/3.7 | 4.2/3.7 | 5.0/4.0 | 4.8/3.8 | Review |
| Manipuri | `mni` | 5.0/4.3 | 4.5/3.8 | 4.8/3.2 | 4.8/3.8 | 4.8/3.8 | Review |
| Kashmiri | `ks` | 4.5/4.5 | 4.3/3.3 | 3.3/3.7 | 4.3/3.7 | 4.1/3.8 | Review |
| Konkani | `kok` | 4.5/3.7 | 4.8/3.7 | 4.7/3.7 | 4.3/3.7 | 4.6/3.7 | Review |
| Santali | `sat` | 4.5/3.8 | 4.7/3.2 | 4.8/3.2 | 5.0/3.7 | 4.8/3.5 | Review |
| Sanskrit | `sa` | 3.3/3.2 | 3.2/3.0 | 3.2/2.8 | 3.0/3.2 | 3.2/3.0 | Review |
| Sindhi | `sd` | 1.3/2.2 | 1.5/2.8 | 1.0/2.0 | 1.5/2.0 | 1.3/2.2 | **Blocked** |

† 1 language(s) have a lesson that never produced data: Punjabi. Their scores come from the lessons that did; see the failure list below. Failures recovered by a later re-run are not flagged.

## Judged quality, by language

Fidelity is whether the meaning survived; fluency is whether a native reader
would accept the sentence. Both are an independent model's opinion, 1-5, and
both are directional until a native reader confirms them.

| Language | Code | Cells | Fidelity | Fluency |
|---|---|---:|---|---|
| Punjabi  **FAILED** | `pa` | 21 | 4.7 (4.0-5.0) | 4.9 (4.0-5.0) |
| Bengali | `bn` | 24 | 4.4 (3.0-5.0) | 4.8 (4.0-5.0) |
| Telugu | `te` | 24 | 4.5 (3.0-5.0) | 4.8 (4.0-5.0) |
| Gujarati | `gu` | 24 | 4.7 (2.0-5.0) | 4.8 (4.0-5.0) |
| Tamil | `ta` | 24 | 4.5 (3.0-5.0) | 4.7 (4.0-5.0) |
| Kannada | `kn` | 24 | 4.5 (3.0-5.0) | 4.6 (4.0-5.0) |
| Malayalam | `ml` | 24 | 4.8 (2.0-5.0) | 4.6 (4.0-5.0) |
| Marathi | `mr` | 24 | 4.5 (2.0-5.0) | 4.6 (4.0-5.0) |
| Hindi | `hi` | 24 | 4.6 (3.0-5.0) | 4.6 (3.0-5.0) |
| Assamese | `as` | 24 | 4.2 (2.0-5.0) | 4.6 (4.0-5.0) |
| Nepali | `ne` | 24 | 4.4 (3.0-5.0) | 4.6 (3.0-5.0) |
| Odia | `or` | 24 | 4.8 (4.0-5.0) | 4.5 (3.0-5.0) |
| Urdu | `ur` | 24 | 4.7 (3.0-5.0) | 4.5 (4.0-5.0) |
| Maithili | `mai` | 24 | 4.6 (3.0-5.0) | 4.4 (4.0-5.0) |
| Dogri | `doi` | 24 | 4.4 (3.0-5.0) | 4.2 (3.0-5.0) |
| Bodo | `brx` | 24 | 4.8 (1.0-5.0) | 3.8 (3.0-5.0) |
| Manipuri | `mni` | 24 | 4.8 (4.0-5.0) | 3.8 (3.0-5.0) |
| Kashmiri | `ks` | 24 | 4.1 (1.0-5.0) | 3.8 (2.0-5.0) |
| Konkani | `kok` | 24 | 4.6 (3.0-5.0) | 3.7 (2.0-5.0) |
| Santali | `sat` | 24 | 4.8 (4.0-5.0) | 3.5 (2.0-4.0) |
| Sanskrit | `sa` | 24 | 3.2 (2.0-4.0) | 3.0 (2.0-4.0) |
| Sindhi | `sd` | 24 | 1.3 (1.0-4.0) | 2.2 (1.0-4.0) |

### Languages that failed to run

- **Punjabi** (`pa`): cp/pointers/dynamic-memory-allocation: TranslationUnavailable: seed for pa leaked a schema fragment

