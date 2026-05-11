"""
SparseRetriever — full-text search via PostgreSQL tsvector + ts_rank.

To swap for Elasticsearch BM25: replace the constructor (accept an ES client)
and the retrieve() body. Interface and callers unchanged.
"""

import psycopg2
from psycopg2.extras import RealDictCursor

from pipeline.retrievers.base import Retriever, RetrievalQuery, ScoredCandidate

_LIMIT = 20


class SparseRetriever(Retriever):
    def __init__(self, conn: psycopg2.extensions.connection) -> None:
        self._conn = conn

    def retrieve(self, query: RetrievalQuery) -> list[ScoredCandidate]:
        if not query.fts_keywords.strip():
            return []

        sql = """
            SELECT id,
                   ts_rank(search_tsv, plainto_tsquery('english', %(keywords)s)) AS rank_score
            FROM publishers
            WHERE search_tsv @@ plainto_tsquery('english', %(keywords)s)
            ORDER BY rank_score DESC
            LIMIT %(limit)s
        """

        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, {"keywords": query.fts_keywords, "limit": _LIMIT})
            rows = cur.fetchall()

        return [
            ScoredCandidate(
                publisher_id=row["id"],
                score=float(row["rank_score"]),
                source="sparse",
                metadata={"ts_rank": float(row["rank_score"])},
            )
            for row in rows
        ]
