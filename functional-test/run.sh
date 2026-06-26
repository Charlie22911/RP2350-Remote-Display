#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
VENV_DIR="${RPD_TEST_VENV:-$REPOSITORY_DIR/.venv}"
PYTHON_BIN="$VENV_DIR/bin/python"

bash "$PROJECT_DIR/scripts/setup.sh"

exec "$PYTHON_BIN" "$PROJECT_DIR/functional_test.py" "$@"
