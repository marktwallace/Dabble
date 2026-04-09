#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_NAME="$(basename "$SCRIPT_DIR")"
PID_FILE="$HOME/.$DEPLOY_NAME.pid"
LOG_FILE="$HOME/logs/$DEPLOY_NAME.log"

# Ensure uv is on PATH (not available in non-interactive shells unless sourced)
command -v uv &>/dev/null || . "$HOME/.local/bin/env"

# Load app config (.env must define PORT and SERVER_BASE_URL_PATH)
set -a
source "$SCRIPT_DIR/.env"
set +a

cd "$SCRIPT_DIR"
mkdir -p "$HOME/logs"

nohup uv run streamlit run app.py \
    --server.port "$PORT" \
    --server.baseUrlPath "$SERVER_BASE_URL_PATH" \
    --server.headless true \
    >> "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
echo "$DEPLOY_NAME started on :$PORT at $SERVER_BASE_URL_PATH — log: $LOG_FILE"
