import pytest
from processing_indexing.models import TranscriptSegment
from processing_indexing.windowing import generate_windows, transcript_for_window


@pytest.mark.parametrize(
    "duration,expected",
    [
        (3.5, [(0, 3.5)]),
        (10, [(0, 10)]),
        (10.25, [(0, 10), (5, 10.25)]),
        (25, [(0, 10), (5, 15), (10, 20), (15, 25)]),
    ],
)
def test_windows(duration, expected):
    assert [(x.start, x.end) for x in generate_windows("v", duration)] == expected


def test_fractional_precision_and_no_redundant_window():
    assert generate_windows("v", 15.125)[-1].end == 15.125


def test_transcript_uses_timestamp_overlap_and_preserves_repetition():
    segments = [
        TranscriptSegment(start=1, end=3, text="again"),
        TranscriptSegment(start=6, end=8, text="again"),
        TranscriptSegment(start=12, end=13, text="later"),
    ]
    assert transcript_for_window(segments, 5, 10) == "again"
    assert transcript_for_window(segments, 0, 10) == "again again"


def test_ids_are_stable():
    assert generate_windows("abc", 20)[1].window_id == "abc_window_0001"
