"""
FacetRetriever — hard constraint filtering via PostgreSQL WHERE clauses.

To swap this for Elasticsearch structured queries, replace the body of retrieve()
and update the constructor to accept an ES client instead of a psycopg2 connection.
The Retriever interface and all callers remain unchanged.
"""

import psycopg2
from psycopg2.extras import RealDictCursor

from pipeline.retrievers.base import Retriever, RetrievalQuery, ScoredCandidate
from pipeline.retrievers.rrf import CONFIDENCE_THRESHOLD


def build_hard_facet_conditions(query: RetrievalQuery) -> tuple[list[str], dict]:
    """
    Shared helper: converts high-confidence hard facets into SQL WHERE conditions.
    Used by FacetRetriever, DenseRetriever, and SparseRetriever so all three
    apply identical constraints.
    """
    conditions: list[str] = []
    params: dict = {}
    conf = query.facet_confidence

    categories = query.hard_facets.get("categories", [])
    if categories and conf.get("categories", 0) >= CONFIDENCE_THRESHOLD:
        conditions.append("category = ANY(%(categories)s)")
        params["categories"] = categories

    income_tiers = query.hard_facets.get("income_tiers", [])
    if income_tiers and conf.get("income_tiers", 0) >= CONFIDENCE_THRESHOLD:
        conditions.append("income_tier = ANY(%(income_tiers)s)")
        params["income_tiers"] = income_tiers

    if conf.get("age_range", 0) >= CONFIDENCE_THRESHOLD:
        conditions.append("min_age <= %(age_max)s AND max_age >= %(age_min)s")
        params["age_min"] = query.age_range["min"]
        params["age_max"] = query.age_range["max"]

    geos = query.hard_facets.get("geos", [])
    if geos and conf.get("geos", 0) >= CONFIDENCE_THRESHOLD:
        conditions.append(
            "('nationwide' = ANY(top_geos) OR %(geo)s = ANY(top_geos))"
        )
        params["geo"] = geos[0]

    return conditions, params


class FacetRetriever(Retriever):
    def __init__(self, conn: psycopg2.extensions.connection) -> None:
        self._conn = conn

    def retrieve(self, query: RetrievalQuery) -> list[ScoredCandidate]:
        conditions, params = build_hard_facet_conditions(query)

        if not conditions:
            # No confident hard facets — return empty rather than the entire catalog
            return []

        sql = f"""
            SELECT id
            FROM publishers
            WHERE {" AND ".join(conditions)}
        """

        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        # All facet matches are equally weighted at this stage;
        # relative ordering comes from outer RRF.
        return [
            ScoredCandidate(publisher_id=row["id"], score=1.0, source="facet")
            for row in rows
        ]

