"""
Phase 6 — FastAPI Backend

POST /api/analyze      → enqueues pipeline, returns { job_id } immediately
GET  /api/jobs/{id}/stream → SSE stream of pipeline stage events
"""

import asyncio
import json
import os
import sys
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from concurrent.futures import ThreadPoolExecutor

from db.connection import get_connection
from pipeline.understand import understand_brief
from pipeline.retrieve import retrieve_candidates
from pipeline.rerank import rerank
from pipeline.config import build_campaign_config
from pipeline.generate import generate_creatives


# ---------------------------------------------------------------------------
# In-process job queue: job_id -> asyncio.Queue
# Only present while a job is running and an SSE client is connected.
# ---------------------------------------------------------------------------

job_queues: dict[str, asyncio.Queue] = {}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    brief: str


class JobCreatedResponse(BaseModel):
    job_id: str


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

persona_records: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global persona_records
    data = json.loads((ROOT / "data" / "shopper_personas.json").read_text())
    persona_records = {p["id"]: p for p in data}

    # Ensure jobs table exists (idempotent)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id          TEXT PRIMARY KEY,
                    status      TEXT NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'running', 'completed', 'failed')),
                    brief       TEXT NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    result      JSONB,
                    error       TEXT
                )
            """)
        conn.commit()
    finally:
        conn.close()

    yield


app = FastAPI(title="Disco Ad Placement API", lifespan=lifespan)

_CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# DB helpers (sync — called from threads or startup)
# ---------------------------------------------------------------------------

def _db_execute(sql: str, params: tuple) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _db_get_job(job_id: str) -> dict | None:
    from psycopg2.extras import RealDictCursor
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(event_type: str, data: dict) -> str:
    """Format a single SSE message."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Pipeline runner — executes in a thread pool worker
# ---------------------------------------------------------------------------

def _run_pipeline(
    job_id: str,
    brief: str,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    _persona_records: dict,
) -> None:
    def emit(event_type: str, data: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event_type, data))

    try:
        _db_execute("UPDATE jobs SET status='running', updated_at=now() WHERE id=%s", (job_id,))

        # Stage 1: understand
        emit("status", {"stage": "understand", "message": "Parsing brief…"})
        understanding = understand_brief(brief)

        # Validate that the brief contained enough signal to be useful.
        # Confidence scores are more reliable than presence checks — the model will
        # hallucinate categories before it returns empty, so low confidence is the
        # honest signal that the brief wasn't meaningful.
        avg_confidence = sum(understanding.facet_confidence.values()) / max(len(understanding.facet_confidence), 1)
        if avg_confidence < 0.3:
            raise ValueError(
                "Brief doesn't contain enough information to match publishers. "
                "Please describe your product, target customer, or category in a sentence or two."
            )

        emit("understand", {
            "hard_facets": understanding.hard_facets,
            "soft_facets": understanding.soft_facets,
            "age_range": understanding.age_range,
            "facet_confidence": understanding.facet_confidence,
            "fts_keywords": understanding.fts_keywords,
            "embedding_query": understanding.embedding_query,
            "persona_embedding_query": understanding.persona_embedding_query,
        })

        # Stage 2: retrieve
        emit("status", {"stage": "retrieve", "message": "Retrieving candidates…"})
        candidates = retrieve_candidates(understanding)
        emit("retrieve", {
            "candidate_count": len(candidates),
            "candidates": [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "category": c["category"],
                    "rrf_score": float(c["rrf_score"]),
                    "retrieval_source": c.get("retrieval_source", ""),
                    "income_tier": c["income_tier"],
                    "min_age": c["min_age"],
                    "max_age": c["max_age"],
                    "aov_usd": float(c["aov_usd"]),
                    "top_geos": c["top_geos"],
                }
                for c in candidates
            ],
        })

        # Stage 3: rerank
        emit("status", {"stage": "rerank", "message": "Ranking publishers…"})
        reranked = rerank(brief, candidates, _persona_records, understanding)
        emit("rerank", {
            "recommended_count": len(reranked.recommended),
            "excluded_count": len(reranked.excluded),
            "top_publishers": [
                {
                    "publisher_id": pub.publisher_id,
                    "name": pub.name,
                    "fit_score": pub.fit_score,
                    "fit_reasoning": pub.fit_reasoning,
                }
                for pub in reranked.recommended[:3]
            ],
        })

        # Stage 4: campaign config + creative generation (parallel)
        emit("status", {"stage": "generate", "message": "Generating creatives and campaign config…"})
        with ThreadPoolExecutor(max_workers=2) as executor:
            config_future = executor.submit(build_campaign_config, brief, understanding, reranked)
            creatives_future = executor.submit(generate_creatives, brief, reranked.ranked_personas, _persona_records, reranked.recommended)
            campaign_config = config_future.result()
            creative_variants = creatives_future.result()

        # Assemble final result
        result_payload = {
            "brief": brief,
            "ranked_publishers": [
                {
                    "publisher_id": pub.publisher_id,
                    "name": pub.name,
                    "category": pub.category,
                    "subcategories": pub.record["subcategories"],
                    "fit_score": pub.fit_score,
                    "fit_reasoning": pub.fit_reasoning,
                    "retrieval_source": pub.record.get("retrieval_source", ""),
                    "rrf_score": float(pub.record.get("rrf_score", 0)),
                    "aov_usd": float(pub.record["aov_usd"]),
                    "monthly_impressions": pub.record["monthly_impressions"],
                    "income_tier": pub.record["income_tier"],
                    "min_age": pub.record["min_age"],
                    "max_age": pub.record["max_age"],
                    "top_geos": pub.record["top_geos"],
                    "notes": pub.record["notes"],
                }
                for pub in reranked.recommended
            ],
            "excluded_publishers": [
                {
                    "publisher_id": pub.publisher_id,
                    "name": pub.name,
                    "exclusion_reason": pub.exclusion_reason,
                }
                for pub in reranked.excluded
            ],
            "creative_variants": [
                {
                    "persona_name": v.persona_name,
                    "persona_reasoning": v.persona_reasoning,
                    "headline": v.headline,
                    "body_copy": v.body_copy,
                    "persona_meta": {
                        k: _persona_records.get(v.persona_id, {}).get(k)
                        for k in ("age_range", "gender_skew", "description", "typical_aov_usd",
                                  "price_sensitivity", "messaging_preferences",
                                  "category_affinities", "disinterested_in")
                    },
                }
                for v in creative_variants
            ],
            "campaign_config": campaign_config,
        }

        _db_execute(
            "UPDATE jobs SET status='completed', updated_at=now(), result=%s WHERE id=%s",
            (json.dumps(result_payload), job_id),
        )
        emit("complete", result_payload)

    except Exception as exc:
        print(traceback.format_exc(), file=sys.stderr)
        _db_execute(
            "UPDATE jobs SET status='failed', updated_at=now(), error=%s WHERE id=%s",
            (str(exc), job_id),
        )
        emit("error", {"message": str(exc)})

    finally:
        # Sentinel — signals the SSE generator to close
        loop.call_soon_threadsafe(queue.put_nowait, None)


