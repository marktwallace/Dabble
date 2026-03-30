#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load app config for DABBLE_S3_BUCKET and DABBLE_S3_PREFIX
set -a
source "$SCRIPT_DIR/.env"
set +a

BUCKET="${DABBLE_S3_BUCKET:?DABBLE_S3_BUCKET not set in .env}"
PREFIX="${DABBLE_S3_PREFIX:?DABBLE_S3_PREFIX not set in .env}"
DATE=$(date +%Y-%m-%d)
S3_DEST="s3://${BUCKET}/${PREFIX}/knowledge/${DATE}/"
KNOWLEDGE_DIR="$SCRIPT_DIR/knowledge"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) Backing up $KNOWLEDGE_DIR to $S3_DEST"
aws s3 cp --recursive "$KNOWLEDGE_DIR" "$S3_DEST" --exclude ".gitkeep"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) Backup complete"
