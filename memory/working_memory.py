from __future__ import annotations

from typing import Any

from storage.database import Database


class WorkingMemory:
    def __init__(self, database: Database) -> None:
        self.database = database

    def put(
        self,
        user_id: str,
        session_id: str,
        key: str,
        value: str,
        kind: str = "note",
        confidence: float = 0.5,
        importance: float = 0.5,
    ) -> None:
        self.database.upsert_working_memory(
            user_id=user_id,
            session_id=session_id,
            key=key,
            value=value,
            kind=kind,
            confidence=confidence,
            importance=importance,
        )

    def list(
        self,
        user_id: str,
        session_id: str | None = None,
        limit: int = 16,
    ) -> list[dict[str, Any]]:
        return self.database.list_working_memory(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )

    def clear_session(self, user_id: str, session_id: str) -> None:
        self.database.clear_working_memory_session(user_id=user_id, session_id=session_id)
