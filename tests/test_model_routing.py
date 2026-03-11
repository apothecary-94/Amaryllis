from __future__ import annotations

import unittest

from models.routing import (
    ModelCandidate,
    RoutingConstraints,
    estimate_model_size_b,
    infer_model_tags,
    normalize_route_mode,
    quality_tier_for_model,
    score_candidate,
    speed_tier_for_model,
)


def _candidate(
    *,
    provider: str,
    model: str,
    local: bool,
    installed: bool,
    active: bool = False,
) -> ModelCandidate:
    size = estimate_model_size_b(model)
    tags = infer_model_tags(model)
    return ModelCandidate(
        provider=provider,
        model=model,
        local=local,
        installed=installed,
        active=active,
        supports_stream=True,
        supports_tools=False,
        requires_api_key=not local,
        estimated_params_b=size,
        quality_tier=quality_tier_for_model(model, size),
        speed_tier=speed_tier_for_model(local, size, tags),
        tags=tags,
        source="listed",
        metadata={},
    )


class ModelRoutingTests(unittest.TestCase):
    def test_estimate_model_size(self) -> None:
        self.assertEqual(estimate_model_size_b("Qwen2.5-7B-Instruct"), 7.0)
        self.assertEqual(estimate_model_size_b("Mixtral-8x7B"), 56.0)
        self.assertEqual(estimate_model_size_b("Tiny-500M"), 0.5)
        self.assertIsNone(estimate_model_size_b("unknown-model"))

    def test_local_first_prefers_local_installed(self) -> None:
        local = _candidate(
            provider="mlx",
            model="mlx-community/Qwen2.5-7B-Instruct-4bit",
            local=True,
            installed=True,
        )
        cloud = _candidate(
            provider="openai",
            model="gpt-4.1-mini",
            local=False,
            installed=False,
        )
        constraints = RoutingConstraints(mode="local_first")
        local_score = score_candidate(local, constraints)
        cloud_score = score_candidate(cloud, constraints)
        self.assertIsNotNone(local_score)
        self.assertIsNotNone(cloud_score)
        assert local_score is not None
        assert cloud_score is not None
        self.assertGreater(local_score, cloud_score)

    def test_quality_first_prefers_high_tier(self) -> None:
        compact = _candidate(
            provider="mlx",
            model="mlx-community/Qwen2.5-1.5B-Instruct-4bit",
            local=True,
            installed=True,
        )
        high = _candidate(
            provider="openrouter",
            model="anthropic/claude-3.7-sonnet",
            local=False,
            installed=False,
        )
        constraints = RoutingConstraints(mode="quality_first", prefer_local=False)
        compact_score = score_candidate(compact, constraints)
        high_score = score_candidate(high, constraints)
        self.assertIsNotNone(compact_score)
        self.assertIsNotNone(high_score)
        assert compact_score is not None
        assert high_score is not None
        self.assertGreater(high_score, compact_score)

    def test_coding_mode_prefers_coder_models(self) -> None:
        coder = _candidate(
            provider="mlx",
            model="mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
            local=True,
            installed=True,
        )
        general = _candidate(
            provider="mlx",
            model="mlx-community/Qwen2.5-7B-Instruct-4bit",
            local=True,
            installed=True,
        )
        constraints = RoutingConstraints(mode="coding")
        coder_score = score_candidate(coder, constraints)
        general_score = score_candidate(general, constraints)
        self.assertIsNotNone(coder_score)
        self.assertIsNotNone(general_score)
        assert coder_score is not None
        assert general_score is not None
        self.assertGreater(coder_score, general_score)

    def test_normalize_route_mode(self) -> None:
        self.assertEqual(normalize_route_mode("quality_first"), "quality_first")
        self.assertEqual(normalize_route_mode("QUALITY_FIRST"), "quality_first")
        self.assertEqual(normalize_route_mode("unknown"), "balanced")


if __name__ == "__main__":
    unittest.main()
