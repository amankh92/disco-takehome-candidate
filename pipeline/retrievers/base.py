"""
Base abstractions for the retrieval layer.

Adding a new data store means implementing Retriever and nothing else changes —
the orchestrator (retrieve.py), RRF fusion (rrf.py), and all other retrievers
are unaffected.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RetrievalQuery:
    hard_facets: dict           # category, income_tiers, geos — WHERE clause material
    soft_facets: dict           # aov_min/max, gender_skew — scoring weights
    age_range: dict             # {min: int, max: int}
    facet_confidence: dict      # per-dimension 0.0–1.0 scores
    fts_keywords: str           # space-separated keywords for full-text search
    query_embedding: list[float]  # pre-computed embedding of embedding_query


@dataclass
class ScoredCandidate:
    publisher_id: str
    score: float                # normalised score (e.g. RRF score or raw similarity)
    source: str                 # "facet" | "dense" | "sparse" | "hybrid"
    metadata: dict = field(default_factory=dict)  # optional passthrough (rank, raw score, etc.)


class Retriever(ABC):
    """
    Common interface for all retrieval strategies.

    Each implementation encapsulates one data store and one retrieval mode.
    Swap the implementation to change the store; the pipeline never changes.
    """

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> list[ScoredCandidate]:
        """
        Return candidates scored and sourced by this retriever.
        No ordering guarantee — callers apply RRF fusion.
        """
        ...
