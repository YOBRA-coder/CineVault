#!/usr/bin/env bash
# One-command start (macOS / Linux). The React app is pre-built in frontend/dist.
set -e
cd "$(dirname "$0")/backend"
python3 app.py
