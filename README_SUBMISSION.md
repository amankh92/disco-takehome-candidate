# Ad Placement & Creative Generation

## What I built

**Stack:** FastAPI (Python) · Next.js · PostgreSQL + pgvector · Claude Sonnet (runtime) · Claude Haiku (offline ingest) · OpenAI `text-embedding-3-small`

PostgreSQL handles all three query modes — facet filtering (btree), full-text search (tsvector + GIN), and vector search (pgvector HNSW) — in one datastore. Sonnet is used at runtime for steps that require reasoning; Haiku handles offline fit description generation where the task is well-defined and runs in batch.

**Ingestion (offline, run once).** `ingest/seed.py` transforms `publishers.json`, generates a fit description per publisher via Haiku, embeds those descriptions, and upserts everything into Postgres. It also derives `facets.json` — all valid enum values for categories, income tiers, geos, and subcategories — which is used at runtime to constrain the brief understanding LLM's structured output.

Fit descriptions exist because advertiser briefs and publisher records don't embed near each other naturally. Rewriting each publisher as "what kind of advertiser would do well here" puts both sides in the same embedding space. In production this runs per record at onboarding time; `enrich_publishers()` in `ingest/embed.py` already supports that.

**Runtime pipeline.**

```
Brief
  → [Sonnet] structured extraction: categories, income tiers, age range, keywords, embedding query
  → parallel retrieval:
      Branch A — facet filter (SQL WHERE on high-confidence hard facets)
      Branch B — hybrid: dense (pgvector ANN) + sparse (tsvector FTS), inner RRF
  → outer RRF fusion → top-30 candidates
  → [Sonnet] rerank: fit scores 1–10, per-publisher reasoning, exclusion reasons
  → parallel:
      [Sonnet] campaign config — bid strategy (CPM/CPC/CPA), budget allocation, flight, brand safety
      [Sonnet] creative generation — one variant per persona, single call at temperature 1.0
```

4 Sonnet calls per run. Haiku is used only in the offline ingest step.

**Outputs:** ranked publisher list with fit scores and exclusion reasons for every non-recommended publisher; 3–5 ad creative variants each tuned to a different shopper persona with reasoning visible; structured campaign config with per-publisher budget allocation and reasoning.

**Frontend.** Next.js. Streams pipeline events via SSE and renders each stage (brief understanding, candidate retrieval, rerank preview, final result) as it completes.

---

## How to run

**Local** (requires PostgreSQL 18 + pgvector)

macOS:
```bash
brew install postgresql@18 pgvector
brew services start postgresql@18
```

Linux:
```bash
sudo apt-get install -y postgresql-18 postgresql-18-pgvector
sudo service postgresql start
```

Then:
```bash
cp .env.example .env                    # add ANTHROPIC_API_KEY and OPENAI_API_KEY
bash scripts/setup.sh                   # venv, deps, DB schema, seed (~2 min first run)
bash scripts/start.sh                   # API :8000, frontend :3000
```

**Docker**
```bash
cp .env.example .env        # add API keys
docker compose up           # seeds DB on first run (~2 min); skipped on restart
```

To reset the database and re-seed from scratch:
```bash
docker compose down -v      # removes containers and the persistent volume
docker compose up
```

---

## What I'd do with another week

1. **Pre-computed numerical similarity.** AOV, gender split, and age range are passed as text to the LLM today. At scale these need to be computed in Python before the rerank call — AOV proximity, age range overlap, gender split distance — and injected as structured fields alongside each publisher so the reranker works with explicit numbers rather than text descriptions.

2. **Persona retrieval at scale.** `persona_embedding_query` is extracted on every call, ready for ANN-based persona retrieval when the catalog grows past what fits in a prompt. The publisher retrieval architecture already exists — extending it to personas is straightforward once the catalog warrants it.

3. **Subcategory filtering.** Subcategories are passed to LLMs as context only — the retrieval layer doesn't filter on them, and `facets.json` stores them as a flat list across all verticals. At N=20 this is fine. As the catalog grows, subcategory filtering becomes necessary: category-level first (already in place), subcategory-level second, with subcategories grouped by parent category rather than a flat pool.

---

## What I intentionally cut

**Retrieval parameter tuning.** RRF works on ranks alone, so there's no score calibration needed between branches. But tuning k=60, branch weighting, the confidence threshold (0.6), or any other parameter requires labeled examples to validate against. Building that eval loop is a multi-week investment. Without it, every parameter stays a starting default — which is where they are now.

**Full BM25.** PostgreSQL `ts_rank` (TF-IDF) is close enough at N=20. `ts_rank` doesn't normalize for document length, so longer publisher descriptions score higher regardless of actual term relevance — BM25 corrects for this. The gap doesn't matter at this scale but shows at larger catalogs.

**Category adjacency graph.** Cross-category placements — a brand converting on a publisher in a related vertical because audiences overlap — require encoding which categories are related. Encoding that requires building a graph of adjacent categories and injecting those signals into retrieval and reranking. This is a data modeling problem, not a retrieval tuning problem.

---

## Hard vs easy

**Straightforward:**
- LLM calls — tool schemas with constrained output and clear system prompts handle most of the complexity
- Retrieval infrastructure — pgvector + tsvector is standard; the schema, indexes, and queries are well-documented
- Async pipeline and SSE streaming — FastAPI BackgroundTasks plus an in-process queue is enough for this scale

**Genuinely hard:**

**No labeled data, no way to measure anything.** Retrieval recall, rerank precision, and prompt quality are all unmeasurable without ground truth. This includes the fit description approach itself — Haiku rewrites each publisher record as an ideal advertiser brief to put both sides in the same embedding space, and it works, but there's no way to verify that those descriptions match how real advertisers actually describe their products. The only validation is looking at results manually.

**Numerical signals passed as text.** AOV, gender split, and age range are continuous values. The system encodes them in text and relies on the LLM to approximate proximity rather than compute it. This works at N=20 but is not a real system at scale.

---

## Known gaps

- At N=20 all three retrieval branches return essentially the full catalog — the multi-branch design and RRF fusion are the right patterns for production but aren't load-bearing at this scale. The LLM reranker is the only active precision mechanism. RRF scores are passed to the reranker as a weak signal; the LLM overrides them on fit quality.
- Error handling covers one case: briefs with average facet confidence below 0.3 are rejected. Empty retrieval sets, malformed LLM outputs, and mid-run DB failures are unhandled.
- Reloading during a running job loses the result. The backend persists completed jobs and replays on reconnect, but the frontend doesn't store the job ID, so there's nothing to reconnect to mid-run.
