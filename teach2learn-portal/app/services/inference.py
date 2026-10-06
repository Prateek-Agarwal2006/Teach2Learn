"""Lazy, server-side text generation with subject-specific PEFT adapters.

The module deliberately does not import torch, transformers, or peft until the real
backend is used.  Importing and testing the web application can therefore never
download a model on a developer machine.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol, Sequence

from app.topics import normalize_subject


@dataclass(frozen=True)
class ModelProfile:
    base_model: str
    adapter: str | None = None
    trust_remote_code: bool = False
    device: int | str | None = None
    endpoint: str | None = None
    adapter_name: str | None = None
    # Override for a base model whose weights were downloaded into a non-default HF
    # cache (e.g. because the default cache's disk was full at download time) rather
    # than wherever HF_HOME/local_files_only would otherwise look.
    cache_dir: str | None = None


@dataclass(frozen=True)
class GenerationResult:
    content: str
    raw_content: str
    evaluation: Mapping[str, str] | None = None
    queue_wait_ms: int = 0
    generation_ms: int = 0
    fallback_used: bool = False


DEFAULT_PROFILES: dict[str, ModelProfile] = {
    # These are identifiers, not eager dependencies. Deployments normally override
    # the adapter paths (and may override the base models) with INFERENCE_PROFILES.
    "qwen3": ModelProfile("Qwen/Qwen3-8B"),
    "gemma2": ModelProfile("google/gemma-2-9b-it"),
    "mistral": ModelProfile("mistralai/Mistral-7B-Instruct-v0.3"),
    "granite": ModelProfile("ibm-granite/granite-3.3-8b-instruct"),
    "qwen2.5": ModelProfile("Qwen/Qwen2.5-7B-Instruct"),
    # Second batch, fine-tuned to extend the RAG-vs-finetuned comparison to models that
    # are also directly selectable (ungrounded, via OpenRouter) on the RAG side -- see
    # finetune-new-models/ on the GPU host. Granite 4.2 (not 3.3) and Llama 3.1 because
    # those are the versions actually live on OpenRouter. (A third slot, Ministral, was
    # dropped: every current Ministral-3-generation snapshot is vision-multimodal and
    # incompatible with this text-only LoRA pipeline.)
    "granite42": ModelProfile("ibm-granite/granite-4.2-8b"),
    # The default HF cache's disk filled up mid-download during training, so this one's
    # weights only ever landed in finetune-new-models/.hf_cache -- point this profile
    # straight at that cache rather than the shared default.
    "llama31": ModelProfile(
        "meta-llama/Llama-3.1-8B-Instruct",
        cache_dir="/data/scratch/sanyam_jain_2022/finetune-new-models/.hf_cache/hub",
    ),
}

DEFAULT_ADAPTER_ROOT = "/data/scratch/sanyam_jain_2022/mistral_finetune/gemma2_s9b"
MODEL_OUTPUT_DIRS = {
    "qwen3": "outputs_qwen3_8b_lora_no_quant",
    "gemma2": "outputs_gemma2_9b_it_lora_no_quant",
    "mistral": "outputs_mistral7b_lora_no_quant",
    "granite": "outputs_granite33_8b_lora_no_quant",
    "qwen2.5": "outputs_qwen25_7b_lora_no_quant",
    # Empty: these two's adapter root (below) already points straight at the directory
    # that directly contains each subject's final_adapter/, with nothing to join.
    "granite42": "",
    "llama31": "",
}
SUBJECT_DATASET_DIRS = {"cp": "CP_dataset", "dsa": "DSA_dataset", "oop_java": "oops_dataset", "os": "OS_dataset"}

# Per-profile override of the shared adapter_root below -- these two live in their own
# training directory (finetune-new-models/), separate from Sanyam's own mistral_finetune/
# tree, which this deployment only ever reads from, never writes into.
NEW_MODEL_ADAPTER_ROOT = "/data/scratch/sanyam_jain_2022/finetune-new-models/outputs"
MODEL_ADAPTER_ROOTS = {
    "granite42": f"{NEW_MODEL_ADAPTER_ROOT}/granite42",
    "llama31": f"{NEW_MODEL_ADAPTER_ROOT}/llama31",
}

DEFAULT_SUBJECT_MODELS = {
    "cp": "qwen3",
    "dsa": "gemma2",
    "oop_java": "mistral",
    "os": "granite",
}


@dataclass(frozen=True)
class InferenceConfig:
    backend: str = "fake"
    profiles: Mapping[str, ModelProfile] = field(default_factory=lambda: DEFAULT_PROFILES.copy())
    subject_models: Mapping[str, str] = field(default_factory=lambda: DEFAULT_SUBJECT_MODELS.copy())
    max_loaded_models: int = 1
    max_new_tokens: int = 192
    temperature: float = 0.25
    top_p: float = 0.9
    local_files_only: bool = True
    device_map: str = "auto"
    torch_dtype: str = "auto"
    adapter_root: str = DEFAULT_ADAPTER_ROOT
    max_pending_requests: int = 20
    queue_timeout_seconds: float = 120.0
    preload_models: bool = False
    stop_after_question: bool = True

    @classmethod
    def from_env(cls) -> "InferenceConfig":
        profiles = DEFAULT_PROFILES.copy()
        raw_profiles = os.getenv("INFERENCE_PROFILES", "").strip()
        if raw_profiles:
            for name, value in json.loads(raw_profiles).items():
                if isinstance(value, str):
                    profiles[name] = ModelProfile(value)
                else:
                    profiles[name] = ModelProfile(
                        base_model=value["base_model"],
                        adapter=value.get("adapter"),
                        trust_remote_code=bool(value.get("trust_remote_code", False)),
                        device=value.get("device"),
                        endpoint=value.get("endpoint"),
                    )

        subject_models = DEFAULT_SUBJECT_MODELS.copy()
        raw_routing = os.getenv("INFERENCE_SUBJECT_MODELS", "").strip()
        if raw_routing:
            subject_models.update({normalize_subject(k): v for k, v in json.loads(raw_routing).items()})

        # Simple per-profile adapter variables make production .env files readable.
        for name, profile in list(profiles.items()):
            prefix = "INFERENCE_" + re.sub(r"[^A-Z0-9]", "_", name.upper())
            base = os.getenv(prefix + "_BASE_MODEL", profile.base_model)
            adapter = os.getenv(prefix + "_ADAPTER", profile.adapter)
            profiles[name] = ModelProfile(
                base,
                adapter or None,
                profile.trust_remote_code,
                profile.device,
                profile.endpoint,
                profile.adapter_name,
                profile.cache_dir,
            )

        raw_devices = os.getenv("INFERENCE_PROFILE_DEVICES", "").strip()
        if raw_devices:
            for name, device in json.loads(raw_devices).items():
                if name not in profiles:
                    raise ValueError(f"Unknown profile in INFERENCE_PROFILE_DEVICES: {name}")
                profile = profiles[name]
                if isinstance(device, str) and device.isdigit():
                    device = int(device)
                profiles[name] = ModelProfile(
                    profile.base_model,
                    profile.adapter,
                    profile.trust_remote_code,
                    device,
                    profile.endpoint,
                    profile.adapter_name,
                    profile.cache_dir,
                )

        raw_endpoints = os.getenv("INFERENCE_VLLM_ENDPOINTS", "").strip()
        if raw_endpoints:
            for name, endpoint in json.loads(raw_endpoints).items():
                if name not in profiles:
                    raise ValueError(f"Unknown profile in INFERENCE_VLLM_ENDPOINTS: {name}")
                profile = profiles[name]
                profiles[name] = ModelProfile(
                    profile.base_model,
                    profile.adapter,
                    profile.trust_remote_code,
                    profile.device,
                    str(endpoint).rstrip("/"),
                    profile.adapter_name,
                    profile.cache_dir,
                )

        return cls(
            backend=os.getenv("INFERENCE_BACKEND", "fake").lower(),
            profiles=profiles,
            subject_models=subject_models,
            max_loaded_models=max(1, int(os.getenv("INFERENCE_MAX_LOADED_MODELS", "1"))),
            max_new_tokens=int(os.getenv("INFERENCE_MAX_NEW_TOKENS", "192")),
            temperature=float(os.getenv("INFERENCE_TEMPERATURE", "0.25")),
            top_p=float(os.getenv("INFERENCE_TOP_P", "0.9")),
            local_files_only=os.getenv("INFERENCE_LOCAL_FILES_ONLY", "true").lower() not in {"0", "false", "no"},
            device_map=os.getenv("INFERENCE_DEVICE_MAP", "auto"),
            torch_dtype=os.getenv("INFERENCE_TORCH_DTYPE", "auto"),
            adapter_root=os.getenv("INFERENCE_ADAPTER_ROOT", DEFAULT_ADAPTER_ROOT),
            max_pending_requests=max(1, int(os.getenv("INFERENCE_MAX_PENDING_REQUESTS", "20"))),
            queue_timeout_seconds=max(1.0, float(os.getenv("INFERENCE_QUEUE_TIMEOUT_SECONDS", "120"))),
            preload_models=os.getenv("INFERENCE_PRELOAD_MODELS", "false").lower() in {"1", "true", "yes", "on"},
        )


class InferenceBusyError(RuntimeError):
    """The bounded inference queue has no remaining capacity."""


class InferenceQueueTimeoutError(TimeoutError):
    """A request waited too long for its assigned GPU."""


class Backend(Protocol):
    def load(self, profile: ModelProfile) -> Any: ...
    def generate(
        self,
        loaded: Any,
        profile: ModelProfile,
        messages: Sequence[Mapping[str, str]],
        config: InferenceConfig,
    ) -> str: ...
    def unload(self, loaded: Any) -> None: ...


# Scripted learner questions for local development, keyed on the selected subtopic
# exactly as it reaches the model in "Selected topic:". Only Operating Systems ->
# Threads and scheduling -> CPU scheduling is covered; every other subtopic keeps the
# single generic follow-up below. Index 0 opens the lesson, the rest are follow-ups
# walked by turn. Every entry must end in "?" or generate_detailed replaces it with the
# generic fallback question.
_FAKE_LEARNER_SCRIPTS: dict[str, tuple[str, ...]] = {
    "cpu scheduling": (
        "Hi! I’m ready to learn about CPU scheduling. Why does the operating system need to "
        "choose which process runs next at all?",
        "That makes sense so far. If two processes are both ready at the same moment, how does "
        "the scheduler actually decide between them?",
        "Could you walk me through a small example with three processes and show what order "
        "round-robin would run them in?",
        "You mentioned the time quantum. What goes wrong if it is set far too small, and what "
        "goes wrong if it is set far too large?",
        "How is a scheduler that has to meet a real-time deadline different from one that is "
        "just trying to keep the CPU busy?",
        "If I told you a scheduler was fair, how would you test that claim? What would you "
        "actually measure?",
        "Where does the cost of a context switch show up in all of this, and does it change "
        "which algorithm you would pick?",
    ),
}


class FakeBackend:
    """Deterministic backend used by development, CI, and API tests."""

    def load(self, profile: ModelProfile) -> ModelProfile:
        return profile

    def generate(
        self,
        loaded: ModelProfile,
        profile: ModelProfile,
        messages: Sequence[Mapping[str, str]],
        config: InferenceConfig,
    ) -> str:
        prompt = "\n".join(str(message.get("content", "")) for message in messages).lower()
        if "independent final teaching evaluator" in prompt:
            return (
                "<final_feedback>\n"
                "Strength: You explained the core idea clearly and stayed responsive to the learner.\n"
                "Strength: You used relevant details to build the learner's understanding.\n"
                "Improvement: Add one concrete example and explain why each step works.\n"
                "Improvement: Check the learner's understanding before moving to a harder idea.\n"
                "Summary: You built a useful explanation across the conversation. Your clearest moments connected the core idea to how it works; adding a concrete worked example would make the teaching more complete.\n"
                "</final_feedback>"
            )
        if "independent turn evaluator" in prompt:
            return (
                "<evaluation>\nLevel: Understand\nScore: Medium\n"
                "Strength: The explanation identifies the central idea clearly.\n"
                "Improvement: Add a concrete example and explain why it works.\n</evaluation>"
            )
        question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        topic_match = re.search(r"Selected topic:\s*(.+)", messages[0]["content"] if messages else "")
        topic = topic_match.group(1).strip() if topic_match else "the selected topic"
        script = _FAKE_LEARNER_SCRIPTS.get(topic.strip().lower())
        if "lesson is starting" in question.lower() or "[system trigger]" in question.lower():
            if script:
                return script[0]
            return f"Hi! I’m ready to learn about {topic}. What problem does this idea help us solve?"
        if script:
            # One question already asked per assistant turn in the history; clamp so a
            # session that runs long repeats the last question rather than raising.
            asked = sum(1 for message in messages if message.get("role") == "assistant")
            return script[min(max(asked, 1), len(script) - 1)]
        return f"I think I follow your explanation of {topic}. Could you give me a concrete example and explain why it works?"

    def unload(self, loaded: Any) -> None:
        return None

class VLLMHTTPBackend:
    """OpenAI-compatible client for resident, continuously batched vLLM engines."""

    supports_concurrency = True

    def __init__(self) -> None:
        import httpx

        self.client = httpx.Client(timeout=httpx.Timeout(70.0, connect=3.0), limits=httpx.Limits(max_connections=32))

    def load(self, profile: ModelProfile) -> ModelProfile:
        if not profile.endpoint:
            raise RuntimeError(f"No vLLM endpoint configured for {profile.base_model}")
        return profile

    def generate(
        self,
        loaded: ModelProfile,
        profile: ModelProfile,
        messages: Sequence[Mapping[str, str]],
        config: InferenceConfig,
    ) -> str:
        formatted_messages = normalize_chat_messages(messages)
        if "gemma" in profile.base_model.lower() and formatted_messages and formatted_messages[0]["role"] == "system":
            system_text = formatted_messages.pop(0)["content"]
            if formatted_messages and formatted_messages[0]["role"] == "user":
                formatted_messages[0] = {
                    "role": "user",
                    "content": f"System instruction:\n{system_text}\n\nConversation:\n{formatted_messages[0]['content']}",
                }
            else:
                formatted_messages.insert(0, {"role": "user", "content": f"System instruction:\n{system_text}"})
        request_body = {
                "model": profile.adapter_name or profile.base_model,
                "messages": formatted_messages,
                "max_tokens": config.max_new_tokens,
                "temperature": config.temperature,
                "top_p": config.top_p,
                "chat_template_kwargs": {"enable_thinking": False},
                "stream": True,
            }
        chunks: list[str] = []
        with self.client.stream(
            "POST",
            f"{profile.endpoint}/v1/chat/completions",
            json=request_body,
        ) as response:
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                response.read()
                payload = response.json()
                return str(payload["choices"][0]["message"]["content"])
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                payload = json.loads(data)
                choices = payload.get("choices") or []
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content")
                if content:
                    chunks.append(str(content))
                    if config.stop_after_question and should_stop_after_question("".join(chunks)):
                        break
        return "".join(chunks)

    def unload(self, loaded: Any) -> None:
        return None

    def healthcheck(self, profiles: Sequence[ModelProfile]) -> None:
        for endpoint in sorted({profile.endpoint for profile in profiles if profile.endpoint}):
            response = self.client.get(f"{endpoint}/health")
            response.raise_for_status()


class TransformersBackend:
    """Transformers + PEFT backend; all heavyweight imports and loads are lazy."""

    @dataclass
    class LoadedModel:
        tokenizer: Any
        model: Any
        base_model: str
        adapters: dict[str, str] = field(default_factory=dict)

    def load(self, profile: ModelProfile) -> LoadedModel:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("Real inference requires the server inference dependencies: torch and transformers") from exc

        dtype: Any = self.config.torch_dtype
        if dtype != "auto":
            dtype = getattr(torch, dtype, dtype)
        tokenizer = AutoTokenizer.from_pretrained(
            profile.base_model,
            trust_remote_code=profile.trust_remote_code,
            local_files_only=self.config.local_files_only,
            cache_dir=profile.cache_dir,
        )
        device_map: Any = self.config.device_map
        if profile.device is not None:
            device_map = {"": profile.device}
        model = AutoModelForCausalLM.from_pretrained(
            profile.base_model,
            device_map=device_map,
            dtype=dtype,
            trust_remote_code=profile.trust_remote_code,
            local_files_only=self.config.local_files_only,
            cache_dir=profile.cache_dir,
        )
        model.eval()
        return self.LoadedModel(tokenizer, model, profile.base_model)

    def __init__(self, config: InferenceConfig):
        self.config = config

    def generate(
        self,
        loaded: LoadedModel,
        profile: ModelProfile,
        messages: Sequence[Mapping[str, str]],
        config: InferenceConfig,
    ) -> str:
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        tokenizer, model = loaded.tokenizer, loaded.model
        if profile.adapter:
            try:
                from peft import PeftModel
            except ImportError as exc:
                raise RuntimeError("A configured adapter requires peft on the inference server") from exc
            adapter_name = loaded.adapters.get(profile.adapter)
            if adapter_name is None:
                adapter_name = "portal_" + hashlib.sha256(profile.adapter.encode("utf-8")).hexdigest()[:12]
                if isinstance(model, PeftModel):
                    model.load_adapter(
                        profile.adapter,
                        adapter_name=adapter_name,
                        is_trainable=False,
                        low_cpu_mem_usage=True,
                    )
                else:
                    model = PeftModel.from_pretrained(
                        model,
                        profile.adapter,
                        adapter_name=adapter_name,
                        is_trainable=False,
                        local_files_only=config.local_files_only,
                        low_cpu_mem_usage=True,
                    )
                    loaded.model = model
                loaded.adapters[profile.adapter] = adapter_name
            model.set_adapter(adapter_name)
            model.eval()
        formatted_messages = normalize_chat_messages(messages)
        if "gemma" in profile.base_model.lower() and formatted_messages and formatted_messages[0]["role"] == "system":
            system_text = formatted_messages.pop(0)["content"]
            if formatted_messages and formatted_messages[0]["role"] == "user":
                formatted_messages[0] = {
                    "role": "user",
                    "content": f"System instruction:\n{system_text}\n\nConversation:\n{formatted_messages[0]['content']}",
                }
            else:
                formatted_messages.insert(0, {"role": "user", "content": f"System instruction:\n{system_text}"})
        template_kwargs: dict[str, Any] = {"tokenize": False, "add_generation_prompt": True}
        if "qwen" in profile.base_model.lower():
            template_kwargs["enable_thinking"] = False
        try:
            text = tokenizer.apply_chat_template(formatted_messages, **template_kwargs)
        except TypeError:
            template_kwargs.pop("enable_thinking", None)
            text = tokenizer.apply_chat_template(formatted_messages, **template_kwargs)
        inputs = tokenizer(text, return_tensors="pt")
        device = next(model.parameters()).device
        inputs = {key: value.to(device) for key, value in inputs.items()}
        prompt_tokens = inputs["input_ids"].shape[-1]

        class StopAfterFirstCompleteQuestion(StoppingCriteria):
            def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> Any:
                generated_text = tokenizer.decode(input_ids[0, prompt_tokens:], skip_special_tokens=True)
                should_stop = should_stop_after_question(generated_text)
                return torch.full((input_ids.shape[0],), should_stop, dtype=torch.bool, device=input_ids.device)

        kwargs: dict[str, Any] = {
            "max_new_tokens": config.max_new_tokens,
            "do_sample": config.temperature > 0,
            "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
        }
        if config.stop_after_question:
            kwargs["stopping_criteria"] = StoppingCriteriaList([StopAfterFirstCompleteQuestion()])
        if kwargs["do_sample"]:
            kwargs.update(temperature=config.temperature, top_p=config.top_p)
        with torch.inference_mode():
            output = model.generate(**inputs, **kwargs)
        generated = output[0, inputs["input_ids"].shape[-1] :]
        return tokenizer.decode(generated, skip_special_tokens=True)

    def unload(self, loaded: LoadedModel) -> None:
        del loaded.model
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


class InferenceService:
    def __init__(self, config: InferenceConfig | None = None, backend: Backend | None = None):
        self.config = config or InferenceConfig.from_env()
        if backend is None:
            if self.config.backend == "fake":
                backend = FakeBackend()
            elif self.config.backend in {"transformers", "real"}:
                backend = TransformersBackend(self.config)
            elif self.config.backend == "vllm":
                backend = VLLMHTTPBackend()
            else:
                raise ValueError(f"Unsupported INFERENCE_BACKEND: {self.config.backend}")
        self.backend = backend
        self._loaded: OrderedDict[str, Any] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._queue_guard = asyncio.Lock()
        self._resource_locks: dict[str, asyncio.Lock] = {}
        self._waiting_by_resource: dict[str, int] = {}
        self._active_by_resource: dict[str, int] = {}
        self._active_profiles: set[str] = set()
        self._preload_state = "disabled" if not self.config.preload_models else "pending"
        self._preload_error: str | None = None

    def _profile_for(self, subject: str, requested_model: str | None = None) -> tuple[str, ModelProfile]:
        subject_key = normalize_subject(subject)
        try:
            profile_name = requested_model or self.config.subject_models[subject_key]
            profile = self.config.profiles[profile_name]
        except KeyError as exc:
            raise ValueError(f"No inference model configured for {requested_model or subject!r}") from exc
        if not profile.adapter and profile_name in MODEL_OUTPUT_DIRS:
            from pathlib import Path

            adapter_root = MODEL_ADAPTER_ROOTS.get(profile_name, self.config.adapter_root)
            try:
                adapter = Path(adapter_root) / MODEL_OUTPUT_DIRS[profile_name] / SUBJECT_DATASET_DIRS[subject_key] / "final_adapter"
            except KeyError as exc:
                raise ValueError(f"No adapter mapping for model {profile_name!r} and subject {subject!r}") from exc
            profile = ModelProfile(
                profile.base_model,
                str(adapter),
                profile.trust_remote_code,
                profile.device,
                profile.endpoint,
                f"{profile_name}_{subject_key}",
                profile.cache_dir,
            )
        return profile_name, profile

    @staticmethod
    def _resource_key(profile_name: str, profile: ModelProfile) -> str:
        return f"device:{profile.device}" if profile.device is not None else f"profile:{profile_name}"

    def _load(self, name: str, profile: ModelProfile) -> Any:
        if name in self._loaded:
            self._loaded.move_to_end(name)
            return self._loaded[name]
        while len(self._loaded) >= self.config.max_loaded_models:
            evictable = next((key for key in self._loaded if key not in self._active_profiles), None)
            if evictable is None:
                raise InferenceBusyError("All resident model slots are currently active")
            old = self._loaded.pop(evictable)
            self.backend.unload(old)
        loaded = self.backend.load(profile)
        self._loaded[name] = loaded
        return loaded

    async def _enter_resource(self, resource: str) -> tuple[asyncio.Lock, int, int]:
        lock = self._resource_locks.setdefault(resource, asyncio.Lock())
        started = time.perf_counter()
        async with self._queue_guard:
            waiting_total = sum(self._waiting_by_resource.values())
            active_total = sum(self._active_by_resource.values())
            if waiting_total + active_total >= self.config.max_pending_requests:
                raise InferenceBusyError("The inference queue is full")
            position = self._waiting_by_resource.get(resource, 0) + (1 if lock.locked() else 0)
            self._waiting_by_resource[resource] = self._waiting_by_resource.get(resource, 0) + 1
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self.config.queue_timeout_seconds)
        except TimeoutError as exc:
            raise InferenceQueueTimeoutError("Timed out waiting for the assigned GPU") from exc
        finally:
            async with self._queue_guard:
                self._waiting_by_resource[resource] -= 1
        async with self._queue_guard:
            self._active_by_resource[resource] = self._active_by_resource.get(resource, 0) + 1
        return lock, position, round((time.perf_counter() - started) * 1000)

    async def _leave_resource(self, resource: str, lock: asyncio.Lock) -> None:
        async with self._queue_guard:
            self._active_by_resource[resource] = max(0, self._active_by_resource.get(resource, 1) - 1)
        lock.release()
        if resource.startswith("request:"):
            self._resource_locks.pop(resource, None)
            self._active_by_resource.pop(resource, None)

    def queue_status(self, subject: str, model: str | None = None) -> dict[str, int | bool]:
        if getattr(self.backend, "supports_concurrency", False):
            return {"busy": False, "queue_position": 0}
        profile_name, profile = self._profile_for(subject, model)
        resource = self._resource_key(profile_name, profile)
        lock = self._resource_locks.get(resource)
        waiting = self._waiting_by_resource.get(resource, 0)
        return {"busy": bool(lock and lock.locked()), "queue_position": waiting + (1 if lock and lock.locked() else 0)}

    def status(self) -> dict[str, int | str | None]:
        supports_concurrency = getattr(self.backend, "supports_concurrency", False)
        external_engine_count = (
            len(self.config.profiles) if supports_concurrency else 0
        )
        return {
            "loaded_models": external_engine_count or len(self._loaded),
            "serving_mode": (
                "continuous_batching"
                if supports_concurrency
                else "in_process"
            ),
            "active_requests": sum(self._active_by_resource.values()),
            "queued_requests": sum(self._waiting_by_resource.values()),
            "model_capacity": self.config.max_loaded_models,
            "queue_capacity": self.config.max_pending_requests,
            "preload_state": self._preload_state,
            "preload_error": self._preload_error,
        }

    async def preload_all(self) -> None:
        self._preload_state = "running"
        try:
            for profile_name, profile in self.config.profiles.items():
                resource = self._resource_key(profile_name, profile)
                lock, _, _ = await self._enter_resource(resource)
                try:
                    async with self._cache_lock:
                        self._active_profiles.add(profile_name)
                        try:
                            await asyncio.to_thread(self._load, profile_name, profile)
                        finally:
                            self._active_profiles.discard(profile_name)
                finally:
                    await self._leave_resource(resource, lock)
        except Exception as exc:
            self._preload_state = "failed"
            self._preload_error = f"{type(exc).__name__}: {exc}"[:500]
            raise
        self._preload_state = "completed"

    async def check_ready(self) -> None:
        healthcheck = getattr(self.backend, "healthcheck", None)
        if healthcheck:
            await asyncio.to_thread(healthcheck, list(self.config.profiles.values()))

    async def generate(
        self,
        subject: str,
        topic: str,
        question: str | None = None,
        *,
        messages: Sequence[Mapping[str, str]] | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> str:
        result = await self.generate_detailed(
            subject,
            topic,
            question,
            messages=messages,
            system_prompt=system_prompt,
            model=model,
        )
        return result.content

    async def generate_detailed(
        self,
        subject: str,
        topic: str,
        question: str | None = None,
        *,
        messages: Sequence[Mapping[str, str]] | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        transform_history: bool = True,
        stop_after_question: bool = True,
        max_new_tokens: int | None = None,
        branch_instruction: str | None = None,
    ) -> GenerationResult:
        if not topic.strip():
            raise ValueError("topic is required")
        if messages is None:
            if not question or not question.strip():
                raise ValueError("question is required")
            messages = [{"role": "user", "content": question.strip()}]
        instruction = system_prompt or (
            "You are a curious student learning from a human teacher. Evaluate each teacher explanation internally "
            "inside <evaluation> tags with Level, Score, Strength, and Improvement fields, then ask one concise, "
            "natural follow-up question. Do not act like the teacher."
        )
        messages = training_contract_messages(messages) if transform_history else [dict(message) for message in messages]
        if branch_instruction:
            messages = [*messages]
            branch_task = f"[Branch task]\n{branch_instruction.strip()}"
            if messages and messages[-1]["role"] == "user":
                messages[-1] = {**messages[-1], "content": f"{messages[-1]['content']}\n\n{branch_task}"}
            else:
                messages.append({"role": "user", "content": branch_task})
        routed_messages = [
            {"role": "system", "content": f"{instruction}\nSelected topic: {topic.strip()}"},
            *({"role": str(m["role"]), "content": str(m["content"])} for m in messages),
        ]
        profile_name, profile = self._profile_for(subject, model)
        resource = (
            f"request:{id(asyncio.current_task())}:{time.monotonic_ns()}"
            if getattr(self.backend, "supports_concurrency", False)
            else self._resource_key(profile_name, profile)
        )
        lock, _, queue_wait_ms = await self._enter_resource(resource)
        try:
            async with self._cache_lock:
                self._active_profiles.add(profile_name)
                try:
                    loaded = await asyncio.to_thread(self._load, profile_name, profile)
                except Exception:
                    self._active_profiles.discard(profile_name)
                    raise
            generation_started = time.perf_counter()
            request_config = replace(
                self.config,
                stop_after_question=stop_after_question,
                max_new_tokens=max_new_tokens or self.config.max_new_tokens,
            )
            raw_output = await asyncio.to_thread(self.backend.generate, loaded, profile, routed_messages, request_config)
            generation_ms = round((time.perf_counter() - generation_started) * 1000)
        finally:
            async with self._cache_lock:
                self._active_profiles.discard(profile_name)
            await self._leave_resource(resource, lock)
        public_content = clean_output(raw_output)
        fallback_used = stop_after_question and "?" not in public_content
        if fallback_used:
            public_content = "Could you give me one concrete example that shows how this works?"
        return GenerationResult(
            content=public_content,
            raw_content=raw_output.strip(),
            evaluation=parse_inline_evaluation(raw_output),
            queue_wait_ms=queue_wait_ms,
            generation_ms=generation_ms,
            fallback_used=fallback_used,
        )

    async def unload_all(self) -> None:
        async with self._cache_lock:
            while self._loaded:
                _, loaded = self._loaded.popitem(last=False)
                await asyncio.to_thread(self.backend.unload, loaded)


def clean_output(text: str) -> str:
    """Remove common chat-template debris without altering the answer itself."""
    # Some reasoning models expose their private scratchpad in a tagged prefix.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<evaluation>.*?(?:</evaluation>|$)", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r"^\s*(?:evaluation|level|score|strength|improvement|feedback)\s*:\s*.*(?:\n|$)",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    text = re.sub(r"<\|(?:assistant|im_start|im_end|endoftext)\|>", "", text)
    text = re.sub(r"^\s*(?:assistant|model)\s*:\s*", "", text, flags=re.IGNORECASE)
    # Some adapters continue into the next training-dialogue field after producing
    # the student's question. Keep only the assistant turn that the portal asked for.
    text = re.split(
        r"\n\s*(?:user|human|teacher(?:'s)?\s+answer|previous\s+question)\s*:?(?:\s|$)",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return text.strip()


def should_stop_after_question(text: str) -> bool:
    """Stop once one public question is complete, but never inside a private assessment."""
    lowered = text.lower()
    if "<evaluation>" in lowered and "</evaluation>" not in lowered:
        return False
    return "?" in clean_output(text)


def parse_inline_evaluation(text: str) -> dict[str, str] | None:
    match = re.search(r"<evaluation>(.*?)</evaluation>", text, flags=re.DOTALL | re.IGNORECASE)
    body = match.group(1).strip() if match else text.strip()
    result: dict[str, str] = {"raw": body}
    for key in ("level", "score", "strength", "improvement", "feedback"):
        field = re.search(rf"^\s*{key}\s*:\s*(.+)$", body, flags=re.MULTILINE | re.IGNORECASE)
        if field:
            result[key] = field.group(1).strip()
    required = {"level", "score", "strength", "improvement"}
    return result if match or required.issubset(result) else None


def training_contract_messages(messages: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Render clean portal history in the lexical format used by adapter training."""
    rendered: list[dict[str, str]] = []
    previous_question = ""
    teacher_turn = 0
    for item in messages:
        role = str(item["role"])
        content = str(item["content"]).strip()
        if role == "assistant":
            previous_question = content
        elif role == "user":
            if "lesson is starting" in content.lower():
                content = "[SYSTEM TRIGGER]: The user has entered the room. Initiate the lesson by asking your first question."
            else:
                teacher_turn += 1
                prefix = ""
                if teacher_turn > 1 and previous_question:
                    prefix = f"Previous Question: {previous_question}\n"
                content = f"{prefix}Teacher's Answer: {content}"
        rendered.append({"role": role, "content": content})
    return rendered


def normalize_chat_messages(messages: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Make stored portal history valid for strict alternating chat templates."""
    normalized = [{"role": str(item["role"]), "content": str(item["content"])} for item in messages]
    if len(normalized) > 1 and normalized[0]["role"] == "system" and normalized[1]["role"] == "assistant":
        normalized.insert(1, {"role": "user", "content": "Begin the lesson by asking your first question."})
    return normalized


_service: InferenceService | None = None


def get_inference_service() -> InferenceService:
    global _service
    if _service is None:
        _service = InferenceService()
    return _service
