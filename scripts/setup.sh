#!/usr/bin/env bash
# Local setup: creates venv, installs dependencies, initialises the database, seeds data.
# Run once before using start.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── .env ──────────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example."
  echo "Add your ANTHROPIC_API_KEY and OPENAI_API_KEY, then re-run this script."
  exit 1
fi

if grep -q "your_anthropic_api_key_here" .env; then
  echo "Error: fill in your API keys in .env before running setup."
  exit 1
fi

# ── Postgres + pgvector check ─────────────────────────────────────────────────
if ! command -v psql &>/dev/null; then
  echo "Error: PostgreSQL 18 + pgvector are required for local setup."
  echo ""
  echo "  macOS:  brew install postgresql@18 pgvector && brew services start postgresql@18"
  echo "  Linux:  sudo apt-get install -y postgresql-18 postgresql-18-pgvector && sudo service postgresql start"
  echo ""
  echo "  Or skip local setup entirely: docker compose up"
  exit 1
fi

# ── Python venv ───────────────────────────────────────────────────────────────
echo "→ Creating Python venv..."
python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate
pip install --quiet -r requirements.txt
echo "  Done."

# ── Node dependencies ─────────────────────────────────────────────────────────
echo "→ Installing frontend dependencies..."
cd frontend && npm install --silent && cd ..
echo "  Done."

# ── Database ──────────────────────────────────────────────────────────────────
echo "→ Setting up database..."
source .env  # load DATABASE_URL
DB_NAME="${DATABASE_URL##*/}"   # extract "disco" from the URL
createdb "$DB_NAME" 2>/dev/null && echo "  Created database '$DB_NAME'." \
  || echo "  Database '$DB_NAME' already exists, skipping."
psql "$DATABASE_URL" -f db/schema.sql -q
echo "  Schema applied."

# ── Seed ─────────────────────────────────────────────────────────────────────
echo "→ Seeding publishers (LLM calls + embeddings — takes ~2 min on first run)..."
python ingest/seed.py
echo ""
echo "Setup complete. Run ./scripts/start.sh to launch the app."
