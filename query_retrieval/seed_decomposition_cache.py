"""One-off/rerunnable script: pre-populate decomposition_cache.json with
real Gemini decompositions for a curated list of demo queries, so demo-day
runs of those exact queries hit the cache tier (tier 1) and never touch
the network - see decomposition.py's three-tier fallback ladder.

Usage:
    python -m query_retrieval.seed_decomposition_cache

Requires a real GEMINI_API_KEY in query_retrieval/.env. Merges into the
existing cache file rather than overwriting it - safe to rerun after
adding new queries to DEMO_QUERIES.
"""
import json
import logging

from query_retrieval import config, decomposition

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Extends demo_queries.py's curated list with a few more realistic
# variations for broader decomposition coverage.
DEMO_QUERIES = [
    "red car",
    "person wearing glasses",
    "dog barking",
    "glass breaking",
    "someone says hello",
    "person mentions their name",
    "a celebration",
    "an outdoor scene",
    "man shouting while driving",
    "a birthday party",
    "loud crash sound",
    "quiet room",
    "someone stole the milk from the fridge",
    "a person in a red jacket near the door",
    "two people talking in a lobby",
    "a dog barking near a fence",
    "person mentions their name and address",
    "an explosion sound in the distance",
    "a package being delivered at the entrance",
    "a person in a dark jacket pauses near a side entrance",
]


def main() -> None:
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY not set in query_retrieval/.env - can't pre-seed live decompositions.")

    # DECOMPOSITION_TIMEOUT_SECONDS (1.0s default) is tuned for the live
    # in-request path, where giving up fast matters more than completing
    # the call. A batch seeding script has the opposite priority - and
    # worse, a call that's abandoned at 1.0s doesn't actually stop; the
    # daemon thread keeps running and the real API request still lands,
    # still burning quota, for a result this script would've just thrown
    # away. Use a generous timeout here so seeding runs don't waste calls.
    config.DECOMPOSITION_TIMEOUT_SECONDS = 15.0

    cache = dict(decomposition._load_cache())  # start from whatever's already cached
    added = 0

    for query in DEMO_QUERIES:
        if query in cache:
            logger.info("skip (already cached): %r", query)
            continue
        try:
            result = decomposition._live_decompose(query)
        except Exception as exc:  # noqa: BLE001 - log and continue, don't let one bad query kill the batch
            logger.warning("live decomposition failed for %r: %s - skipping", query, exc)
            continue
        cache[query] = result.model_dump(exclude={"tier"})
        added += 1
        logger.info("cached %r -> weights=%s", query, result.weights)

    decomposition.CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
    logger.info("Wrote %d total entries (%d new) to %s", len(cache), added, decomposition.CACHE_PATH)


if __name__ == "__main__":
    main()
