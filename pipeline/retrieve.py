"""
Phase 3 — Parallel Retrieval orchestrator.

Runs FacetRetriever and HybridRetriever concurrently, fuses with outer RRF,
fetches full publisher records for the top-30 candidates.
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from db.connection import get_connection
from pipeline.understand import BriefUnderstanding
from pipeline.retrievers.base import RetrievalQuery, ScoredCandidate
from pipeline.retrievers.facet import FacetRetriever
from pipeline.retrievers.dense import DenseRetriever
from pipeline.retrievers.sparse import SparseRetriever
from pipeline.retrievers.hybrid import HybridRetriever
from pipeline.retrievers.rrf import rrf_fuse

_TOP_N = 30
openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def _embed(text: str) -> list[float]:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=[text],
    )
    return response.data[0].embedding


def _build_query(understanding: BriefUnderstanding) -> RetrievalQuery:
    return RetrievalQuery(
        hard_facets=understanding.hard_facets,
        soft_facets=understanding.soft_facets,
        age_range=understanding.age_range,
        facet_confidence=understanding.facet_confidence,
        fts_keywords=understanding.fts_keywords,
        query_embedding=_embed(understanding.embedding_query),
    )


def _fetch_full_records(
    candidates: list[ScoredCandidate],
) -> list[dict]:
    """Fetch full publisher rows for the top candidates in one query."""
    if not candidates:
        return []

    ids = [c.publisher_id for c in candidates]
    score_map = {c.publisher_id: c for c in candidates}

    conn = get_connection()
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM publishers WHERE id = ANY(%s)",
                (ids,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    # Attach rrf_score and source, preserve top-N ordering
    records = []
    for row in rows:
        candidate = score_map[row["id"]]
        record = dict(row)
        record["rrf_score"] = candidate.score
        record["retrieval_source"] = candidate.source
        records.append(record)

    records.sort(key=lambda r: r["rrf_score"], reverse=True)
    return records


def retrieve_candidates(understanding: BriefUnderstanding) -> list[dict]:
    conn = get_connection()
    try:
        query = _build_query(understanding)

        facet_retriever = FacetRetriever(conn)
        hybrid_retriever = HybridRetriever(
            dense=DenseRetriever(conn),
            sparse=SparseRetriever(conn),
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            facet_future = executor.submit(facet_retriever.retrieve, query)
            hybrid_future = executor.submit(hybrid_retriever.retrieve, query)

            facet_results = facet_future.result()
            hybrid_results = hybrid_future.result()

        fused = rrf_fuse([facet_results, hybrid_results])
        top = fused[:_TOP_N]
    finally:
        conn.close()

    return _fetch_full_records(top)


