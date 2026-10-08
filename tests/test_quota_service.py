"""Quota usage normalization tests."""

from services.quota_service import normalize_usage


def test_normalize_usage_includes_vertex_reasoning_tokens_and_caps_cached_input() -> None:
    usage = normalize_usage(
        {
            "input_tokens": 10,
            "output_tokens": 5,
            "thoughts_token_count": 3,
            "input_token_details": {"cache_read": 20},
        }
    )

    assert usage.input_tokens == 10
    assert usage.cached_input_tokens == 10
    assert usage.output_tokens == 8
