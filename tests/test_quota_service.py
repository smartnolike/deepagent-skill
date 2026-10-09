"""Quota usage normalization and pricing tests."""

from types import SimpleNamespace

from services.quota_service import _cost_micro_usd, normalize_usage


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
    assert usage.cache_write_tokens == 0
    assert usage.output_tokens == 8


def test_normalize_usage_keeps_chat_openai_cache_write_separate_from_cache_read() -> None:
    usage = normalize_usage(
        {
            "input_tokens": 84_863,
            "output_tokens": 1_593,
            "input_token_details": {"cache_read": 59_976, "cache_creation": 24_866},
            "output_token_details": {"reasoning": 264},
        }
    )

    assert usage.input_tokens == 84_863
    assert usage.cached_input_tokens == 59_976
    assert usage.cache_write_tokens == 24_866
    # ChatOpenAI output_tokens already includes its output_token_details.reasoning count.
    assert usage.output_tokens == 1_593


def test_cost_uses_a_separate_openai_cache_write_rate() -> None:
    pricing = SimpleNamespace(
        input_micro_usd_per_mtok=220_000,
        cached_input_micro_usd_per_mtok=30_000,
        cache_write_micro_usd_per_mtok=275_000,
        output_micro_usd_per_mtok=1_320_000,
    )

    cost = _cost_micro_usd(84_863, 59_976, 24_866, 1_593, pricing)

    # 21 normal-input, 59,976 cache-read, and 24,866 cache-write tokens.
    assert cost == 10_745
