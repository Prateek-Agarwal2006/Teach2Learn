import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.inference import (
    FakeBackend,
    InferenceConfig,
    InferenceService,
    ModelProfile,
    VLLMHTTPBackend,
    clean_output,
    normalize_chat_messages,
    parse_inline_evaluation,
    should_stop_after_question,
    training_contract_messages,
)
from app.topics import normalize_subject, topics_for


def test_fake_generation_is_deterministic_and_injects_topic():
    service = InferenceService(InferenceConfig(backend="fake"))
    result = asyncio.run(service.generate("DSA", "Graph traversal", "How does BFS work?"))
    assert result == "I think I follow your explanation of Graph traversal. Could you give me a concrete example and explain why it works?"


def test_subject_aliases_and_topics():
    assert normalize_subject("OOP and Java") == "oop_java"
    assert "Virtual memory" in topics_for("Operating Systems")


def test_output_cleanup():
    assert clean_output("<|assistant|> Assistant:  hello <|im_end|>") == "hello"
    assert clean_output("A useful question?\nuser\nTeacher's Answer: leaked training text") == "A useful question?"
    assert (
        clean_output(
            "Level: Apply\nScore: High\nStrength: Clear example.\nImprovement: Explain the tradeoff.\nWhy does the lock work?"
        )
        == "Why does the lock work?"
    )
    assert clean_output("<evaluation>\nLevel: Apply\nScore: High") == ""


def test_missing_public_question_gets_safe_fallback():
    class EvaluationOnlyBackend(FakeBackend):
        def generate(self, loaded, profile, messages, config):
            return (
                "<evaluation>\nLevel: Apply\nScore: High\nStrength: Clear.\n"
                "Improvement: Add an example.\n</evaluation>"
            )

    result = asyncio.run(
        InferenceService(InferenceConfig(backend="fake"), EvaluationOnlyBackend()).generate_detailed(
            "cp", "Pointers", "A pointer stores an address."
        )
    )
    assert result.content == "Could you give me one concrete example that shows how this works?"
    assert result.fallback_used is True
    assert result.evaluation and result.evaluation["score"] == "High"


def test_generation_stops_after_one_complete_question():
    assert should_stop_after_question("What does it do?")
    assert not should_stop_after_question("<evaluation>\nImprovement: Explain why?")
    assert should_stop_after_question("<evaluation>\nImprovement: Explain why?\n</evaluation>\nCan you show an example?")


def test_leading_assistant_history_is_normalized_for_strict_templates():
    messages = [
        {"role": "system", "content": "Act as a student."},
        {"role": "assistant", "content": "What is a semaphore?"},
        {"role": "user", "content": "It coordinates access."},
    ]
    assert [item["role"] for item in normalize_chat_messages(messages)] == ["system", "user", "assistant", "user"]


def test_training_contract_and_private_evaluation_parsing():
    history = training_contract_messages([
        {"role": "assistant", "content": "What is a mutex?"},
        {"role": "user", "content": "It protects a critical section."},
        {"role": "assistant", "content": "Can you give an example?"},
        {"role": "user", "content": "A lock can protect a shared counter."},
    ])
    assert history[1]["content"] == "Teacher's Answer: It protects a critical section."
    assert history[3]["content"].startswith("Previous Question: Can you give an example?\nTeacher's Answer:")
    parsed = parse_inline_evaluation("<evaluation>\nLevel: Apply\nScore: High\nFeedback: Clear.\n</evaluation>\nQuestion?")
    assert parsed == {"raw": "Level: Apply\nScore: High\nFeedback: Clear.", "level": "Apply", "score": "High", "feedback": "Clear."}
    structured = parse_inline_evaluation(
        "<evaluation>\nLevel: Analyze\nScore: Medium\nStrength: Clear comparison.\nImprovement: Add an example.\n</evaluation>\nQuestion?"
    )
    assert structured["strength"] == "Clear comparison."
    assert structured["improvement"] == "Add an example."
    untagged = parse_inline_evaluation(
        "Level: Apply\nScore: High\nStrength: Clear example.\nImprovement: Explain the tradeoff.\nWhy?"
    )
    assert untagged and untagged["score"] == "High"


class RecordingBackend(FakeBackend):
    def __init__(self):
        self.loads = []
        self.unloads = []

    def load(self, profile):
        self.loads.append(profile.base_model)
        return profile

    def unload(self, loaded):
        self.unloads.append(loaded.base_model)


def test_lru_unloads_when_subject_profile_changes():
    backend = RecordingBackend()
    config = InferenceConfig(
        backend="fake",
        profiles={"a": ModelProfile("a"), "b": ModelProfile("b")},
        subject_models={"cp": "a", "dsa": "b"},
        max_loaded_models=1,
    )
    service = InferenceService(config, backend)
    asyncio.run(service.generate("cp", "Pointers", "Explain them"))
    asyncio.run(service.generate("dsa", "Trees", "Explain them"))
    assert backend.loads == ["a", "b"]
    assert backend.unloads == ["a"]


