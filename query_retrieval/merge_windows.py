"""Merge overlapping/adjacent same-video FusedHits into candidate regions.

MERGE_GAP_SECONDS lives in config.py, env-overridable.
"""
from query_retrieval import config
from query_retrieval.models import FusedHit, MergedRegion


def merge_windows(fused_hits: list[FusedHit]) -> list[MergedRegion]:
    """Merge fused hits belonging to the same event into single regions.

    Windows are grouped by video_id first - merging never crosses videos,
    even if timestamps happen to coincide. Within a video, windows are
    sorted by start time, then chain-merged: a window joins the current
    cluster if it overlaps the cluster's time span so far, or the gap
    between the cluster's rightmost end and the window's start is
    <= MERGE_GAP_SECONDS. Comparing against the cluster's running max end
    (not just the previous window) is what makes A-B-C chains collapse into
    one region even when A and C don't directly overlap/qualify.

    Each region's fused_score is the max of its constituents' scores,
    matched_modalities is the union, and payload is taken from whichever
    constituent has the highest fused_score. Output is sorted by
    fused_score descending.
    """
    by_video: dict[str, list[FusedHit]] = {}
    for hit in fused_hits:
        by_video.setdefault(hit.payload.video_id, []).append(hit)

    regions: list[MergedRegion] = []
    for video_id, hits in by_video.items():
        ordered = sorted(hits, key=lambda h: h.payload.start)
        cluster: list[FusedHit] = []

        for hit in ordered:
            if cluster:
                cluster_end = max(h.payload.end for h in cluster)
                gap = hit.payload.start - cluster_end
                if gap <= config.MERGE_GAP_SECONDS:
                    cluster.append(hit)
                    continue
                regions.append(_finalize_cluster(video_id, cluster))
            cluster = [hit]

        if cluster:
            regions.append(_finalize_cluster(video_id, cluster))

    regions.sort(key=lambda r: r.fused_score, reverse=True)
    return regions


def _finalize_cluster(video_id: str, cluster: list[FusedHit]) -> MergedRegion:
    best = max(cluster, key=lambda h: h.fused_score)
    matched_modalities: set[str] = set()
    for hit in cluster:
        matched_modalities.update(hit.matched_modalities)

    return MergedRegion(
        video_id=video_id,
        start=min(h.payload.start for h in cluster),
        end=max(h.payload.end for h in cluster),
        fused_score=best.fused_score,
        payload=best.payload,
        matched_modalities=sorted(matched_modalities),
        source_window_ids=[h.window_id for h in cluster],
    )