async def _run_pipeline_task(
    job_id: str,
    brief: str,
    queue: asyncio.Queue,
    _persona_records: dict,
) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_pipeline, job_id, brief, queue, loop, _persona_records)


# ---------------------------------------------------------------------------
# SSE generator — drains the queue and yields SSE-formatted strings
# ---------------------------------------------------------------------------

async def _sse_generator(job_id: str, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            if item is None:
                break

            event_type, data = item
            yield _sse(event_type, data)

            if event_type in ("complete", "error"):
                break

    except GeneratorExit:
        pass
    finally:
        job_queues.pop(job_id, None)


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/analyze", response_model=JobCreatedResponse, status_code=202)
async def analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    if not req.brief.strip():
        raise HTTPException(status_code=400, detail="Brief cannot be empty.")

    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    job_queues[job_id] = queue

    _db_execute("INSERT INTO jobs (id, brief, status) VALUES (%s, %s, 'pending')", (job_id, req.brief))

    background_tasks.add_task(_run_pipeline_task, job_id, req.brief, queue, persona_records)

    return JobCreatedResponse(job_id=job_id)


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    queue = job_queues.get(job_id)

    if queue is not None:
        # Live job — stream directly from the queue
        return StreamingResponse(
            _sse_generator(job_id, queue),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    # Queue not in memory — look up DB for reconnect / replay
    job = _db_get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job["status"] == "completed" and job["result"] is not None:
        async def _replay_complete() -> AsyncGenerator[str, None]:
            yield _sse("complete", job["result"])
        return StreamingResponse(_replay_complete(), media_type="text/event-stream", headers=_SSE_HEADERS)

    if job["status"] == "failed":
        async def _replay_error() -> AsyncGenerator[str, None]:
            yield _sse("error", {"message": job["error"] or "Pipeline failed."})
        return StreamingResponse(_replay_error(), media_type="text/event-stream", headers=_SSE_HEADERS)

    # pending/running but queue is gone (server restart mid-job)
    async def _replay_lost() -> AsyncGenerator[str, None]:
        yield _sse("error", {"message": "Job was interrupted by a server restart. Please resubmit."})
    return StreamingResponse(_replay_lost(), media_type="text/event-stream", headers=_SSE_HEADERS)
