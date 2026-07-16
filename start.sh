#!/usr/bin/env bash
# ============================================================================
#  ACARS Tracks - launcher for macOS / Linux
#  Run:  ./start.sh           (live data)
#        ./start.sh --demo     (offline synthetic data)
#  First run sets up a small private environment (needs internet); after that
#  it starts quickly. Make it runnable once with:  chmod +x start.sh
# ============================================================================
set -e
cd "$(dirname "$0")"

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
command -v "$PY" >/dev/null 2>&1 || { echo "Python 3 not found. Install it from https://www.python.org/downloads/"; exit 1; }

if [ ! -x ".venv/bin/python" ]; then
    echo "Setting up for first use (this happens only once)..."
    "$PY" -m venv .venv
fi
VENV_PY=".venv/bin/python"

if [ ! -f ".venv/.deps_ok" ]; then
    echo "Installing required packages (first run only, needs internet)..."
    "$VENV_PY" -m pip install --upgrade pip
    "$VENV_PY" -m pip install -r requirements.txt
    echo "Trying optional sounding renderer (pyMeteo)..."
    "$VENV_PY" -m pip install -r requirements-optional.txt || true
    touch ".venv/.deps_ok"
fi

echo "Starting... your web browser should open in a moment. Press Ctrl+C to stop."
exec "$VENV_PY" server.py "$@"
