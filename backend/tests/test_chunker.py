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


def test_split_zero_total_size_produces_sentinel_empty_range():
    # total_size=0 is a degenerate case: min(num_chunks, 0) -> 0, then max(1, 0) -> 1,
    # giving base_size = 0 // 1 = 0 and a single range (0, -1). This is NOT a valid
    # inclusive byte range (start > end) and must never be used to build an HTTP
    # Range header. Callers (the segmented downloader) must special-case
    # total_size == 0 and skip chunked range requests entirely (e.g. write an empty
    # file directly). This test pins down the current sentinel behavior so a future
    # change to this function doesn't silently alter it.
    ranges = split_into_chunks(total_size=0, num_chunks=4)
    assert ranges == [(0, -1)]
