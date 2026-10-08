#!/usr/bin/env bash
# TruthLens setup for macOS / Linux
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "=== TruthLens setup ==="

PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[x] Python 3.10, 3.11 or 3.12 is required (https://www.python.org/downloads/)."
  exit 1
fi
echo "[ok] Using $PY"

if ! command -v node >/dev/null 2>&1; then
  echo "[x] Node.js 20 or newer is required (https://nodejs.org/)."
  exit 1
fi
echo "[ok] Node.js $(node --version)"

echo
echo "--- Installing the backend (this can take a few minutes) ---"
[ -x backend/.venv/bin/python ] || "$PY" -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip --quiet
backend/.venv/bin/python -m pip install -r backend/requirements.txt

if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "[!] Created backend/.env - open it and paste your GEMINI_API_KEY."
fi

echo
echo "--- Building the web app ---"
(cd frontend && (npm ci || npm install) && npm run build)

echo
echo "=== Setup complete ==="
echo " 1. Put your Gemini API key in backend/.env  (GEMINI_API_KEY=...)"
echo " 2. Start the app with:  ./run.sh"
