from app.engine.chunker import split_into_chunks


def test_split_even():
    ranges = split_into_chunks(total_size=1000, num_chunks=4)
    assert ranges == [(0, 249), (250, 499), (500, 749), (750, 999)]


def test_split_uneven_remainder_goes_to_last_chunk():
    ranges = split_into_chunks(total_size=1001, num_chunks=4)
    assert ranges == [(0, 249), (250, 499), (500, 749), (750, 1000)]


def test_split_more_chunks_than_bytes_clamps_to_one_chunk_per_byte():
    ranges = split_into_chunks(total_size=3, num_chunks=8)
    assert ranges == [(0, 0), (1, 1), (2, 2)]


def test_split_single_chunk():
    ranges = split_into_chunks(total_size=500, num_chunks=1)
    assert ranges == [(0, 499)]


def test_split_zero_total_size_returns_empty_list():
    # total_size=0 has nothing to download: the function returns [] rather than a
    # degenerate range, so callers can use a plain `if not ranges:` check instead of
    # needing to know about an invalid-looking sentinel tuple.
    ranges = split_into_chunks(total_size=0, num_chunks=4)
    assert ranges == []
