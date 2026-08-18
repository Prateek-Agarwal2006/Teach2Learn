from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from app.db import Database

Evaluator = Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]


class EvaluationService:
    """Coordinates an optional evaluator and persists its lifecycle."""

    def __init__(self, database: Database, evaluator: Evaluator | None = None, *, enabled: bool = False):
        self.database = database
        self.evaluator = evaluator
        self.enabled = enabled

    @property
    def connected(self) -> bool:
        return self.enabled and self.evaluator is not None

    async def evaluate(self, session_id: str, transcript: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        session = self.database.get_session(session_id)
        if session is None:
            raise KeyError(f"unknown session: {session_id}")
        if session["status"] != "completed":
            raise ValueError("only completed conversations can be evaluated")
        if not self.connected:
            self.database.set_evaluation(session_id, "skipped", error="evaluator is not connected")
            return None
        self.database.set_evaluation(session_id, "running")
        try:
            result = self.evaluator(transcript)
            if inspect.isawaitable(result):
                result = await result
            result = dict(result)
            self.database.set_evaluation(session_id, "completed", result=result)
            return result
        except Exception as exc:
            self.database.set_evaluation(session_id, "failed", error=str(exc))
            raise
