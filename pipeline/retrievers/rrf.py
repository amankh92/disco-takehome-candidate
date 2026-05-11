"""
Reciprocal Rank Fusion — pure function, no data store dependency.

rrf_fuse() can fuse any number of ranked candidate lists. Adding a new retriever
to the pipeline requires no changes here.
"""

from pipeline.retrievers.base import ScoredCandidate

CONFIDENCE_THRESHOLD = 0.6   # below this, a facet dimension is treated as soft


def rrf_fuse(
    ranked_lists: list[list[ScoredCandidate]],
    k: int = 60,
) -> list[ScoredCandidate]:
    """
    Fuse multiple ranked candidate lists using Reciprocal Rank Fusion.

    Score for candidate c = sum over lists L of: 1 / (k + rank_of_c_in_L)
    Candidates missing from a list are simply not scored for that list.

    Args:
        ranked_lists: Each inner list is already ordered by relevance (index 0 = best).
        k: RRF constant controlling the influence of rank position (default 60).

    Returns:
        Deduplicated candidates ordered by descending fused score,
        with source set to "rrf" and score set to the fused value.
    """
    scores: dict[str, float] = {}
    sources: dict[str, set[str]] = {}

    for ranked in ranked_lists:
        for rank, candidate in enumerate(ranked, start=1):
            pid = candidate.publisher_id
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
            sources.setdefault(pid, set()).add(candidate.source)

    return [
        ScoredCandidate(
            publisher_id=pid,
            score=score,
            source="+".join(sorted(sources[pid])),
        )
        for pid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)
    ]
