CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS publishers (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    category            TEXT NOT NULL,
    subcategories       TEXT[] NOT NULL,
    min_age             INTEGER NOT NULL,
    max_age             INTEGER NOT NULL,
    income_tier         TEXT NOT NULL,
    top_geos            TEXT[] NOT NULL,
    aov_usd             NUMERIC NOT NULL,
    monthly_impressions BIGINT NOT NULL,
    gender_female_pct   NUMERIC NOT NULL,
    gender_male_pct     NUMERIC NOT NULL,
    notes               TEXT NOT NULL,
    search_tsv          TSVECTOR,
    fit_description     TEXT,
    embedding           VECTOR(1536)
);

CREATE INDEX IF NOT EXISTS publishers_category_idx        ON publishers (category);
CREATE INDEX IF NOT EXISTS publishers_income_tier_idx     ON publishers (income_tier);
CREATE INDEX IF NOT EXISTS publishers_age_idx             ON publishers (min_age, max_age);
CREATE INDEX IF NOT EXISTS publishers_aov_idx             ON publishers (aov_usd);
CREATE INDEX IF NOT EXISTS publishers_search_tsv_idx      ON publishers USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS publishers_embedding_idx       ON publishers USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Job queue (async pipeline runs)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    brief       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    result      JSONB,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at DESC);
