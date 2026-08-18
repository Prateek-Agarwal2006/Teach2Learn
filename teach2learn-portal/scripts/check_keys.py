"""Confirm the Sarvam and OpenRouter keys in .env.local actually work.

Run before a multilingual session so a misconfigured key surfaces here rather
than degrading silently into an English session.

    .venv/bin/python scripts/check_keys.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

PROJECT_DIR = Path(__file__).resolve().parent.parent


def load_env_local() -> None:
    path = PROJECT_DIR / ".env.local"
    if not path.exists():
        sys.exit(".env.local is missing. Copy .env.example and set APP_ENV=development.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


async def check_sarvam() -> bool:
    sys.path.insert(0, str(PROJECT_DIR))
    from app.services.translation import TranslationService

    backend = os.getenv("T2L_TRANSLATION_BACKEND", "sarvam")
    if backend != "sarvam":
        print(f"  SKIP  T2L_TRANSLATION_BACKEND={backend}, so the real API is never called.")
        return True
    if not os.getenv("SARVAM_API_KEY", "").strip():
        print("  FAIL  SARVAM_API_KEY is empty. Sessions would silently run in English.")
        return False

    service = TranslationService()
    sample = "A scheduler decides which process runs next."
    result = await service.from_english(sample, "hi")
    await service.close()
    if result == sample:
        print("  FAIL  Sarvam returned the input unchanged (passthrough fallback).")
        print("        Re-run with T2L_LOG_LEVEL=DEBUG to see the translation_failed warning.")
        return False
    print(f"  OK    Sarvam [{service.model}] -> {result}")
    return True


async def check_openrouter() -> bool:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("FINAL_FEEDBACK_MODEL", "openai/gpt-5.6-luna").strip()
    if not key:
        print("  WARN  OPENROUTER_API_KEY is empty. The judge falls back to the local adapter,")
        print("        which under INFERENCE_BACKEND=fake returns scripted filler feedback.")
        return True
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
                    "max_tokens": 200,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        print(f"  FAIL  OpenRouter {exc.response.status_code}: {exc.response.text[:200]}")
        return False
    except Exception as exc:
        print(f"  FAIL  OpenRouter unreachable: {type(exc).__name__}")
        return False
    reply = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(f"  OK    OpenRouter [{model}] -> {str(reply).strip()[:60] or '(empty reply)'}")
    return True


async def main() -> int:
    load_env_local()
    print("Sarvam translation:")
    sarvam_ok = await check_sarvam()
    print("OpenRouter judge:")
    openrouter_ok = await check_openrouter()
    print()
    if sarvam_ok and openrouter_ok:
        print("Both checks passed. Start the portal with ./scripts/run-local.sh")
        return 0
    print("Fix the failures above before starting a multilingual session.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
