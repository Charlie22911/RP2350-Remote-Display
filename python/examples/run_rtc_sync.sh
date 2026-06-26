#!/usr/bin/env bash
set -Eeuo pipefail

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_DIR="$(cd "$EXAMPLE_DIR/../.." && pwd)"
VENV_DIR="${RPD_TEST_VENV:-$REPOSITORY_DIR/.venv}"

bash "$REPOSITORY_DIR/functional-test/scripts/setup.sh"
exec "$VENV_DIR/bin/python" "$EXAMPLE_DIR/rtc_sync.py" "$@"
