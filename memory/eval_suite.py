from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from memory.episodic_memory import EpisodicMemory
from memory.memory_manager import MemoryManager
from memory.semantic_memory import SemanticMemory
from memory.user_memory import UserMemory
from memory.working_memory import WorkingMemory
from storage.database import Database
from storage.vector_store import VectorStore

CaseFn = Callable[[MemoryManager], tuple[bool, float, dict[str, Any]]]


class MemoryQualityEvaluator:
    def __init__(
        self,
        *,
        profile_decay_enabled: bool = True,
        profile_decay_half_life_days: float = 45.0,
        profile_decay_floor: float = 0.35,
        profile_decay_min_delta: float = 0.05,
    ) -> None:
        self.profile_decay_enabled = bool(profile_decay_enabled)
        self.profile_decay_half_life_days = max(1.0, float(profile_decay_half_life_days))
        self.profile_decay_floor = max(0.0, min(1.0, float(profile_decay_floor)))
        self.profile_decay_min_delta = max(0.0, float(profile_decay_min_delta))

    def run(self, suite: str = "core") -> dict[str, Any]:
        suite_name = (suite or "core").strip().lower() or "core"
        if suite_name not in {"core", "extended"}:
            raise ValueError(f"Unsupported memory eval suite: {suite_name}")

        core_cases: list[tuple[str, str, CaseFn]] = [
            (
                "profile_decay_overwrite",
                "Stale profile preference can be replaced when effective confidence decays.",
                self._case_profile_decay_overwrite,
            ),
            (
                "semantic_consolidation_strength",
                "Consolidation removes redundant same-value facts and keeps strongest winner.",
                self._case_semantic_consolidation_strength,
            ),
            (
                "retrieval_ranking_quality",
                "Retrieval scoring prioritizes high-confidence/high-importance candidate.",
                self._case_retrieval_ranking_quality,
            ),
            (
                "extraction_coverage",
                "Extraction captures facts, preferences, and task hints in one turn.",
                self._case_extraction_coverage,
            ),
        ]

        extended_only: list[tuple[str, str, CaseFn]] = [
            (
                "conflict_audit_coverage",
                "Conflict audit records are produced for conflicting profile updates.",
                self._case_conflict_audit_coverage,
            )
        ]

        case_specs = list(core_cases)
        if suite_name == "extended":
            case_specs.extend(extended_only)

        results: list[dict[str, Any]] = []
        passed = 0
        score_total = 0.0

        for case_id, description, fn in case_specs:
            case_result = self._run_case(case_id=case_id, description=description, fn=fn)
            results.append(case_result)
            if bool(case_result.get("passed", False)):
                passed += 1
            score_total += float(case_result.get("score", 0.0))

        total = len(results)
        failed = max(0, total - passed)
        pass_rate = (passed / total) if total else 0.0
        average_score = (score_total / total) if total else 0.0

        return {
            "suite": suite_name,
            "total_cases": total,
            "passed_cases": passed,
            "failed_cases": failed,
            "pass_rate": round(pass_rate, 6),
            "average_score": round(average_score, 6),
            "cases": results,
        }

    def _run_case(self, *, case_id: str, description: str, fn: CaseFn) -> dict[str, Any]:
        tmp = tempfile.TemporaryDirectory(prefix="amaryllis-memory-eval-")
        base = Path(tmp.name)
        database = Database(base / "state.db")
        vector_store = VectorStore(base / "vectors.faiss")

        manager = MemoryManager(
            episodic=EpisodicMemory(database),
            semantic=SemanticMemory(database, vector_store),
            user_memory=UserMemory(database),
            working_memory=WorkingMemory(database),
            telemetry=None,
            profile_decay_enabled=self.profile_decay_enabled,
            profile_decay_half_life_days=self.profile_decay_half_life_days,
            profile_decay_floor=self.profile_decay_floor,
            profile_decay_min_delta=self.profile_decay_min_delta,
        )

        try:
            passed, score, details = fn(manager)
            normalized_score = max(0.0, min(1.0, float(score)))
            return {
                "id": case_id,
                "description": description,
                "passed": bool(passed),
                "score": round(normalized_score, 6),
                "details": details,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "id": case_id,
                "description": description,
                "passed": False,
                "score": 0.0,
                "details": {"error": str(exc)},
            }
        finally:
            database.close()
            tmp.cleanup()

    @staticmethod
    def _case_profile_decay_overwrite(manager: MemoryManager) -> tuple[bool, float, dict[str, Any]]:
        user_id = "eval-user"
        old_ts = (datetime.now(timezone.utc) - timedelta(days=220)).isoformat()
        manager.user_memory.set(
            user_id=user_id,
            key="language",
            value="english",
            confidence=0.95,
            importance=0.8,
            source="extraction:user",
            updated_at=old_ts,
        )

        decay_trace = manager.debug_profile_decay(user_id=user_id, limit=5)
        effective_before = float(decay_trace[0]["confidence_effective"]) if decay_trace else 0.95

        resolution = manager.set_user_preference(
            user_id=user_id,
            key="language",
            value="german",
            confidence=0.58,
            importance=0.8,
            source="extraction:user",
        )
        stored = manager.user_memory.get(user_id=user_id, key="language")

        passed = (
            effective_before < 0.58
            and resolution == "incoming_overwrites_previous"
            and isinstance(stored, dict)
            and str(stored.get("value", "")) == "german"
        )
        score = 1.0 if passed else 0.0
        return passed, score, {
            "effective_before": effective_before,
            "resolution": resolution,
            "stored_value": (stored or {}).get("value"),
        }

    @staticmethod
    def _case_semantic_consolidation_strength(manager: MemoryManager) -> tuple[bool, float, dict[str, Any]]:
        user_id = "eval-user"
        manager.semantic.add(
            user_id=user_id,
            text="timezone=UTC",
            metadata={"fact_key": "timezone", "fact_value": "UTC"},
            kind="fact",
            confidence=0.93,
            importance=0.9,
            fingerprint="tz-utc-1",
        )
        manager.semantic.add(
            user_id=user_id,
            text="timezone=UTC",
            metadata={"fact_key": "timezone", "fact_value": "UTC"},
            kind="fact",
            confidence=0.42,
            importance=0.4,
            fingerprint="tz-utc-2",
        )
        manager.semantic.add(
            user_id=user_id,
            text="timezone=CET",
            metadata={"fact_key": "timezone", "fact_value": "CET"},
            kind="fact",
            confidence=0.65,
            importance=0.6,
            fingerprint="tz-cet-1",
        )

        summary = manager.consolidate_user_memory(user_id=user_id)
        active = manager.semantic.database.list_semantic_entries(
            user_id=user_id,
            kind="fact",
            active_only=True,
            limit=20,
        )
        timezone_active = [
            item
            for item in active
            if str((item.get("metadata") or {}).get("fact_key", "")) == "timezone"
        ]
        winner_value = None
        if timezone_active:
            winner_value = str((timezone_active[0].get("metadata") or {}).get("fact_value"))

        passed = (
            len(timezone_active) == 1
            and winner_value == "UTC"
            and int(summary.get("semantic_redundant_value_deactivated", 0)) >= 1
            and int(summary.get("semantic_deactivated", 0)) >= 2
        )
        score = 1.0 if passed else 0.0
        return passed, score, {
            "active_timezone_count": len(timezone_active),
            "winner_value": winner_value,
            "semantic_deactivated": int(summary.get("semantic_deactivated", 0)),
            "semantic_redundant_value_deactivated": int(summary.get("semantic_redundant_value_deactivated", 0)),
        }

    @staticmethod
    def _case_retrieval_ranking_quality(manager: MemoryManager) -> tuple[bool, float, dict[str, Any]]:
        user_id = "eval-user"
        high_id = manager.semantic.add(
            user_id=user_id,
            text="project alpha deadline",
            metadata={"fact_key": "project", "fact_value": "alpha"},
            kind="fact",
            confidence=0.95,
            importance=0.95,
            fingerprint="project-alpha-high",
        )
        low_id = manager.semantic.add(
            user_id=user_id,
            text="project alpha deadline",
            metadata={"fact_key": "project", "fact_value": "alpha-low"},
            kind="fact",
            confidence=0.2,
            importance=0.2,
            fingerprint="project-alpha-low",
        )

        trace = manager.debug_retrieval(user_id=user_id, query="project alpha deadline", top_k=5)
        top_id = trace[0].get("semantic_id") if trace else None
        passed = bool(len(trace) >= 2 and int(top_id or -1) == int(high_id))
        score = 1.0 if passed else 0.0
        return passed, score, {
            "high_id": high_id,
            "low_id": low_id,
            "top_id": top_id,
            "trace_count": len(trace),
        }

    @staticmethod
    def _case_extraction_coverage(manager: MemoryManager) -> tuple[bool, float, dict[str, Any]]:
        user_id = "eval-user"
        extracted = manager.ingest_user_turn(
            user_id=user_id,
            agent_id="agent-eval",
            session_id="session-eval",
            content="My name is Alice. I prefer tea. Remind me to send report.",
        )
        context = manager.build_context(
            user_id=user_id,
            agent_id="agent-eval",
            session_id="session-eval",
            query="name preference task",
            semantic_top_k=6,
        )
        has_task_hint = any(item.kind == "task_hint" for item in context.working)
        has_profile = any(item.key == "preference" for item in context.profile)

        passed = (
            len(extracted.facts) >= 1
            and len(extracted.preferences) >= 1
            and len(extracted.tasks) >= 1
            and has_task_hint
            and has_profile
        )
        score = 1.0 if passed else 0.0
        return passed, score, {
            "facts": len(extracted.facts),
            "preferences": len(extracted.preferences),
            "tasks": len(extracted.tasks),
            "working_count": len(context.working),
            "profile_count": len(context.profile),
            "has_task_hint": has_task_hint,
            "has_profile": has_profile,
        }

    @staticmethod
    def _case_conflict_audit_coverage(manager: MemoryManager) -> tuple[bool, float, dict[str, Any]]:
        user_id = "eval-user"
        manager.set_user_preference(
            user_id=user_id,
            key="tone",
            value="formal",
            confidence=0.95,
            source="user_preference",
        )
        resolution = manager.set_user_preference(
            user_id=user_id,
            key="tone",
            value="casual",
            confidence=0.3,
            source="extraction:user",
        )
        conflicts = manager.list_conflicts(user_id=user_id, limit=20)
        has_conflict = any(
            item.get("layer") == "profile"
            and item.get("key") == "tone"
            and item.get("resolution") in {"kept_previous_higher_confidence", "incoming_overwrites_previous"}
            for item in conflicts
        )

        passed = bool(resolution in {"kept_previous_higher_confidence", "incoming_overwrites_previous"} and has_conflict)
        score = 1.0 if passed else 0.0
        return passed, score, {
            "resolution": resolution,
            "conflict_count": len(conflicts),
            "has_conflict": has_conflict,
        }
