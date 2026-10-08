#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -x backend/.venv/bin/python ]; then
  echo "TruthLens isn't installed yet. Run ./setup.sh first."
  exit 1
fi
exec backend/.venv/bin/python backend/run.py "$@"
