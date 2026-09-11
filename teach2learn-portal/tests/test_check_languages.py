"""Guards in the language harness that decide whether a crossing counts as failed.

The harness is a script rather than a module, so it is loaded by path here. Only the
pure helpers are exercised; nothing in this file calls a model, Sarvam, or the judge.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "check_languages", ROOT / "scripts" / "check_languages.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because @dataclass resolves annotations through
    # sys.modules[cls.__module__], which is absent for a module loaded by path.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


# The payload Sarvam actually returned for one Punjabi sentence, quoted from
# LANGUAGE_TEST_RESULTS.md. Handed on unchecked it becomes the participant's answer.
REAL_LEAK = (
    "{'description': 'The translation of the source sentence assuming the subject is "
    "female.', 'title': 'Female', 'type': 'string'}"
)


@pytest.mark.parametrize(
    "text",
    [
        REAL_LEAK,
        '[{"type": "string"}]',
        'the model said "title": something',
        "{'properties': {}}",
    ],
)
def test_schema_payloads_are_caught(text):
    assert harness._looks_like_schema(text)


@pytest.mark.parametrize(
    "text",
    [
        # The echo translation backend prefixes the language code. A detector that
        # fired on any leading bracket failed every language in a local dry run
        # before a single sentence had been translated.
        "[hi] Round-robin gives each process a fixed time quantum in turn.",
        "[1] The scheduler decides which ready process runs next.",
        "A very small quantum wastes time on context switches.",
        "",
    ],
)
def test_ordinary_text_is_not_mistaken_for_a_schema(text):
    assert not harness._looks_like_schema(text)


def test_meetei_mayek_counts_as_non_latin():
    # Manipuri's script was missing from the range, so a leak scored as clean --
    # an absent alarm reads exactly like a passing test.
    assert harness._has_non_latin("ꯃꯤꯇꯩ ꯃꯌꯦꯛ")
    assert not harness._has_non_latin("plain english text")


def test_a_missing_bank_refuses_rather_than_falling_back(tmp_path):
    """No built-in fallback: falling back would emit a partial run that looks complete."""
    with pytest.raises(SystemExit) as excinfo:
        harness.load_lessons(str(tmp_path / "absent.json"))
    assert "no lesson bank found" in str(excinfo.value)


def test_lessons_resolve_and_carry_their_review_state(tmp_path):
    bank_path = tmp_path / "lessons.json"
    bank_path.write_text(
        json.dumps(
            {
                "version": 9,
                "lessons": [
                    {
                        "id": "os/threads-scheduling/cpu-scheduling",
                        "subject": "os",
                        "topic_id": "threads-scheduling",
                        "subtopic": "CPU scheduling",
                        "reviewed": True,
                        "carried_from": "LANGUAGE_TEST_RESULTS.md",
                        "script": ["one.", "two.", "three."],
                    },
                    {
                        "id": "dsa/trees-heaps/heaps",
                        "subject": "dsa",
                        "topic_id": "trees-heaps",
                        "subtopic": "Heaps",
                        "reviewed": False,
                        "script": ["one.", "two.", "three."],
                    },
                ],
            }
        )
    )
    bank = harness.load_lessons(str(bank_path))

    every = harness.resolve_lessons(bank, None, None)
    assert [lesson.lesson_id for lesson in every] == [
        "os/threads-scheduling/cpu-scheduling",
        "dsa/trees-heaps/heaps",
    ]
    assert every[0].reviewed is True and every[0].carried_from == "LANGUAGE_TEST_RESULTS.md"
    assert every[1].reviewed is False and every[1].carried_from is None
    # Resolved against the real catalogue, not echoed back from the file.
    assert every[0].topic == "Threads and scheduling"

    only_dsa = harness.resolve_lessons(bank, "dsa", None)
    assert [lesson.lesson_id for lesson in only_dsa] == ["dsa/trees-heaps/heaps"]

    with pytest.raises(SystemExit):
        harness.resolve_lessons(bank, None, "os/no/such-lesson")


def test_an_unknown_topic_in_the_bank_fails_before_any_generation(tmp_path):
    bank_path = tmp_path / "lessons.json"
    bank_path.write_text(
        json.dumps(
            {
                "version": 9,
                "lessons": [
                    {
                        "id": "os/invented/nonsense",
                        "subject": "os",
                        "topic_id": "invented",
                        "subtopic": "Nonsense",
                        "reviewed": True,
                        "script": ["one.", "two.", "three."],
                    }
                ],
            }
        )
    )
    bank = harness.load_lessons(str(bank_path))
    with pytest.raises(ValueError, match="Unknown topic"):
        harness.resolve_lessons(bank, None, None)
