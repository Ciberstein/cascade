def split_into_chunks(total_size: int, num_chunks: int) -> list[tuple[int, int]]:
    """Split [0, total_size) into up to num_chunks inclusive (start, end) byte ranges.

    Returns an empty list for non-positive total_size, so callers never receive
    an invalid range (e.g. a 0-byte file should skip range requests entirely).
    """
    if total_size <= 0:
        return []

    num_chunks = max(1, min(num_chunks, total_size))
    base_size = total_size // num_chunks
    remainder = total_size % num_chunks

    ranges: list[tuple[int, int]] = []
    start = 0
    for i in range(num_chunks):
        size = base_size + (remainder if i == num_chunks - 1 else 0)
        end = start + size - 1
        ranges.append((start, end))
        start = end + 1
    return ranges
