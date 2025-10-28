from backend.services.token_chunk import rough_token_count, split_by_token_limit


def test_split_by_token_limit_splits_large_single_block() -> None:
    limit = 120
    # Each token is approx 4 chars. Create a block ~10x the limit.
    block = "a" * (limit * 4 * 3 + 10)

    parts = split_by_token_limit([block], limit)

    # The joined content should match the original aside from inserted newlines.
    combined = "".join(part.replace("\n", "") for part in parts)
    assert combined == block

    for part in parts:
        assert rough_token_count(part) <= limit


def test_split_by_token_limit_handles_mixed_blocks() -> None:
    limit = 50
    blocks = ["alpha", "beta" * 80, "gamma"]

    parts = split_by_token_limit(blocks, limit)

    assert len(parts) >= 2
    for part in parts:
        assert rough_token_count(part) <= limit


