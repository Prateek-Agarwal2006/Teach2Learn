# Experimental Test Bed

The setup for the expanded Teach2Learn evaluation. This describes what will be run and
under what conditions; it contains no results. Written before the run so the design is
fixed in advance rather than described afterwards from whatever happened.

**Status: 24 lessons written, none reviewed, nothing run.**

## Why it changed

The results in `LANGUAGE_TEST_RESULTS.md` came from **one lesson per subject**, run once.
Every per-subject figure there is three turns of a single hand-written script, so a
subject average and a single lesson's score are the same number, and there is no way to
tell a real difference from run-to-run variation.

Two changes fix that: six lessons per subject drawn from three different topics, and
each lesson run several times so every figure carries a spread.

## The grid

| | |
|---|---|
| Subjects | 4 |
| Topics per subject | 3 |
| Subtopics per topic | 2 |
| **Lessons** | **24** |
| Teacher turns per lesson | 3 |
| Repeats per lesson | 3 (planned) |
| Source of run-to-run variation | sampled decoding; identical input, different output |
| Languages | 22 Indic + English |

Subjects and topics are drawn from `teach2learn-portal/app/topics.py`, the same catalogue
a participant picks from, so no lesson names a topic the portal does not offer. Every
entry is validated against it when the bank loads.

Subject is not only a change of wording: each subject routes to a different fine-tuned
model, so varying subject also varies the model.

| Subject | Base model | Adapter |
|---|---|---|
| Computer Programming | Qwen3 8B | `CP_dataset` |
| Data Structures and Algorithms | Gemma 2 9B | `DSA_dataset` |
| OOP with Java | Mistral 7B | `oops_dataset` |
| Operating Systems | Granite 3.3 8B | `OS_dataset` |

That coupling is worth stating plainly in the write-up: a difference between two subjects
is a difference between two models as well, and the design cannot separate them.

## The 24 lessons

Each is a fixed three-sentence explanation, the kind of thing a participant teaching that
subtopic would say. The same three sentences are used for every language and every repeat,
so differences are attributable to the language or the system rather than to what the
teacher happened to say.

`*` marks the four scripts carried over byte-for-byte from the run that produced
`LANGUAGE_TEST_RESULTS.md`, so the new results can be compared against that report on
those cells instead of replacing it. A test enforces that they stay identical.

| Subject | Topic | Subtopic |
|---|---|---|
| Computer Programming | C fundamentals | Types, variables, and constants |
| Computer Programming | C fundamentals | Operators and expressions |
| Computer Programming | Control flow | Conditions and switch statements |
| Computer Programming | Control flow | Loops and sentinel values |
| Computer Programming | Pointers and memory | Addresses and pointers |
| Computer Programming | Pointers and memory | Dynamic memory allocation * |
| Data Structures and Algorithms | Algorithm analysis | Asymptotic notation |
| Data Structures and Algorithms | Algorithm analysis | Recurrences |
| Data Structures and Algorithms | Linear data structures | Stacks |
| Data Structures and Algorithms | Linear data structures | Queues and deques |
| Data Structures and Algorithms | Trees and priority queues | Tree terminology and traversals |
| Data Structures and Algorithms | Trees and priority queues | Heaps * |
| OOP with Java | Classes and objects | Constructors |
| OOP with Java | Classes and objects | Access control and object identity |
| OOP with Java | Object-oriented design | Inheritance |
| OOP with Java | Object-oriented design | Polymorphism |
| OOP with Java | Concurrency | Threads |
| OOP with Java | Concurrency | Synchronization and locks * |
| Operating Systems | Processes and communication | Process lifecycle |
| Operating Systems | Processes and communication | Interprocess communication |
| Operating Systems | Threads and scheduling | Multithreading |
| Operating Systems | Threads and scheduling | CPU scheduling * |
| Operating Systems | Virtual memory | Demand paging |
| Operating Systems | Virtual memory | Page replacement |

## Fixed conditions

| | |
|---|---|
| Teacher scripts | `lessons.json` at the repo root, version 1 |
| Translation | Sarvam AI, `sarvam-translate:v1` |
| Judge | independent model over OpenRouter, fixed fidelity and fluency prompts |
| Inference | the deployed backend on the GPU host; never the local `fake` backend |
| Decoding | temperature 0.25, top-p 0.9, sampling on, no fixed seed |
| Recorded per run | backend, bank version and lesson ids, model override, turns, repeats, languages, judge model, adapter root, visible GPUs, UTC timestamps, elapsed seconds |

The bank sits at the repo root rather than inside the portal so the RAG implementation's
harness can read the same file rather than copying it: byte-identical teacher input is
the only reason a later comparison between the two systems would mean anything. That
harness still carries its own single hardcoded lesson and has to be pointed here first,
which is work on the RAG side and not part of this phase.

## What is measured

Two kinds of number, and they do not carry equal weight.

**Mechanical**, no judgement involved: whether text crossed the boundary untranslated,
whether native script reached the English side, how many retries a crossing cost, and
whether the learner's questions repeat each other. These are the figures to quote.

**Judged**, by an independent model: fidelity (did the meaning survive the translation)
and fluency (would a native reader accept the sentence), each 1-5. Sarvam both produces
the translations and is measured on them, so a language rendered consistently wrong in
both directions can still round-trip cleanly; the independent judge exists to break that
loop and mostly does. Treat these as directional until a native reader confirms them.

## Two ways a run can look complete and mean nothing

Both are now refused rather than documented.

- **`INFERENCE_BACKEND=fake`** returns a canned string instead of calling a model, and it
  is the default in `.env.example`. Every question, evaluation, and fluency score would
  describe that string, in a results file shaped exactly like a real one. The harness
  stops unless `--allow-fake` is passed, and stamps `results_are_fake` when it is.
- **Unreviewed lessons.** A script no one has read can be wrong about the subject, and
  the learner's reply to a wrong explanation is not a measurement of anything. The
  harness stops unless `--allow-unreviewed` is passed, and stamps the output.

## Running it

    # what is in the bank, and what still needs review
    python scripts/check_languages.py --list-lessons

    # one subject, English only, three repeats
    python scripts/check_languages.py --baseline --subject os --repeat 3 --out baseline-os.json

    # on the GPU host: the bank travels inside the piped program, since nothing
    # of ours exists on that filesystem
    python3 scripts/pack_for_server.py --with-key | ssh HOST \
      'cd ~/scratch/teach2learn-portal && set -a && . ./.env && set +a && \
       $APP_PYTHON - --sweep --subject os --repeat 3' > results-os.json

## Next

1. A reader who knows the material accepts or rejects each of the 24 scripts and sets
   `"reviewed": true`. Nothing else can proceed first.
2. A pilot on one subject, on the server, which is what tells us the time and cost of the
   full run before committing to it.
3. The full run.
