"""
DenseRetriever — ANN vector search via pgvector.

To swap for Qdrant: replace the constructor (accept a Qdrant client)
and the retrieve() body. Interface and callers unchanged.
"""

import psycopg2
from psycopg2.extras import RealDictCursor

from pipeline.retrievers.base import Retriever, RetrievalQuery, ScoredCandidate

_LIMIT = 20


class DenseRetriever(Retriever):
    def __init__(self, conn: psycopg2.extensions.connection) -> None:
        self._conn = conn

    def retrieve(self, query: RetrievalQuery) -> list[ScoredCandidate]:
        sql = """
            SELECT id,
                   embedding <=> %(vec)s::vector AS distance
            FROM publishers
            ORDER BY embedding <=> %(vec)s::vector
            LIMIT %(limit)s
        """

        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, {"vec": query.query_embedding, "limit": _LIMIT})
            rows = cur.fetchall()

        return [
            ScoredCandidate(
                publisher_id=row["id"],
                score=1.0 - float(row["distance"]),  # cosine distance → similarity
                source="dense",
                metadata={"distance": float(row["distance"])},
            )
            for row in rows
        ]
