#!/usr/bin/env bash
# Docker entrypoint for the API container.
# Waits for Postgres, applies schema, seeds data, then starts uvicorn.
set -euo pipefail

echo "→ Waiting for Postgres..."
until python3 - <<'EOF'
import psycopg2, os, sys
try:
    psycopg2.connect(os.environ["DATABASE_URL"])
    sys.exit(0)
except Exception:
    sys.exit(1)
EOF
do
  sleep 2
done
echo "  Postgres ready."

echo "→ Applying schema..."
psql "$DATABASE_URL" -f db/schema.sql -q
echo "  Done."

PUBLISHER_COUNT=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM publishers;" 2>/dev/null | tr -d ' \n' || echo "0")
if [ "${PUBLISHER_COUNT:-0}" -gt 0 ]; then
  echo "→ Publishers already seeded ($PUBLISHER_COUNT records), skipping."
else
  echo "→ Seeding publishers..."
  python ingest/seed.py
fi

echo "→ Starting API..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
