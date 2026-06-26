#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Setting up scaleswe_gen ==="

# 1. Python venv
if [ ! -d "$PROJECT_ROOT/.venv" ]; then
    echo "Creating Python venv..."
    python3 -m venv "$PROJECT_ROOT/.venv"
fi

source "$PROJECT_ROOT/.venv/bin/activate"

# 2. Install Python deps
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r "$PROJECT_ROOT/requirements.txt"

# 3. Build base Docker image
echo "Building base Docker image..."
bash "$SCRIPT_DIR/build_base_image.sh"

# 4. Check env vars
if [ -z "$GLM_API_KEY" ]; then
    echo "WARNING: GLM_API_KEY not set. Set it before running the orchestrator."
    echo "  export GLM_API_KEY=your-key-here"
fi

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Start vLLM serving GLM-5.2-fp8 on localhost:8080"
echo "  2. source .venv/bin/activate"
echo "  3. python scripts/orchestrate.py --help"
