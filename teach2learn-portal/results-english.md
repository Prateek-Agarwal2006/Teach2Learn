# Results

## Test bed

| | |
|---|---|
| Subjects | 4 — Computer Programming, Data Structures and Algorithms, OOP with Java, Operating Systems |
| Lessons | 24 |
| Repeats per lesson | 3 |
| Languages | English only |
| Backend | transformers |
| Decoding | temperature 0.2, top-p 0.9 |
| Judge | not used |
| Lesson bank | packed by pack_for_server.py v1 |
| Run at | 2026-09-08T10:04:00+00:00 |
| Total runs | 72 |

## Question variety, by subject

Distinct questions as a fraction of questions asked, and how often a follow-up
reused an opening phrase. Higher variety is better; repeated openers are the
formulaic-learner failure the baseline check exists to catch.

| Subject | Model | Lessons | Runs | Distinct question ratio | Runs with repeated openers | Most repeated opening |
|---|---|---:|---:|---|---:|---|
| Computer Programming | qwen3 | 6 | 18 | 1.00 (1.00-1.00) | 18/18 | 61x “that makes sense, but i'm still…” |
| Data Structures and Algorithms | gemma2 | 6 | 18 | 1.00 (1.00-1.00) | 10/18 | 14x “that makes sense, but i'm still…” |
| OOP with Java | mistral | 6 | 18 | 1.00 (1.00-1.00) | 5/18 | 9x “that makes sense, but i'm still…” |
| Operating Systems | granite | 6 | 18 | 1.00 (1.00-1.00) | 3/18 | 4x “i'm still really confused. i'm still…” |

The distinct-question ratio counts whole strings, so it reads 1.00 even when every
follow-up opens with the same clause. The last column is what that ratio hides: how
often one opening phrase recurred, out of roughly four questions per run.

### Per lesson

| Lesson | Runs | Distinct question ratio | Bloom level reached | Adapter score |
|---|---:|---|---|---|
| `cp/c-basics/operators-and-expressions` | 3 | 1.00 (1.00-1.00) | Understand (0.9 (0.0-1.0)) | 0.9 (0.0-1.0) of 2 |
| `cp/c-basics/types-variables-constants` | 3 | 1.00 (1.00-1.00) | Understand (1.0 (1.0-1.0)) | 1.0 (1.0-1.0) of 2 |
| `cp/control-flow/conditions-and-switch` | 3 | 1.00 (1.00-1.00) | Understand (0.8 (0.0-1.0)) | 0.7 (0.0-1.0) of 2 |
| `cp/control-flow/loops-and-sentinel-values` | 3 | 1.00 (1.00-1.00) | Understand (1.0 (1.0-1.0)) | 1.0 (1.0-1.0) of 2 |
| `cp/pointers/addresses-and-pointers` | 3 | 1.00 (1.00-1.00) | Understand (0.8 (0.0-1.0)) | 0.8 (0.0-1.0) of 2 |
| `cp/pointers/dynamic-memory-allocation` | 3 | 1.00 (1.00-1.00) | Understand (0.7 (0.0-1.0)) | 0.7 (0.0-1.0) of 2 |
| `dsa/analysis/asymptotic-notation` | 3 | 1.00 (1.00-1.00) | Understand (1.0 (1.0-1.0)) | 1.0 (1.0-1.0) of 2 |
| `dsa/analysis/recurrences` | 3 | 1.00 (1.00-1.00) | Understand (1.0 (0.0-2.0)) | 0.6 (0.0-1.0) of 2 |
| `dsa/linear/queues-and-deques` | 3 | 1.00 (1.00-1.00) | Remember (0.4 (0.0-1.0)) | 0.3 (0.0-1.0) of 2 |
| `dsa/linear/stacks` | 3 | 1.00 (1.00-1.00) | Understand (0.9 (0.0-2.0)) | 0.8 (0.0-1.0) of 2 |
| `dsa/trees-heaps/heaps` | 3 | 1.00 (1.00-1.00) | Understand (0.8 (0.0-1.0)) | 0.8 (0.0-1.0) of 2 |
| `dsa/trees-heaps/tree-terminology-and-traversals` | 3 | 1.00 (1.00-1.00) | Understand (0.9 (0.0-1.0)) | 0.9 (0.0-1.0) of 2 |
| `oop_java/classes/access-control-and-object-identity` | 3 | 1.00 (1.00-1.00) | Understand (1.0 (1.0-1.0)) | 1.0 (1.0-1.0) of 2 |
| `oop_java/classes/constructors` | 3 | 1.00 (1.00-1.00) | Understand (0.8 (0.0-1.0)) | 0.8 (0.0-1.0) of 2 |
| `oop_java/concurrency/synchronization-and-locks` | 3 | 1.00 (1.00-1.00) | Remember (0.3 (0.0-1.0)) | 0.3 (0.0-1.0) of 2 |
| `oop_java/concurrency/threads` | 3 | 1.00 (1.00-1.00) | Understand (0.8 (0.0-1.0)) | 0.8 (0.0-1.0) of 2 |
| `oop_java/oop-design/inheritance` | 3 | 1.00 (1.00-1.00) | Understand (0.6 (0.0-1.0)) | 0.6 (0.0-1.0) of 2 |
| `oop_java/oop-design/polymorphism` | 3 | 1.00 (1.00-1.00) | Understand (1.0 (1.0-1.0)) | 1.0 (1.0-1.0) of 2 |
| `os/processes/interprocess-communication` | 3 | 1.00 (1.00-1.00) | Understand (0.7 (0.0-1.0)) | 0.0 (0.0-0.0) of 2 |
| `os/processes/process-lifecycle` | 3 | 1.00 (1.00-1.00) | Understand (0.8 (0.0-2.0)) | 0.0 (0.0-0.0) of 2 |
| `os/threads-scheduling/cpu-scheduling` | 3 | 1.00 (1.00-1.00) | Understand (0.8 (0.0-2.0)) | 0.3 (0.0-1.0) of 2 |
| `os/threads-scheduling/multithreading` | 3 | 1.00 (1.00-1.00) | Understand (0.7 (0.0-1.0)) | 0.0 (0.0-0.0) of 2 |
| `os/virtual-memory/demand-paging` | 3 | 1.00 (1.00-1.00) | Understand (1.1 (0.0-2.0)) | 0.3 (0.0-1.0) of 2 |
| `os/virtual-memory/page-replacement` | 3 | 1.00 (1.00-1.00) | Remember (1.0 (0.0-2.0)) | 0.0 (0.0-0.0) of 2 |

