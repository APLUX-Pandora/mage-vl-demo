#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "Missing .venv. Run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
    exit 2
fi
cd "$ROOT"

export PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON" -m demo.server "$@"
