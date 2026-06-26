#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${RPD_VERIFY_VENV:-$REPOSITORY_DIR/.venv}"
PYTHON_BIN="${PYTHON:-python3}"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "Python was not found: $PYTHON_BIN" >&2
    exit 1
}

"$PYTHON_BIN" "$REPOSITORY_DIR/scripts/check-version-consistency.py"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --upgrade -e "$REPOSITORY_DIR/python[dev]"
"$VENV_DIR/bin/python" -m pytest "$REPOSITORY_DIR/python/tests"
"$VENV_DIR/bin/python" "$REPOSITORY_DIR/firmware/tests/test_unifont_asset.py"
RPD_TEST_VENV="$VENV_DIR" "$REPOSITORY_DIR/functional-test/run.sh" --preflight-only


if command -v gcc >/dev/null 2>&1; then
    RENDERER_HARNESS="$REPOSITORY_DIR/firmware/tests/renderer_copy_scroll_harness.c"
    RENDERER_HARNESS_BIN="$(mktemp)"
    FONT_HARNESS="$REPOSITORY_DIR/firmware/tests/builtin_font_asset_harness.c"
    FONT_HARNESS_BIN="$(mktemp)"
    FONT_ASM="$(mktemp --suffix=.S)"
    RTC_HARNESS="$REPOSITORY_DIR/firmware/tests/rtc_pcf85063_harness.c"
    RTC_HARNESS_BIN="$(mktemp)"
    trap 'rm -f "$RENDERER_HARNESS_BIN" "$FONT_HARNESS_BIN" "$RTC_HARNESS_BIN" "$FONT_ASM"' EXIT

    gcc -std=c11 -Wall -Wextra -Werror \
        -I"$REPOSITORY_DIR/firmware/tests/mocks" \
        -I"$REPOSITORY_DIR/firmware/firmware" \
        "$RENDERER_HARNESS" -o "$RENDERER_HARNESS_BIN"
    "$RENDERER_HARNESS_BIN"

    sed "s#@RPD_UNIFONT_ASM_PATH@#$REPOSITORY_DIR/firmware/assets/unifont_all-17.0.04.bin#g" \
        "$REPOSITORY_DIR/firmware/firmware/builtin_font_data.S.in" > "$FONT_ASM"
    gcc -std=c11 -Wall -Wextra -Werror \
        -I"$REPOSITORY_DIR/firmware/firmware" \
        "$REPOSITORY_DIR/firmware/firmware/builtin_font.c" \
        "$FONT_ASM" \
        "$FONT_HARNESS" \
        -o "$FONT_HARNESS_BIN"
    "$FONT_HARNESS_BIN"

    gcc -std=c11 -Wall -Wextra -Werror \
        -I"$REPOSITORY_DIR/firmware/tests/mocks" \
        -I"$REPOSITORY_DIR/firmware/firmware" \
        "$REPOSITORY_DIR/firmware/firmware/rtc_pcf85063.c" \
        "$RTC_HARNESS" \
        -o "$RTC_HARNESS_BIN"
    "$RTC_HARNESS_BIN"
fi
