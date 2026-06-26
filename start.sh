#!/usr/bin/env bash
# ============================================================
# LLM-Keyring startup script for macOS / Linux
# NOTE: v0.1 is Windows-focused. On macOS/Linux the app runs
# in read-only mode (you can view keys but not add/delete).
# ============================================================

set -e

# Locate python3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 not found. Install Python 3.9+ first."
    exit 1
fi

# Check version (need 3.9+)
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Detected Python $PYVER"

# Install dependencies if missing
if ! python3 -c "import fastapi" &> /dev/null; then
    echo "Installing dependencies..."
    python3 -m pip install --quiet -r requirements.txt
fi

# Launch
echo "Starting LLM-Keyring (read-only on this platform)..."
python3 main.py