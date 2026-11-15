"""Token accounting: provider payloads, turn persistence and the panel line."""

import pytest

from chinchilla.core.thread import Turn, Usage


def test_openai_payload_reports_cached_tokens():
    usage = Usage.from_payload(
        {
            "prompt_tokens": 1238,
            "completion_tokens": 13,
            "total_tokens": 1251,
            "prompt_tokens_details": {"cached_tokens": 1024},
        }
    )

    assert usage.input_tokens == 1238
    assert usage.output_tokens == 13
    assert usage.cached_tokens == 1024
    assert usage.cached_ratio == pytest.approx(1024 / 1238)
    assert usage.total_tokens == 1251


def test_openai_payload_without_details_falls_back_to_deepseek_field():
    usage = Usage.from_payload({"prompt_tokens": 900, "completion_tokens": 40, "prompt_cache_hit_tokens": 512})

    assert usage.cached_tokens == 512


def test_anthropic_payload_folds_cache_reads_and_writes_into_input():
    usage = Usage.from_payload(
        {
            "input_tokens": 120,
            "output_tokens": 45,
            "cache_read_input_tokens": 800,
            "cache_creation_input_tokens": 60,
        }
    )

    assert usage.input_tokens == 980
    assert usage.output_tokens == 45
    assert usage.cached_tokens == 800, "writes are not savings, reads are"


def test_empty_payloads_stay_empty():
    assert Usage.from_payload(None).is_empty
    assert Usage.from_payload({}).is_empty


def test_totals_add_the_rounds_of_one_reply():
    first = Usage.from_payload({"prompt_tokens": 100, "completion_tokens": 10})
    second = Usage.from_payload({"prompt_tokens": 300, "completion_tokens": 20})
    first.add(second)

    assert (first.input_tokens, first.output_tokens) == (400, 30)


def test_turn_round_trip_keeps_the_counters():
    turn = Turn(role="assistant", text="hi", usage=Usage(1200, 30, 900))

    restored = Turn.from_dict(turn.to_dict())

    assert restored.usage is not None
    assert restored.usage.cached_tokens == 900
    assert Turn.from_dict({"role": "assistant", "text": "old"}).usage is None


def test_total_ignores_turns_without_counters():
    turns = [
        Turn(role="user", text="a"),
        Turn(role="assistant", text="b", usage=Usage(10, 5, 0)),
        Turn(role="assistant", text="c", usage=Usage(20, 7, 10)),
    ]

    total = Usage.total(turns)

    assert (total.input_tokens, total.output_tokens, total.cached_tokens) == (30, 12, 10)
