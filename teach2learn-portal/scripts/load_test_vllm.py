from __future__ import annotations

import concurrent.futures
import json
import statistics
import time
import urllib.request


ENDPOINTS = {
    "qwen3": "http://127.0.0.1:18101",
    "gemma2": "http://127.0.0.1:18102",
    "mistral": "http://127.0.0.1:18103",
    "granite": "http://127.0.0.1:18104",
    "qwen2.5": "http://127.0.0.1:18105",
}
SUBJECTS = ("cp", "dsa", "oop_java", "os")
SYSTEM = (
    "You are a curious student learning from a human teacher. Assess the explanation inside <evaluation> tags "
    "using Level, Score, Strength, and Improvement fields, then ask exactly one concise follow-up question."
)


def request(profile: str, subject: str, index: int) -> dict[str, object]:
    teacher = (
        f"Teacher's Answer: A mutex protects a shared critical section by allowing only one thread to enter at a "
        f"time. For example, it prevents two threads from losing an update to a shared counter. Test case {index}."
    )
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": teacher}]
    if profile == "gemma2":
        messages = [{"role": "user", "content": f"System instruction:\n{SYSTEM}\n\n{teacher}"}]
    body = json.dumps(
        {
            "model": f"{profile}_{subject}",
            "messages": messages,
            "max_tokens": 120,
            "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode()
    started = time.perf_counter()
    with urllib.request.urlopen(
        urllib.request.Request(
            f"{ENDPOINTS[profile]}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
        ),
        timeout=90,
    ) as response:
        payload = json.load(response)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    output = str(payload["choices"][0]["message"]["content"])
    return {
        "profile": profile,
        "subject": subject,
        "latency_ms": elapsed_ms,
        "has_evaluation": "<evaluation>" in output.lower() and "</evaluation>" in output.lower(),
        "has_question": "?" in output,
    }


def run_scenario(name: str, jobs: list[tuple[str, str, int]]) -> dict[str, object]:
    started = time.perf_counter()
    results: list[dict[str, object]] = []
    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(request, *job) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
    latencies = sorted(int(item["latency_ms"]) for item in results)
    return {
        "scenario": name,
        "requests": len(jobs),
        "completed": len(results),
        "errors": errors,
        "wall_ms": round((time.perf_counter() - started) * 1000),
        "p50_ms": round(statistics.median(latencies)) if latencies else None,
        "p95_ms": latencies[max(0, round(0.95 * len(latencies)) - 1)] if latencies else None,
        "max_ms": max(latencies) if latencies else None,
        "evaluations_parsed": sum(bool(item["has_evaluation"]) for item in results),
        "questions_present": sum(bool(item["has_question"]) for item in results),
    }


def main() -> None:
    mixed_profiles = list(ENDPOINTS) * 2
    mixed = [(profile, SUBJECTS[index % len(SUBJECTS)], index) for index, profile in enumerate(mixed_profiles)]
    same_model = [("qwen3", SUBJECTS[index % len(SUBJECTS)], index) for index in range(10)]
    print(json.dumps(run_scenario("ten_mixed_models", mixed), sort_keys=True))
    print(json.dumps(run_scenario("ten_qwen3", same_model), sort_keys=True))


if __name__ == "__main__":
    main()
