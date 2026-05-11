#!/usr/bin/env bash
# Starts the FastAPI backend and Next.js frontend.
# Run after setup.sh has been completed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -d .venv ]; then
  echo "Error: .venv not found. Run ./scripts/setup.sh first."
  exit 1
fi

source .venv/bin/activate

# ── API ───────────────────────────────────────────────────────────────────────
echo "→ Starting API on http://localhost:8000 ..."
uvicorn api.main:app --reload --port 8000 &
API_PID=$!

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "→ Starting frontend on http://localhost:3000 ..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "App running:"
echo "  Frontend → http://localhost:3000"
echo "  API      → http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop."

cleanup() {
  kill "$API_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
wait
