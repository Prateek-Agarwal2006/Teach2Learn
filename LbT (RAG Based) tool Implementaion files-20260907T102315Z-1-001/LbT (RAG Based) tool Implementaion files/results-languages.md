# Results

## Test bed

| | |
|---|---|
| Subjects | 4 — Computer Programming, Data Structures and Algorithms, OOP with Java, Operating Systems |
| Lessons | 24 |
| Repeats per lesson | 2 |
| Languages | 22 |
| Backend | openrouter |
| Decoding | temperature 0.25, top-p 0.9 |
| Judge | openai/gpt-5.6-luna |
| Lesson bank | /home/prateek/Documents/Teach2Learn/lessons.json v1 |
| Run at | 2026-09-11T17:56:14.891986+00:00 |
| Total runs | 80 |

## Question variety, by subject

Distinct questions as a fraction of questions asked, and how often a follow-up
reused an opening phrase. Higher variety is better; repeated openers are the
formulaic-learner failure the baseline check exists to catch.

| Subject | Model | Lessons | Runs | Distinct question ratio | Runs with repeated openers | Most repeated opening |
|---|---|---:|---:|---|---:|---|
| Computer Programming | openai/gpt-4o | 6 | 18 | 0.86 (0.50-1.00) | 14/18 | 8x “could you explain how associativity affects…” |
| Data Structures and Algorithms | openai/gpt-4o | 6 | 18 | 0.92 (0.50-1.00) | 16/18 | 27x “i think i got the main…” |
| OOP with Java | openai/gpt-4o | 6 | 18 | 0.90 (0.75-1.00) | 10/18 | 7x “could you explain how thread priorities…” |
| Operating Systems | openai/gpt-4o | 6 | 18 | 0.93 (0.75-1.00) | 13/18 | 9x “could you explain how the scheduler…” |

The distinct-question ratio counts whole strings, so it reads 1.00 even when every
follow-up opens with the same clause. The last column is what that ratio hides: how
often one opening phrase recurred, out of roughly four questions per run.

### Per lesson

| Lesson | Runs | Distinct question ratio | Bloom level reached | Adapter score |
|---|---:|---|---|---|
| `cp/c-basics/operators-and-expressions` | 3 | 0.75 (0.75-0.75) | - | - |
| `cp/c-basics/types-variables-constants` | 3 | 1.00 (1.00-1.00) | - | - |
| `cp/control-flow/conditions-and-switch` | 3 | 1.00 (1.00-1.00) | - | - |
| `cp/control-flow/loops-and-sentinel-values` | 3 | 0.75 (0.50-1.00) | - | - |
| `cp/pointers/addresses-and-pointers` | 3 | 0.75 (0.50-1.00) | - | - |
| `cp/pointers/dynamic-memory-allocation` | 3 | 0.92 (0.75-1.00) | - | - |
| `dsa/analysis/asymptotic-notation` | 3 | 0.92 (0.75-1.00) | - | - |
| `dsa/analysis/recurrences` | 3 | 0.83 (0.50-1.00) | - | - |
| `dsa/linear/queues-and-deques` | 3 | 1.00 (1.00-1.00) | - | - |
| `dsa/linear/stacks` | 3 | 0.92 (0.75-1.00) | - | - |
| `dsa/trees-heaps/heaps` | 3 | 1.00 (1.00-1.00) | - | - |
| `dsa/trees-heaps/tree-terminology-and-traversals` | 3 | 0.83 (0.75-1.00) | - | - |
| `oop_java/classes/access-control-and-object-identity` | 3 | 1.00 (1.00-1.00) | - | - |
| `oop_java/classes/constructors` | 3 | 0.83 (0.75-1.00) | - | - |
| `oop_java/concurrency/synchronization-and-locks` | 3 | 0.92 (0.75-1.00) | - | - |
| `oop_java/concurrency/threads` | 3 | 0.92 (0.75-1.00) | - | - |
| `oop_java/oop-design/inheritance` | 3 | 0.75 (0.75-0.75) | - | - |
| `oop_java/oop-design/polymorphism` | 3 | 1.00 (1.00-1.00) | - | - |
| `os/processes/interprocess-communication` | 3 | 1.00 (1.00-1.00) | - | - |
| `os/processes/process-lifecycle` | 3 | 0.83 (0.75-1.00) | - | - |
| `os/threads-scheduling/cpu-scheduling` | 3 | 0.92 (0.75-1.00) | - | - |
| `os/threads-scheduling/multithreading` | 3 | 1.00 (1.00-1.00) | - | - |
| `os/virtual-memory/demand-paging` | 3 | 0.83 (0.75-1.00) | - | - |
| `os/virtual-memory/page-replacement` | 3 | 1.00 (1.00-1.00) | - | - |

