"""Purge synthetic seed_dummy_data.py points that were accidentally written
into the production collection (config.COLLECTION_NAME).

Matches ONLY by exact video_id membership in seed_markers.KNOWN_SEED_VIDEO_IDS
- no fuzzy/substring/caption-text matching - so real indexed data is never at
risk of deletion by this script, even if its captions happen to share words
with seed captions.

Usage:
    python -m query_retrieval.purge_seed_contamination            # dry run, lists only
    python -m query_retrieval.purge_seed_contamination --confirm  # actually deletes
"""
import argparse
import logging

from qdrant_client.models import FieldCondition, Filter, MatchAny

from query_retrieval import config
from query_retrieval.qdrant_client import (
    check_seed_contamination,
    connect_qdrant,
    validate_collection_schema,
)
from query_retrieval.seed_markers import KNOWN_SEED_VIDEO_IDS

logger = logging.getLogger(__name__)


def find_contaminated_points(client=None, collection_name: str | None = None) -> list[dict]:
    """Scroll the collection for points whose video_id exactly matches a
    known seed marker. Returns a list of dicts describing each match."""
    client = client or connect_qdrant()
    collection_name = collection_name or config.COLLECTION_NAME

    found: list[dict] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="video_id", match=MatchAny(any=KNOWN_SEED_VIDEO_IDS))]
            ),
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            found.append(
                {
                    "id": point.id,
                    "video_id": payload.get("video_id"),
                    "window_id": payload.get("window_id"),
                    "caption": (payload.get("caption") or "")[:80],
                }
            )
        if offset is None:
            break
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete the matched points. Without this flag, only lists what would be deleted.",
    )
    args = parser.parse_args()

    client = connect_qdrant()
    collection_name = config.COLLECTION_NAME
    targets = find_contaminated_points(client, collection_name)

    if not targets:
        print(f"No seed-marker points found in '{collection_name}' (exact video_id match). Nothing to do.")
        return

    print(f"Found {len(targets)} point(s) in '{collection_name}' matching known seed video_ids (exact match):\n")
    for t in targets:
        print(f"  id={t['id']}  video_id={t['video_id']}  window_id={t['window_id']}  caption={t['caption']!r}")

    if not args.confirm:
        print(
            f"\nDry run only - {len(targets)} point(s) would be deleted from '{collection_name}'. "
            "Re-run with --confirm to actually delete."
        )
        return

    ids = [t["id"] for t in targets]
    client.delete(collection_name=collection_name, points_selector=ids)
    logger.info(
        "Deleted %d seed-contamination point(s) from '%s': %s",
        len(ids),
        collection_name,
        [(t["video_id"], t["window_id"]) for t in targets],
    )
    print(f"\nDeleted {len(ids)} point(s) from '{collection_name}'.")

    schema_issues = validate_collection_schema(client)
    remaining = check_seed_contamination(client, collection_name)
    remaining_count_result = client.count(collection_name=collection_name, exact=True)

    print(f"\nPost-purge schema check: {'OK' if not schema_issues else schema_issues}")
    print(f"Post-purge contamination check: {remaining['contaminated_count']} seed point(s) remaining.")
    print(f"Post-purge total points remaining in '{collection_name}': {remaining_count_result.count}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
