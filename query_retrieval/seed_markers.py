"""Canonical list of synthetic seed markers written by seed_dummy_data.py's
build_points(), across all seeding scenarios it has ever defined.

Single source of truth for qdrant_client.check_seed_contamination() and
purge_seed_contamination.py, so the two can't drift out of sync. Kept
separate from seed_dummy_data.py itself to avoid a circular import
(qdrant_client <-> seed_dummy_data).

If build_points() gains a new scenario/video_id, add it here too.
"""

KNOWN_SEED_VIDEO_IDS: list[str] = [
    "video_a",
    "video_b",
    "video_c",
    "video_d",
    "video_e",
    "video_f",
    "video_short",
    "video_long",
    "video_full",
    "video_dup_a",
    "video_dup_b",
    "video_edge",
]

# Fixed caption/transcript literals from build_points() - exact match.
KNOWN_SEED_CAPTION_EXACT: list[str] = [
    "A dog is barking near a fence",
    "a red bicycle leaning against a wall",
    "a blue car parked outside",
    "completely unrelated content",
    "Zero-duration edge case window",
    "Very large timestamp edge case window",
]
KNOWN_SEED_TRANSCRIPT_EXACT: list[str] = [
    "A dog barks loudly",
    "completely unrelated content",
]

# Numeric-suffixed literals (e.g. "...frame 0", "...frame 1") - suffix
# varies per window index, so these are prefix matches, not exact.
KNOWN_SEED_CAPTION_PREFIXES: list[str] = [
    "A person walks across frame ",
    "Static landscape shot ",
    "Short clip segment ",
    "Long video segment ",
    "A fully-annotated scene ",
]
KNOWN_SEED_TRANSCRIPT_PREFIXES: list[str] = [
    "Speaker discusses topic ",
    "Narrator describes scene ",
]