## Mechanical checks

No judgement involved. These are the figures to quote.

| | Count | Over |
|---|---:|---:|
| Untranslated participant text | 0 | 525 turns |
| Untranslated text shown back | 0 | 525 turns |
| Native script reaching the English zone | 0 | 525 turns |
| Crossings needing a retry | 0 | 1575 crossings |

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
| Punjabi † | `pa` | 4.3/5.0 | 4.8/5.0 | 4.7/4.8 | 4.3/5.0 | 4.6/5.0 | Ready |
| Malayalam | `ml` | 5.0/4.8 | 4.8/4.8 | 4.5/5.0 | 5.0/5.0 | 4.8/4.9 | Ready |
| Telugu | `te` | 4.2/4.8 | 4.0/4.7 | 4.7/4.8 | 4.5/5.0 | 4.3/4.8 | Ready |
| Urdu | `ur` | 4.8/5.0 | 4.7/4.8 | 4.7/4.8 | 4.5/4.7 | 4.7/4.8 | Ready |
| Hindi | `hi` | 5.0/5.0 | 4.3/4.7 | 4.7/4.5 | 4.5/5.0 | 4.6/4.8 | Ready |
| Gujarati | `gu` | 4.8/4.8 | 4.7/4.8 | 4.5/4.7 | 4.8/4.8 | 4.7/4.8 | Ready |
| Bengali | `bn` | 4.3/4.5 | 4.3/4.8 | 4.7/4.8 | 4.2/4.7 | 4.4/4.7 | Ready |
| Odia | `or` | 4.5/4.7 | 4.5/4.7 | 4.7/4.5 | 4.5/5.0 | 4.5/4.7 | Ready |
| Nepali | `ne` | 4.0/5.0 | 4.7/4.7 | 4.7/4.5 | 4.3/4.7 | 4.4/4.7 | Ready |
| Kannada | `kn` | 4.7/4.5 | 4.3/4.7 | 4.7/4.8 | 4.5/4.7 | 4.5/4.7 | Ready |
| Marathi | `mr` | 4.3/4.7 | 4.3/4.7 | 4.5/4.7 | 4.3/4.7 | 4.4/4.7 | Ready |
| Assamese | `as` | 4.7/4.5 | 4.7/4.5 | 4.5/4.8 | 4.3/4.7 | 4.5/4.6 | Ready |
| Tamil | `ta` | 4.0/5.0 | 4.5/4.7 | 4.7/4.5 | 4.3/4.2 | 4.4/4.6 | Ready |
| Maithili | `mai` | 4.7/4.5 | 4.7/4.5 | 4.8/4.2 | 4.2/4.3 | 4.6/4.4 | Ready |
| Dogri | `doi` | 4.2/4.2 | 4.7/4.5 | 4.5/4.2 | 4.3/4.2 | 4.4/4.2 | Ready |
| Bodo | `brx` | 4.8/4.0 | 4.8/4.0 | 4.3/3.8 | 5.0/4.0 | 4.8/4.0 | Review |
| Kashmiri | `ks` | 4.7/4.0 | 4.7/4.2 | 4.3/3.5 | 4.3/4.2 | 4.5/4.0 | Review |
| Konkani | `kok` | 4.3/3.7 | 4.8/3.8 | 4.7/3.8 | 4.5/4.0 | 4.6/3.8 | Review |
| Manipuri | `mni` | 5.0/4.0 | 4.5/3.7 | 5.0/3.7 | 5.0/3.8 | 4.9/3.8 | Review |
| Santali | `sat` | 4.8/3.3 | 4.8/3.6 | 4.8/3.3 | 5.0/4.0 | 4.9/3.6 | Review |
| Sanskrit | `sa` | 3.5/3.2 | 3.3/3.2 | 3.2/3.5 | 3.0/3.2 | 3.2/3.2 | Review |
| Sindhi | `sd` | 1.0/2.0 | 1.0/1.8 | 1.0/1.7 | 1.0/2.0 | 1.0/1.9 | **Blocked** |

