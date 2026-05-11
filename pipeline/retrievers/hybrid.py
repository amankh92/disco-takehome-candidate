"""
HybridRetriever — composes DenseRetriever + SparseRetriever with inner RRF.

Implements the Retriever interface so it can be passed to the orchestrator
exactly like any other retriever. Adding a third signal (e.g. BM25 from
a different store) means adding it to the inner rrf_fuse call here.
"""

from pipeline.retrievers.base import Retriever, RetrievalQuery, ScoredCandidate
from pipeline.retrievers.dense import DenseRetriever
from pipeline.retrievers.sparse import SparseRetriever
from pipeline.retrievers.rrf import rrf_fuse

_TOP_K = 20


class HybridRetriever(Retriever):
    def __init__(
        self,
        dense: DenseRetriever,
        sparse: SparseRetriever,
        k: int = 60,
    ) -> None:
        self._dense = dense
        self._sparse = sparse
        self._k = k

    def retrieve(self, query: RetrievalQuery) -> list[ScoredCandidate]:
        dense_results = self._dense.retrieve(query)
        sparse_results = self._sparse.retrieve(query)

        fused = rrf_fuse([dense_results, sparse_results], k=self._k)

        # Tag the fused results with source "hybrid" for outer RRF traceability
        for c in fused:
            c.source = "hybrid"

        return fused[:_TOP_K]
