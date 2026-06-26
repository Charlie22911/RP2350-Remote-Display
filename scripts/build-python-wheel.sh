#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
DIST_DIR="$REPOSITORY_DIR/dist"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "Python was not found: $PYTHON_BIN" >&2
    exit 1
}

"$PYTHON_BIN" -m pip install --disable-pip-version-check --upgrade build
rm -rf "$DIST_DIR"
"$PYTHON_BIN" -m build --outdir "$DIST_DIR" "$REPOSITORY_DIR/python"
printf 'Built package artifacts in %s\n' "$DIST_DIR"