† 1 language(s) have a lesson that never produced data: Punjabi. Their scores come from the lessons that did; see the failure list below. Failures recovered by a later re-run are not flagged.

## Judged quality, by language

Fidelity is whether the meaning survived; fluency is whether a native reader
would accept the sentence. Both are an independent model's opinion, 1-5, and
both are directional until a native reader confirms them.

| Language | Code | Cells | Fidelity | Fluency |
|---|---|---:|---|---|
| Punjabi  **FAILED** | `pa` | 21 | 4.6 (3.0-5.0) | 5.0 (4.0-5.0) |
| Malayalam | `ml` | 24 | 4.8 (2.0-5.0) | 4.9 (4.0-5.0) |
| Telugu | `te` | 24 | 4.3 (3.0-5.0) | 4.8 (4.0-5.0) |
| Urdu | `ur` | 24 | 4.7 (3.0-5.0) | 4.8 (4.0-5.0) |
| Hindi | `hi` | 24 | 4.6 (3.0-5.0) | 4.8 (4.0-5.0) |
| Gujarati | `gu` | 24 | 4.7 (2.0-5.0) | 4.8 (3.0-5.0) |
| Bengali | `bn` | 24 | 4.4 (3.0-5.0) | 4.7 (3.0-5.0) |
| Odia | `or` | 24 | 4.5 (3.0-5.0) | 4.7 (4.0-5.0) |
| Nepali | `ne` | 24 | 4.4 (3.0-5.0) | 4.7 (4.0-5.0) |
| Kannada | `kn` | 24 | 4.5 (3.0-5.0) | 4.7 (4.0-5.0) |
| Marathi | `mr` | 24 | 4.4 (2.0-5.0) | 4.7 (4.0-5.0) |
| Assamese | `as` | 24 | 4.5 (2.0-5.0) | 4.6 (4.0-5.0) |
| Tamil | `ta` | 24 | 4.4 (2.0-5.0) | 4.6 (3.0-5.0) |
| Maithili | `mai` | 24 | 4.6 (3.0-5.0) | 4.4 (4.0-5.0) |
| Dogri | `doi` | 24 | 4.4 (3.0-5.0) | 4.2 (4.0-5.0) |
| Bodo | `brx` | 24 | 4.8 (1.0-5.0) | 4.0 (3.0-5.0) |
| Kashmiri | `ks` | 24 | 4.5 (3.0-5.0) | 4.0 (3.0-5.0) |
| Konkani | `kok` | 24 | 4.6 (3.0-5.0) | 3.8 (3.0-5.0) |
| Manipuri | `mni` | 24 | 4.9 (4.0-5.0) | 3.8 (3.0-4.0) |
| Santali | `sat` | 24 | 4.9 (4.0-5.0) | 3.6 (3.0-4.0) |
| Sanskrit | `sa` | 24 | 3.2 (2.0-4.0) | 3.2 (2.0-4.0) |
| Sindhi | `sd` | 24 | 1.0 (1.0-1.0) | 1.9 (1.0-3.0) |

### Languages that failed to run

- **Punjabi** (`pa`): cp/pointers/dynamic-memory-allocation: seed for pa came back unchanged on 3 attempts

