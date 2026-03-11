from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SUPPORTED_ROUTE_MODES: tuple[str, ...] = (
    "balanced",
    "local_first",
    "quality_first",
    "coding",
    "reasoning",
)


@dataclass(frozen=True)
class RoutingConstraints:
    mode: str = "balanced"
    require_stream: bool = True
    require_tools: bool = False
    prefer_local: bool | None = None
    min_params_b: float | None = None
    max_params_b: float | None = None


@dataclass(frozen=True)
class ModelCandidate:
    provider: str
    model: str
    local: bool
    installed: bool
    active: bool
    supports_stream: bool
    supports_tools: bool
    requires_api_key: bool
    estimated_params_b: float | None
    quality_tier: str
    speed_tier: str
    tags: tuple[str, ...]
    source: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "local": self.local,
            "installed": self.installed,
            "active": self.active,
            "supports_stream": self.supports_stream,
            "supports_tools": self.supports_tools,
            "requires_api_key": self.requires_api_key,
            "estimated_params_b": self.estimated_params_b,
            "quality_tier": self.quality_tier,
            "speed_tier": self.speed_tier,
            "tags": list(self.tags),
            "source": self.source,
            "metadata": self.metadata,
        }


def normalize_route_mode(value: str | None) -> str:
    mode = (value or "balanced").strip().lower()
    if mode not in SUPPORTED_ROUTE_MODES:
        return "balanced"
    return mode


def estimate_model_size_b(model_id: str) -> float | None:
    text = model_id.lower()
    mix = re.search(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)b", text)
    if mix:
        try:
            experts = float(mix.group(1))
            per_expert = float(mix.group(2))
            return round(experts * per_expert, 4)
        except Exception:
            return None

    billions = re.search(r"(\d+(?:\.\d+)?)\s*b\b", text)
    if billions:
        try:
            return round(float(billions.group(1)), 4)
        except Exception:
            return None

    millions = re.search(r"(\d+(?:\.\d+)?)\s*m\b", text)
    if millions:
        try:
            return round(float(millions.group(1)) / 1000.0, 4)
        except Exception:
            return None

    return None


def infer_model_tags(model_id: str) -> tuple[str, ...]:
    text = model_id.lower()
    tags: list[str] = []

    coding_tokens = ("coder", "code", "codellama", "starcoder", "deepseek-coder")
    reasoning_tokens = ("r1", "qwq", "reason", "o1", "o3", "sonnet", "claude")
    vision_tokens = ("vision", "vl", "gpt-4o", "omni", "image")
    small_tokens = ("tiny", "mini", "1b", "1.5b", "2b", "3b", "4b")
    fast_tokens = ("haiku", "mini", "flash")

    if any(token in text for token in coding_tokens):
        tags.append("coding")
    if any(token in text for token in reasoning_tokens):
        tags.append("reasoning")
    if any(token in text for token in vision_tokens):
        tags.append("vision")
    if "instruct" in text or "chat" in text:
        tags.append("instruction")
    if "4bit" in text or "q4" in text:
        tags.append("quantized")
    if any(token in text for token in small_tokens):
        tags.append("compact")
    if any(token in text for token in fast_tokens):
        tags.append("fast_hint")

    if "coding" not in tags and "reasoning" not in tags and "vision" not in tags:
        tags.append("general")

    return tuple(dict.fromkeys(tags))


def quality_tier_for_model(model_id: str, estimated_params_b: float | None) -> str:
    text = model_id.lower()
    if any(token in text for token in ("gpt-5", "gpt-4.1", "claude-3-7", "claude-3-5-sonnet", "gemini-2.5")):
        return "high"
    if estimated_params_b is None:
        if "mini" in text or "haiku" in text:
            return "compact"
        return "medium"
    if estimated_params_b >= 32:
        return "high"
    if estimated_params_b >= 8:
        return "medium"
    return "compact"


def speed_tier_for_model(local: bool, estimated_params_b: float | None, tags: tuple[str, ...]) -> str:
    if "fast_hint" in tags:
        return "fast"
    if estimated_params_b is None:
        return "medium"
    if local and estimated_params_b >= 30:
        return "slow"
    if estimated_params_b <= 3:
        return "fast"
    if estimated_params_b >= 40:
        return "slow"
    return "medium"


def score_candidate(candidate: ModelCandidate, constraints: RoutingConstraints) -> float | None:
    if constraints.require_stream and not candidate.supports_stream:
        return None
    if constraints.require_tools and not candidate.supports_tools:
        return None
    if constraints.min_params_b is not None and candidate.estimated_params_b is not None:
        if candidate.estimated_params_b < constraints.min_params_b:
            return None
    if constraints.max_params_b is not None and candidate.estimated_params_b is not None:
        if candidate.estimated_params_b > constraints.max_params_b:
            return None

    quality_score_map = {"compact": 0.7, "medium": 1.3, "high": 2.0}
    speed_score_map = {"fast": 1.8, "medium": 1.2, "slow": 0.6}

    score = 0.0
    score += quality_score_map.get(candidate.quality_tier, 1.0)
    score += speed_score_map.get(candidate.speed_tier, 1.0)
    score += 0.7 if candidate.active else 0.0
    score += 0.5 if candidate.installed else 0.0

    if constraints.prefer_local is True:
        score += 2.0 if candidate.local else -1.0
    elif constraints.prefer_local is False:
        score += 1.0 if not candidate.local else -0.3

    if constraints.mode == "local_first":
        score += 3.0 if candidate.local else -2.0
        score += 0.8 if candidate.installed else 0.0
    elif constraints.mode == "quality_first":
        score += 2.2 if candidate.quality_tier == "high" else (1.2 if candidate.quality_tier == "medium" else 0.2)
    elif constraints.mode == "coding":
        score += 2.5 if "coding" in candidate.tags else -0.7
    elif constraints.mode == "reasoning":
        score += 2.5 if "reasoning" in candidate.tags else -0.7

    if candidate.requires_api_key and candidate.source == "suggested":
        score -= 0.5
    if "vision" in candidate.tags:
        score -= 0.1

    return round(score, 6)