def test_invalid_subject_fails_before_loading():
    with pytest.raises(ValueError, match="Unknown subject"):
        asyncio.run(InferenceService().generate("chemistry", "Atoms", "Explain"))


def test_one_base_model_is_reused_across_subject_adapters():
    backend = RecordingBackend()
    config = InferenceConfig(
        backend="fake",
        profiles={"qwen3": ModelProfile("qwen-base")},
        subject_models={"cp": "qwen3", "dsa": "qwen3"},
        max_loaded_models=1,
    )
    service = InferenceService(config, backend)
    asyncio.run(service.generate("cp", "Pointers", "Explain", model="qwen3"))
    asyncio.run(service.generate("dsa", "Trees", "Explain", model="qwen3"))
    assert backend.loads == ["qwen-base"]


class ConcurrencyBackend(FakeBackend):
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()

    def generate(self, loaded, profile, messages, config):
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.08)
        try:
            return super().generate(loaded, profile, messages, config)
        finally:
            with self.guard:
                self.active -= 1


def test_different_gpu_resources_generate_concurrently():
    backend = ConcurrencyBackend()
    service = InferenceService(
        InferenceConfig(
            backend="fake",
            profiles={"a": ModelProfile("a", device=0), "b": ModelProfile("b", device=1)},
            subject_models={"cp": "a", "dsa": "b"},
            max_loaded_models=2,
        ),
        backend,
    )

    async def run():
        await asyncio.gather(
            service.generate("cp", "Pointers", "Explain"),
            service.generate("dsa", "Trees", "Explain"),
        )

    asyncio.run(run())
    assert backend.max_active == 2


def test_models_sharing_one_gpu_are_serialized():
    backend = ConcurrencyBackend()
    service = InferenceService(
        InferenceConfig(
            backend="fake",
            profiles={"a": ModelProfile("a", device=0), "b": ModelProfile("b", device=0)},
            subject_models={"cp": "a", "dsa": "b"},
            max_loaded_models=2,
        ),
        backend,
    )

    async def run():
        await asyncio.gather(
            service.generate("cp", "Pointers", "Explain"),
            service.generate("dsa", "Trees", "Explain"),
        )

    asyncio.run(run())
    assert backend.max_active == 1


def test_ten_students_are_scheduled_across_four_gpus():
    backend = ConcurrencyBackend()
    profiles = {
        "qwen3": ModelProfile("qwen3", device=0),
        "qwen2.5": ModelProfile("qwen2.5", device=0),
        "gemma2": ModelProfile("gemma2", device=1),
        "mistral": ModelProfile("mistral", device=2),
        "granite": ModelProfile("granite", device=3),
    }
    service = InferenceService(
        InferenceConfig(
            backend="fake",
            profiles=profiles,
            subject_models={"cp": "qwen3"},
            max_loaded_models=5,
            max_pending_requests=20,
        ),
        backend,
    )

    async def run():
        names = list(profiles) * 2
        await asyncio.gather(*(service.generate("cp", "Pointers", "Explain", model=name) for name in names))

    asyncio.run(run())
    assert backend.max_active == 4
    assert service.status()["queued_requests"] == 0


def test_vllm_backend_routes_to_subject_adapter():
    captured = {}

    def handler(request):
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "<evaluation>\nScore: High\n</evaluation>\nWhy?"}}]},
        )

    backend = VLLMHTTPBackend()
    backend.client = httpx.Client(transport=httpx.MockTransport(handler))
    profile = ModelProfile(
        "Qwen/Qwen3-8B",
        endpoint="http://127.0.0.1:18101",
        adapter_name="qwen3_cp",
    )
    result = backend.generate(
        profile,
        profile,
        [{"role": "user", "content": "Explain pointers."}],
        InferenceConfig(max_new_tokens=160),
    )
    assert captured["model"] == "qwen3_cp"
    assert captured["max_tokens"] == 160
    assert captured["stream"] is True
    assert result.endswith("Why?")


def test_vllm_stream_stops_after_first_public_question():
    events = "".join(
        [
            'data: {"choices":[{"delta":{"content":"<evaluation>\\nLevel: Apply\\nScore: High\\n"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"Strength: Clear.\\nImprovement: Add detail.\\n</evaluation>\\nWhy?"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":" This should not be returned."}}]}\n\n',
            "data: [DONE]\n\n",
        ]
    )

    backend = VLLMHTTPBackend()
    backend.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=events, headers={"content-type": "text/event-stream"})
        )
    )
    profile = ModelProfile("Qwen/Qwen3-8B", endpoint="http://engine", adapter_name="qwen3_cp")
    result = backend.generate(
        profile,
        profile,
        [{"role": "user", "content": "Explain pointers."}],
        InferenceConfig(max_new_tokens=128),
    )
    assert result.endswith("Why?")
    assert "should not be returned" not in result
