from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from memory.episodic_memory import EpisodicMemory
from memory.extraction_service import ExtractionService
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


class TelemetrySink(Protocol):
    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        ...


class MemoryManager:
    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        user_memory: UserMemory,
        working_memory: WorkingMemory | None = None,
        telemetry: TelemetrySink | None = None,
        extraction_service: ExtractionService | None = None,
        profile_decay_enabled: bool = True,
        profile_decay_half_life_days: float = 45.0,
        profile_decay_floor: float = 0.35,
        profile_decay_min_delta: float = 0.05,
    ) -> None:
        self.logger = logging.getLogger("amaryllis.memory.manager")
        self.episodic = episodic
        self.semantic = semantic
        self.user_memory = user_memory
        self.working_memory = working_memory
        self.telemetry = telemetry
        self.extraction_service = extraction_service or ExtractionService()
        self.profile_decay_enabled = bool(profile_decay_enabled)
        self.profile_decay_half_life_days = max(1.0, float(profile_decay_half_life_days))
        self.profile_decay_floor = max(0.0, min(1.0, float(profile_decay_floor)))
        self.profile_decay_min_delta = max(0.0, float(profile_decay_min_delta))

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
                    vector_score=float(item.get("vector_score")) if item.get("vector_score") is not None else None,
                    recency_score=float(item.get("recency_score")) if item.get("recency_score") is not None else None,
                    metadata=metadata if isinstance(metadata, dict) else {},
                    kind=str(item.get("kind", (metadata or {}).get("kind", "fact"))),
                    confidence=float(item.get("confidence", (metadata or {}).get("confidence", 0.8))),
                    importance=float(item.get("importance", (metadata or {}).get("importance", 0.5))),
                )
            )

        profile: list[ProfileMemoryItem] = []
        profile_decayed_count = 0
        for item in profile_raw:
            projected, decayed = self._profile_item_with_decay(item)
            if decayed:
                profile_decayed_count += 1
            profile.append(ProfileMemoryItem(**projected))

        context = MemoryContext(
            working=working,
            episodic=episodic,
            semantic=semantic,
            profile=profile,
        )
        self._emit(
            "memory_retrieval",
            {
                "user_id": user_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "working_count": len(context.working),
                "episodic_count": len(context.episodic),
                "semantic_count": len(context.semantic),
                "profile_count": len(context.profile),
                "profile_decayed_count": profile_decayed_count,
                "top_semantic_scores": [round(item.score, 4) for item in context.semantic[:3]],
            },
        )
        return context

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

    def set_user_preference(
        self,
        user_id: str,
        key: str,
        value: str,
        confidence: float = 0.9,
        importance: float = 0.8,
        source: str = "user_preference",
    ) -> str:
        previous = self.user_memory.get(user_id=user_id, key=key)
        if not previous:
            self.user_memory.set(
                user_id=user_id,
                key=key,
                value=value,
                confidence=confidence,
                importance=importance,
                source=source,
            )
            return "created"

        previous_value = str(previous.get("value", ""))
        previous_confidence = float(previous.get("confidence", 0.5))
        previous_effective_confidence, _, _ = self._profile_decay_metrics(
            confidence=previous_confidence,
            updated_at=previous.get("updated_at"),
            source=previous.get("source"),
        )
        if previous_value == value:
            # Refresh confidence/importance when reinforcement is stronger than effective confidence.
            if confidence > previous_effective_confidence + 0.01:
                self.user_memory.set(
                    user_id=user_id,
                    key=key,
                    value=value,
                    confidence=max(confidence, previous_confidence),
                    importance=importance,
                    source=source,
                )
            return "same_value"

        if confidence + 0.05 < previous_effective_confidence:
            resolution = "kept_previous_higher_confidence"
            self._record_conflict(
                user_id=user_id,
                layer="profile",
                key=key,
                previous_value=previous_value,
                incoming_value=value,
                resolution=resolution,
                confidence_prev=previous_effective_confidence,
                confidence_new=confidence,
            )
            return resolution

        self.user_memory.set(
            user_id=user_id,
            key=key,
            value=value,
            confidence=confidence,
            importance=importance,
            source=source,
        )
        resolution = "incoming_overwrites_previous"
        self._record_conflict(
            user_id=user_id,
            layer="profile",
            key=key,
            previous_value=previous_value,
            incoming_value=value,
            resolution=resolution,
            confidence_prev=previous_effective_confidence,
            confidence_new=confidence,
        )
        return resolution

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

    def debug_profile_decay(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        limit_value = max(1, min(int(limit), 500))
        items = self.user_memory.items(user_id=user_id)[:limit_value]
        result: list[dict[str, Any]] = []
        for item in items:
            raw_confidence = float(item.get("confidence", 0.0))
            effective_confidence, decay_factor, age_days = self._profile_decay_metrics(
                confidence=raw_confidence,
                updated_at=item.get("updated_at"),
                source=item.get("source"),
            )
            result.append(
                {
                    "key": str(item.get("key", "")),
                    "value": str(item.get("value", "")),
                    "source": item.get("source"),
                    "updated_at": item.get("updated_at"),
                    "confidence_raw": raw_confidence,
                    "confidence_effective": effective_confidence,
                    "confidence_decay_factor": decay_factor,
                    "age_days": age_days,
                    "decayed": (raw_confidence - effective_confidence) >= self.profile_decay_min_delta,
                }
            )
        return result

    def consolidate_user_memory(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        semantic_limit: int = 1000,
    ) -> dict[str, Any]:
        limit = max(10, min(int(semantic_limit), 5000))
        semantic_items = self._database.list_semantic_entries(
            user_id=user_id,
            kind="fact",
            active_only=True,
            limit=limit,
        )

        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in semantic_items:
            key = self._semantic_group_key(item)
            grouped.setdefault(key, []).append(item)

        semantic_deactivated = 0
        groups_with_duplicates = 0
        conflicts_recorded = 0
        semantic_redundant_value_deactivated = 0

        for group_key, items in grouped.items():
            if len(items) <= 1:
                continue
            groups_with_duplicates += 1
            value_groups: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                value_groups.setdefault(self._semantic_value_key(item), []).append(item)

            value_winners: list[dict[str, Any]] = []
            for value_items in value_groups.values():
                ranked_value = sorted(value_items, key=self._semantic_rank_key, reverse=True)
                winner_value_entry = ranked_value[0]
                value_winners.append(winner_value_entry)
                winner_id = int(winner_value_entry.get("id", 0))
                winner_value = self._fact_value_from_entry(winner_value_entry)
                winner_confidence = float(winner_value_entry.get("confidence", 0.0))

                for redundant in ranked_value[1:]:
                    redundant_id = int(redundant.get("id", 0))
                    if redundant_id <= 0 or redundant_id == winner_id:
                        continue
                    redundant_value = self._fact_value_from_entry(redundant)
                    redundant_confidence = float(redundant.get("confidence", 0.0))
                    self._database.deactivate_semantic_entry(
                        semantic_id=redundant_id,
                        superseded_by=winner_id if winner_id > 0 else None,
                    )
                    semantic_deactivated += 1
                    semantic_redundant_value_deactivated += 1
                    conflicts_recorded += 1
                    self._record_conflict(
                        user_id=user_id,
                        layer="semantic",
                        key=group_key,
                        previous_value=redundant_value,
                        incoming_value=winner_value,
                        resolution="consolidated_redundant_value",
                        confidence_prev=redundant_confidence,
                        confidence_new=winner_confidence,
                    )

            ranked_group = sorted(value_winners, key=self._semantic_rank_key, reverse=True)
            winner = ranked_group[0]
            winner_id = int(winner.get("id", 0))
            winner_value = self._fact_value_from_entry(winner)
            winner_confidence = float(winner.get("confidence", 0.0))

            for loser in ranked_group[1:]:
                loser_id = int(loser.get("id", 0))
                if loser_id <= 0 or loser_id == winner_id:
                    continue
                loser_value = self._fact_value_from_entry(loser)
                loser_confidence = float(loser.get("confidence", 0.0))
                self._database.deactivate_semantic_entry(
                    semantic_id=loser_id,
                    superseded_by=winner_id if winner_id > 0 else None,
                )
                semantic_deactivated += 1
                conflicts_recorded += 1
                self._record_conflict(
                    user_id=user_id,
                    layer="semantic",
                    key=group_key,
                    previous_value=loser_value,
                    incoming_value=winner_value,
                    resolution="consolidated_duplicate",
                    confidence_prev=loser_confidence,
                    confidence_new=winner_confidence,
                )

        working_items: list[dict[str, Any]] = []
        if self.working_memory is not None and session_id:
            working_items = self.working_memory.list(
                user_id=user_id,
                session_id=session_id,
                limit=128,
            )

        profile_items = self.user_memory.items(user_id=user_id)
        profile_decay_candidates = 0
        profile_decay_delta_total = 0.0
        for item in profile_items:
            raw_confidence = float(item.get("confidence", 0.0))
            effective_confidence, _, _ = self._profile_decay_metrics(
                confidence=raw_confidence,
                updated_at=item.get("updated_at"),
                source=item.get("source"),
            )
            delta = max(0.0, raw_confidence - effective_confidence)
            if delta >= self.profile_decay_min_delta:
                profile_decay_candidates += 1
                profile_decay_delta_total += delta
        profile_decay_avg_delta = (
            round(profile_decay_delta_total / profile_decay_candidates, 6)
            if profile_decay_candidates > 0
            else 0.0
        )

        summary = {
            "user_id": user_id,
            "session_id": session_id,
            "consolidated_at": datetime.now(timezone.utc).isoformat(),
            "semantic_scanned": len(semantic_items),
            "semantic_groups": len(grouped),
            "semantic_groups_with_duplicates": groups_with_duplicates,
            "semantic_deactivated": semantic_deactivated,
            "semantic_redundant_value_deactivated": semantic_redundant_value_deactivated,
            "working_items_scanned": len(working_items),
            "profile_items_scanned": len(profile_items),
            "profile_decay_candidates": profile_decay_candidates,
            "profile_decay_avg_delta": profile_decay_avg_delta,
            "conflicts_recorded": conflicts_recorded,
        }
        self._emit(
            "memory_consolidate",
            {
                "user_id": user_id,
                "session_id": session_id,
                "semantic_scanned": len(semantic_items),
                "semantic_deactivated": semantic_deactivated,
                "semantic_redundant_value_deactivated": semantic_redundant_value_deactivated,
                "profile_items_scanned": len(profile_items),
                "profile_decay_candidates": profile_decay_candidates,
                "conflicts_recorded": conflicts_recorded,
            },
        )
        return summary

    def debug_retrieval(self, user_id: str, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        matches = self.semantic.search(user_id=user_id, query=query, top_k=top_k)
        result: list[dict[str, Any]] = []
        for index, item in enumerate(matches, start=1):
            metadata = item.get("metadata", {})
            metadata_obj = metadata if isinstance(metadata, dict) else {}
            result.append(
                {
                    "rank": index,
                    "semantic_id": item.get("semantic_id"),
                    "kind": str(item.get("kind", metadata_obj.get("kind", "fact"))),
                    "text": str(item.get("text", "")),
                    "score": float(item.get("score", 0.0)),
                    "vector_score": float(item.get("vector_score", 0.0)),
                    "recency_score": float(item.get("recency_score", 0.0)),
                    "confidence": float(item.get("confidence", metadata_obj.get("confidence", 0.8))),
                    "importance": float(item.get("importance", metadata_obj.get("importance", 0.5))),
                    "created_at": item.get("created_at"),
                    "metadata": metadata_obj,
                }
            )

        self._emit(
            "memory_retrieval_debug",
            {
                "user_id": user_id,
                "query": query,
                "top_k": top_k,
                "result_count": len(result),
            },
        )
        return result

    def extract_from_text(self, text: str) -> ExtractionResult:
        return self.extraction_service.extract(text)

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
            self._emit(
                "memory_extract",
                {
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "source_role": source_role,
                    "facts": len(extracted.facts),
                    "preferences": len(extracted.preferences),
                    "tasks": len(extracted.tasks),
                },
            )

        for fact in extracted.facts:
            if not fact.value:
                continue
            self._upsert_fact_candidate(
                user_id=user_id,
                agent_id=agent_id,
                source_role=source_role,
                fact=fact,
            )

        for pref in extracted.preferences:
            if not pref.key or not pref.value:
                continue
            self.set_user_preference(
                user_id=user_id,
                key=pref.key,
                value=pref.value,
                confidence=pref.confidence,
                importance=0.8,
                source=f"extraction:{source_role}",
            )

        if self.working_memory is not None and session_id:
            for index, task in enumerate(extracted.tasks):
                if not task.value:
                    continue
                self.working_memory.put(
                    user_id=user_id,
                    session_id=session_id,
                    key=f"task_{index}_{self._fingerprint(task.value)[:10]}",
                    value=task.value,
                    kind="task_hint",
                    confidence=task.confidence,
                    importance=0.8,
                )

    def _upsert_fact_candidate(
        self,
        user_id: str,
        agent_id: str | None,
        source_role: str,
        fact: ExtractionCandidate,
    ) -> int | None:
        metadata = {
            "agent_id": agent_id,
            "source_role": source_role,
            "fact_key": fact.key,
            "fact_value": fact.value,
        }

        previous_entry = None
        if fact.key:
            previous_entry = self._latest_fact_by_key(user_id=user_id, fact_key=fact.key)

        if previous_entry:
            previous_value = self._fact_value_from_entry(previous_entry)
            previous_confidence = float(previous_entry.get("confidence", 0.5))
            new_confidence = float(fact.confidence)

            if previous_value == fact.value:
                if new_confidence <= previous_confidence:
                    return int(previous_entry.get("id"))
                semantic_id = self.semantic.add(
                    user_id=user_id,
                    text=fact.text,
                    metadata={**metadata, "supersedes": previous_entry.get("id")},
                    kind="fact",
                    confidence=new_confidence,
                    importance=0.7,
                    fingerprint=self._fingerprint(fact.text),
                )
                self._database.deactivate_semantic_entry(
                    semantic_id=int(previous_entry["id"]),
                    superseded_by=semantic_id,
                )
                return semantic_id

            if new_confidence + 0.05 < previous_confidence:
                self._record_conflict(
                    user_id=user_id,
                    layer="semantic",
                    key=fact.key,
                    previous_value=previous_value,
                    incoming_value=fact.value,
                    resolution="kept_previous_higher_confidence",
                    confidence_prev=previous_confidence,
                    confidence_new=new_confidence,
                )
                return int(previous_entry.get("id"))

            semantic_id = self.semantic.add(
                user_id=user_id,
                text=fact.text,
                metadata={**metadata, "supersedes": previous_entry.get("id")},
                kind="fact",
                confidence=new_confidence,
                importance=0.7,
                fingerprint=self._fingerprint(fact.text),
            )
            self._database.deactivate_semantic_entry(
                semantic_id=int(previous_entry["id"]),
                superseded_by=semantic_id,
            )
            self._record_conflict(
                user_id=user_id,
                layer="semantic",
                key=fact.key,
                previous_value=previous_value,
                incoming_value=fact.value,
                resolution="incoming_overwrites_previous",
                confidence_prev=previous_confidence,
                confidence_new=new_confidence,
            )
            return semantic_id

        return self.semantic.add(
            user_id=user_id,
            text=fact.text,
            metadata=metadata,
            kind="fact",
            confidence=fact.confidence,
            importance=0.7,
            fingerprint=self._fingerprint(fact.text),
        )

    def _latest_fact_by_key(self, user_id: str, fact_key: str) -> dict[str, Any] | None:
        items = self._database.list_semantic_entries(
            user_id=user_id,
            kind="fact",
            active_only=True,
            limit=200,
        )
        for item in items:
            metadata = item.get("metadata", {})
            if isinstance(metadata, dict) and str(metadata.get("fact_key", "")) == fact_key:
                return item
        return None

    @staticmethod
    def _fact_value_from_entry(entry: dict[str, Any]) -> str | None:
        metadata = entry.get("metadata", {})
        if isinstance(metadata, dict) and metadata.get("fact_value") is not None:
            return str(metadata["fact_value"])
        text = str(entry.get("text", ""))
        if "=" in text:
            return text.split("=", 1)[1].strip()
        return text if text else None

    def _semantic_group_key(self, entry: dict[str, Any]) -> str:
        metadata = entry.get("metadata", {})
        if isinstance(metadata, dict):
            fact_key = str(metadata.get("fact_key", "")).strip().lower()
            if fact_key:
                return f"fact:{fact_key}"
            fingerprint = str(metadata.get("fingerprint", "")).strip().lower()
            if fingerprint:
                return f"fp:{fingerprint}"
        text = str(entry.get("text", "")).strip().lower()
        if text:
            return f"text:{text[:120]}"
        return f"id:{entry.get('id')}"

    @staticmethod
    def _semantic_value_key(entry: dict[str, Any]) -> str:
        metadata = entry.get("metadata", {})
        if isinstance(metadata, dict):
            fact_value = metadata.get("fact_value")
            if fact_value is not None:
                return f"value:{str(fact_value).strip().lower()}"
        text = str(entry.get("text", "")).strip().lower()
        return f"text:{text[:160]}"

    @staticmethod
    def _semantic_rank_key(entry: dict[str, Any]) -> tuple[float, float, float, str, int]:
        confidence = float(entry.get("confidence", 0.0))
        importance = float(entry.get("importance", 0.0))
        created_at = str(entry.get("created_at", ""))
        recency = MemoryManager._semantic_recency_score(created_at)
        score = 0.55 * confidence + 0.25 * importance + 0.20 * recency
        entry_id = int(entry.get("id", 0))
        return score, confidence, importance, created_at, entry_id

    @staticmethod
    def _semantic_recency_score(created_at: str) -> float:
        timestamp = MemoryManager._parse_iso_datetime(created_at)
        if timestamp is None:
            return 0.5
        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() / 86400.0,
        )
        return 1.0 / (1.0 + (age_days / 7.0))

    def _profile_item_with_decay(self, item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        key = str(item.get("key", ""))
        value = str(item.get("value", ""))
        updated_at = str(item.get("updated_at", ""))
        confidence_raw = float(item.get("confidence", 0.0))
        importance = float(item.get("importance", 0.0))
        source = item.get("source")
        effective_confidence, decay_factor, age_days = self._profile_decay_metrics(
            confidence=confidence_raw,
            updated_at=updated_at,
            source=source,
        )
        decayed = (confidence_raw - effective_confidence) >= self.profile_decay_min_delta
        payload = {
            "key": key,
            "value": value,
            "updated_at": updated_at,
            "confidence": effective_confidence,
            "confidence_base": confidence_raw,
            "confidence_decay_factor": decay_factor,
            "confidence_age_days": age_days,
            "importance": importance,
            "source": source,
        }
        return payload, decayed

    def _profile_decay_metrics(
        self,
        *,
        confidence: float,
        updated_at: Any,
        source: Any,
    ) -> tuple[float, float, float]:
        base = max(0.0, min(1.0, float(confidence)))
        if not self.profile_decay_enabled:
            return base, 1.0, 0.0

        timestamp = self._parse_iso_datetime(updated_at)
        if timestamp is None:
            return base, 1.0, 0.0

        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() / 86400.0,
        )
        normalized_source = str(source or "").strip().lower()
        sensitivity = 1.0
        if normalized_source.startswith("extraction:"):
            sensitivity = 1.35
        elif "user_preference" in normalized_source or "manual" in normalized_source:
            sensitivity = 0.6
        elif normalized_source.startswith("system:"):
            sensitivity = 0.85

        effective_half_life = max(1.0, self.profile_decay_half_life_days / sensitivity)
        decay_factor = 0.5 ** (age_days / effective_half_life)
        floor_value = min(base, self.profile_decay_floor)
        effective = max(floor_value, base * decay_factor)
        return max(0.0, min(1.0, effective)), max(0.0, min(1.0, decay_factor)), age_days

    @staticmethod
    def _parse_iso_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip()
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _record_conflict(
        self,
        user_id: str,
        layer: str,
        key: str,
        previous_value: str | None,
        incoming_value: str | None,
        resolution: str,
        confidence_prev: float | None,
        confidence_new: float | None,
    ) -> None:
        self._database.add_conflict_record(
            user_id=user_id,
            layer=layer,
            key=key,
            previous_value=previous_value,
            incoming_value=incoming_value,
            resolution=resolution,
            confidence_prev=confidence_prev,
            confidence_new=confidence_new,
        )
        self._emit(
            "memory_conflict",
            {
                "user_id": user_id,
                "layer": layer,
                "key": key,
                "resolution": resolution,
                "confidence_prev": confidence_prev,
                "confidence_new": confidence_new,
            },
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.telemetry is None:
            return
        try:
            self.telemetry.emit(event_type=event_type, payload=payload)
        except Exception as exc:
            self.logger.debug("memory_telemetry_failed event=%s error=%s", event_type, exc)

    @staticmethod
    def _fingerprint(text: str) -> str:
        return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()
