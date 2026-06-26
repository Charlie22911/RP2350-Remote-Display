#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PACKAGE_DIR="$REPOSITORY_DIR/python"
VENV_DIR="${RPD_TEST_VENV:-$REPOSITORY_DIR/.venv}"
PYTHON_BIN="${PYTHON:-python3}"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "Python was not found: $PYTHON_BIN" >&2
    exit 1
}

[[ -f "$PACKAGE_DIR/pyproject.toml" ]] || {
    echo "Python package source is missing: $PACKAGE_DIR" >&2
    exit 1
}

REPOSITORY_VERSION_FILE="$REPOSITORY_DIR/VERSION"
FUNCTIONAL_TEST_VERSION_FILE="$PROJECT_DIR/VERSION"
[[ -f "$REPOSITORY_VERSION_FILE" && -f "$FUNCTIONAL_TEST_VERSION_FILE" ]] || {
    echo "Release version metadata is missing." >&2
    exit 1
}
REPOSITORY_VERSION="$(tr -d '[:space:]' < "$REPOSITORY_VERSION_FILE")"
FUNCTIONAL_TEST_VERSION="$(tr -d '[:space:]' < "$FUNCTIONAL_TEST_VERSION_FILE")"
[[ "$REPOSITORY_VERSION" == "$FUNCTIONAL_TEST_VERSION" ]] || {
    echo "Functional-test version ($FUNCTIONAL_TEST_VERSION) does not match repository version ($REPOSITORY_VERSION)." >&2
    exit 1
}

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --upgrade --editable "$PACKAGE_DIR"

RPD_EXPECTED_VERSION="$REPOSITORY_VERSION" "$VENV_DIR/bin/python" - <<'PYCHECK'
import os
import rp2350_remote_display as rpd

expected = os.environ["RPD_EXPECTED_VERSION"]
assert rpd.__version__ == expected, (rpd.__version__, expected)
print(f"Installed rp2350-remote-display {rpd.__version__} from this repository")
PYCHECK
