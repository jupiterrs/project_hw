#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Building scaleswe-base Docker image ==="
docker build -t scaleswe-base:latest "$PROJECT_ROOT/base_image/"
echo "=== Done. Image: scaleswe-base:latest ==="
