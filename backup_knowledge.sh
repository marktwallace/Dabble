#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load app config for DABBLE_S3_BUCKET and DABBLE_KNOWLEDGE_S3_PREFIX (or DABBLE_S3_PREFIX)
set -a
source "$SCRIPT_DIR/.env"
set +a

BUCKET="${DABBLE_S3_BUCKET:?DABBLE_S3_BUCKET not set in .env}"
if [[ -n "${DABBLE_KNOWLEDGE_S3_PREFIX:-}" ]]; then
    PREFIX="${DABBLE_KNOWLEDGE_S3_PREFIX%/}"
else
    PREFIX="${DABBLE_S3_PREFIX:?DABBLE_S3_PREFIX not set in .env}/knowledge"
fi
DATE=$(date +%Y-%m-%d)
S3_DEST="s3://${BUCKET}/${PREFIX}/${DATE}/"
KNOWLEDGE_DIR="$SCRIPT_DIR/knowledge"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) Backing up $KNOWLEDGE_DIR to $S3_DEST"
aws s3 cp --recursive "$KNOWLEDGE_DIR" "$S3_DEST" --exclude ".gitkeep"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) Backup complete"
