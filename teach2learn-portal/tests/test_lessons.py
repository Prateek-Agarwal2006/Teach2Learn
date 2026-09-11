"""The shared lesson bank, and the guards that stop an unusable run being reported.

The bank is the experimental test bed: if a lesson names a topic the portal does not
offer, or a carried script drifts from the one that produced LANGUAGE_TEST_RESULTS.md,
the results stop meaning what the write-up says they mean. Both are cheap to check here
and expensive to notice afterwards.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.topics import normalize_subject, topic_selection


ROOT = Path(__file__).resolve().parents[2]
BANK_PATH = ROOT / "lessons.json"

# The four scripts that produced LANGUAGE_TEST_RESULTS.md, quoted here rather than
# imported so this test is an independent record of them. The expanded run is only
# comparable to that report on these cells if they stay byte-identical.
CARRIED = {
    "os/threads-scheduling/cpu-scheduling": (
        "The scheduler decides which ready process runs next on the CPU, because there are "
        "usually more runnable processes than cores.",
        "Round-robin gives each process a fixed time quantum in turn, so no single process "
        "can starve the others while it holds the CPU.",
        "A very small quantum wastes time on context switches, while a very large one makes "
        "the scheduler behave like plain first-come first-served.",
    ),
    "cp/pointers/dynamic-memory-allocation": (
        "malloc reserves a block of memory on the heap while the program is running and "
        "returns a pointer to its first byte, because the size is not known at compile time.",
        "Every successful malloc must be matched by exactly one free, otherwise the block "
        "stays reserved for the whole life of the program and the process leaks memory.",
        "Using a pointer after its block has been freed is undefined behaviour, so it is "
        "good practice to set the pointer to NULL immediately after freeing it.",
    ),
    "dsa/trees-heaps/heaps": (
        "A binary heap is a complete binary tree where every parent is ordered against its "
        "children, so the smallest element is always sitting at the root.",
        "Because the tree is complete, the heap can be stored in a plain array, where the "
        "children of index i live at 2i+1 and 2i+2 and no pointers are needed.",
        "Inserting or removing an element only walks one path between a leaf and the root, "
        "so both operations cost logarithmic time in the number of elements.",
    ),
    "oop_java/concurrency/synchronization-and-locks": (
        "When two threads update the same field at once one update can be lost, because "
        "reading, changing, and writing back is not a single indivisible step.",
        "A synchronized block lets only one thread hold the object's monitor at a time, so "
        "every other thread waits until that block finishes.",
        "Acquiring two locks in different orders in different threads can deadlock, so the "
        "usual rule is to always take locks in one fixed global order.",
    ),
}


@pytest.fixture(scope="module")
def lessons() -> list[dict]:
    return json.loads(BANK_PATH.read_text())["lessons"]


def test_every_lesson_names_a_topic_a_participant_could_pick(lessons):
    for lesson in lessons:
        subject = normalize_subject(lesson["subject"])
        # Raises on an unknown topic or subtopic, which is the point.
        topic_selection(subject, lesson["topic_id"], lesson["subtopic"])
        assert subject == lesson["subject"], f"{lesson['id']} uses a non-canonical subject slug"


def test_ids_are_unique(lessons):
    ids = [lesson["id"] for lesson in lessons]
    assert len(ids) == len(set(ids))


def test_every_script_is_exactly_three_sentences(lessons):
    # run_language walks script[index % len], so three entries under --turns 3 is one
    # clean pass. A script of a different length silently reintroduces cycling.
    for lesson in lessons:
        assert len(lesson["script"]) == 3, lesson["id"]
        assert all(line.strip() for line in lesson["script"]), lesson["id"]


def test_carried_scripts_are_byte_identical_to_the_reported_run(lessons):
    by_id = {lesson["id"]: lesson for lesson in lessons}
    for lesson_id, script in CARRIED.items():
        assert lesson_id in by_id, f"{lesson_id} was dropped from the bank"
        assert tuple(by_id[lesson_id]["script"]) == script, (
            f"{lesson_id} no longer matches LANGUAGE_TEST_RESULTS.md, so the expanded run "
            "can no longer be compared against that report on this cell"
        )
        assert by_id[lesson_id]["carried_from"] == "LANGUAGE_TEST_RESULTS.md"


def test_the_bed_is_balanced_across_subjects_and_topics(lessons):
    """Averages per subject are only meaningful if each subject carries the same weight."""
    per_subject: dict[str, list[str]] = {}
    for lesson in lessons:
        per_subject.setdefault(lesson["subject"], []).append(lesson["topic_id"])

    assert set(per_subject) == {"cp", "dsa", "oop_java", "os"}
    counts = {subject: len(topics) for subject, topics in per_subject.items()}
    assert len(set(counts.values())) == 1, f"unbalanced subjects: {counts}"
    for subject, topics in per_subject.items():
        assert len(set(topics)) >= 3, f"{subject} draws from fewer than three topics"
