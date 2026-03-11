from __future__ import annotations

import hashlib
import re
from typing import Any

from memory.episodic_memory import EpisodicMemory
from memory.models import (
    EpisodicMemoryItem,
    ExtractionCandidate,
    ExtractionResult,
    MemoryContext,
    ProfileMemoryItem,
    SemanticMemoryItem,
    WorkingMemoryItem,
)
from memory.semantic_memory import SemanticMemory
from memory.user_memory import UserMemory
from memory.working_memory import WorkingMemory


class MemoryManager:
    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        user_memory: UserMemory,
        working_memory: WorkingMemory | None = None,
    ) -> None:
        self.episodic = episodic
        self.semantic = semantic
        self.user_memory = user_memory
        self.working_memory = working_memory

        self._database = episodic.database

    def ingest_user_turn(
        self,
        user_id: str,
        agent_id: str | None,
        session_id: str | None,
        content: str,
    ) -> ExtractionResult:
        fingerprint = self._fingerprint(content)
        self.episodic.add(
            user_id=user_id,
            agent_id=agent_id,
            role="user",
            content=content,
            session_id=session_id,
            kind="interaction",
            confidence=1.0,
            importance=0.8,
            fingerprint=fingerprint,
        )

        if self.working_memory is not None and session_id:
            self.working_memory.put(
                user_id=user_id,
                session_id=session_id,
                key="last_user_message",
                value=content,
                kind="recent_turn",
                confidence=1.0,
                importance=0.9,
            )

        extracted = self.extract_from_text(content)
        self._apply_extraction(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            source_role="user",
            source_text=content,
            extracted=extracted,
        )
        return extracted

    def ingest_assistant_turn(
        self,
        user_id: str,
        agent_id: str | None,
        session_id: str | None,
        content: str,
    ) -> ExtractionResult:
        fingerprint = self._fingerprint(content)
        self.episodic.add(
            user_id=user_id,
            agent_id=agent_id,
            role="assistant",
            content=content,
            session_id=session_id,
            kind="interaction",
            confidence=0.95,
            importance=0.6,
            fingerprint=fingerprint,
        )

        if self.working_memory is not None and session_id:
            self.working_memory.put(
                user_id=user_id,
                session_id=session_id,
                key="last_assistant_message",
                value=content,
                kind="recent_turn",
                confidence=0.95,
                importance=0.7,
            )

        extracted = self.extract_from_text(content)
        self._apply_extraction(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            source_role="assistant",
            source_text=content,
            extracted=extracted,
        )
        return extracted

    def build_context(
        self,
        user_id: str,
        agent_id: str | None,
        query: str,
        session_id: str | None = None,
        working_limit: int = 12,
        episodic_limit: int = 16,
        semantic_top_k: int = 8,
    ) -> MemoryContext:
        working_raw = (
            self.working_memory.list(user_id=user_id, session_id=session_id, limit=working_limit)
            if self.working_memory is not None
            else []
        )
        episodic_raw = self.episodic.recent(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            limit=episodic_limit,
        )
        semantic_raw = self.semantic.search(user_id=user_id, query=query, top_k=semantic_top_k)
        profile_raw = self.user_memory.items(user_id=user_id)

        working = [WorkingMemoryItem(**item) for item in working_raw]
        episodic = [EpisodicMemoryItem(**item) for item in episodic_raw]

        semantic: list[SemanticMemoryItem] = []
        for item in semantic_raw:
            metadata = item.get("metadata", {})
            semantic.append(
                SemanticMemoryItem(
                    text=str(item.get("text", "")),
                    score=float(item.get("score", 0.0)),
                    metadata=metadata if isinstance(metadata, dict) else {},
                    kind=str((metadata or {}).get("kind", "fact")),
                    confidence=float((metadata or {}).get("confidence", 0.8)),
                    importance=float((metadata or {}).get("importance", 0.5)),
                )
            )

        profile = [ProfileMemoryItem(**item) for item in profile_raw]
        return MemoryContext(
            working=working,
            episodic=episodic,
            semantic=semantic,
            profile=profile,
        )

    # Backward-compatible wrappers used by current task executor/api.
    def add_interaction(
        self,
        user_id: str,
        agent_id: str | None,
        role: str,
        content: str,
        session_id: str | None = None,
    ) -> None:
        if role == "user":
            self.ingest_user_turn(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                content=content,
            )
            return
        if role == "assistant":
            self.ingest_assistant_turn(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                content=content,
            )
            return

        self.episodic.add(
            user_id=user_id,
            agent_id=agent_id,
            role=role,
            content=content,
            session_id=session_id,
            kind="interaction",
            confidence=0.8,
            importance=0.5,
            fingerprint=self._fingerprint(content),
        )

    def remember_fact(
        self,
        user_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        return self.semantic.add(
            user_id=user_id,
            text=text,
            metadata=metadata,
            kind="fact",
            confidence=0.7,
            importance=0.6,
            fingerprint=self._fingerprint(text),
        )

    def set_user_preference(self, user_id: str, key: str, value: str) -> None:
        previous = self.user_memory.get_all(user_id=user_id).get(key)
        if previous is not None and previous != value:
            self._database.add_conflict_record(
                user_id=user_id,
                layer="profile",
                key=key,
                previous_value=previous,
                incoming_value=value,
                resolution="incoming_overwrites_previous",
                confidence_prev=0.7,
                confidence_new=0.9,
            )
        self.user_memory.set(
            user_id=user_id,
            key=key,
            value=value,
            confidence=0.9,
            importance=0.8,
            source="user_preference",
        )

    def get_context(
        self,
        user_id: str,
        agent_id: str | None,
        query: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        context = self.build_context(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            query=query,
        )
        profile_map = {item.key: item.value for item in context.profile}
        return {
            "working": [item.model_dump() for item in context.working],
            "episodic": [item.model_dump() for item in context.episodic],
            "semantic": [item.model_dump() for item in context.semantic],
            "profile": [item.model_dump() for item in context.profile],
            "user": profile_map,
        }

    def list_extractions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._database.list_extraction_records(user_id=user_id, limit=limit)

    def list_conflicts(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._database.list_conflict_records(user_id=user_id, limit=limit)

    def extract_from_text(self, text: str) -> ExtractionResult:
        normalized = text.strip()
        lowered = normalized.lower()

        facts: list[ExtractionCandidate] = []
        preferences: list[ExtractionCandidate] = []
        tasks: list[ExtractionCandidate] = []

        name_match = re.search(r"\b(?:my name is|i am|i'm)\s+([A-Za-z][A-Za-z0-9_\- ]{1,40})", normalized, re.I)
        if name_match:
            value = name_match.group(1).strip()
            facts.append(
                ExtractionCandidate(
                    kind="fact",
                    text=f"user_name={value}",
                    key="name",
                    value=value,
                    confidence=0.75,
                )
            )

        prefer_match = re.search(r"\b(?:i prefer|my favorite|i like)\s+(.+)$", normalized, re.I)
        if prefer_match:
            value = prefer_match.group(1).strip(" .,!?:;")
            preferences.append(
                ExtractionCandidate(
                    kind="preference",
                    text=f"preference={value}",
                    key="preference",
                    value=value,
                    confidence=0.7,
                )
            )

        task_match = re.search(r"\b(?:todo:|i need to|remind me to)\s+(.+)$", lowered, re.I)
        if task_match:
            task_text = task_match.group(1).strip(" .,!?:;")
            tasks.append(
                ExtractionCandidate(
                    kind="task",
                    text=task_text,
                    key=None,
                    value=task_text,
                    confidence=0.7,
                )
            )

        return ExtractionResult(facts=facts, preferences=preferences, tasks=tasks)

    def _apply_extraction(
        self,
        user_id: str,
        agent_id: str | None,
        session_id: str | None,
        source_role: str,
        source_text: str,
        extracted: ExtractionResult,
    ) -> None:
        payload = extracted.model_dump()
        if any(payload.values()):
            self._database.add_extraction_record(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                source_role=source_role,
                source_text=source_text,
                extracted_json=payload,
            )

        for fact in extracted.facts:
            if not fact.value:
                continue
            self.semantic.add(
                user_id=user_id,
                text=fact.text,
                metadata={
                    "agent_id": agent_id,
                    "source_role": source_role,
                },
                kind="fact",
                confidence=fact.confidence,
                importance=0.7,
                fingerprint=self._fingerprint(fact.text),
            )

        for pref in extracted.preferences:
            if not pref.key or not pref.value:
                continue
            self.set_user_preference(user_id=user_id, key=pref.key, value=pref.value)

        if self.working_memory is not None and session_id:
            for index, task in enumerate(extracted.tasks):
                if not task.value:
                    continue
                self.working_memory.put(
                    user_id=user_id,
                    session_id=session_id,
                    key=f"task_{index}",
                    value=task.value,
                    kind="task_hint",
                    confidence=task.confidence,
                    importance=0.8,
                )

    @staticmethod
    def _fingerprint(text: str) -> str:
        return hashlib.sha1(text.strip().lower().encode("utf-8")).hexdigest()
