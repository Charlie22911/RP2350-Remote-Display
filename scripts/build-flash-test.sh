#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/build-flash-test.sh [options] [-- functional-test-options]

Build the firmware, wait for a confirmed BOOTSEL flash, then run the hardware
functional test. The confirmation is read from /dev/tty, so it still waits when
this runner is started from a pasted Bash here-document.

Options:
  --sdk PATH          Path to the Raspberry Pi Pico SDK.
  --no-clean          Reuse the existing firmware build directory.
  -h, --help          Show this help.

Everything after -- is passed to functional-test/run.sh.
EOF
}

REPOSITORY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_PATH="${PICO_SDK_PATH:-$HOME/src/pico-sdk}"
CLEAN=1
TEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sdk)
            [[ $# -ge 2 ]] || { echo "--sdk requires a path." >&2; exit 2; }
            SDK_PATH="$2"
            shift 2
            ;;
        --no-clean)
            CLEAN=0
            shift
            ;;
        --)
            shift
            TEST_ARGS=("$@")
            break
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

BUILD_ARGS=(--sdk "$SDK_PATH")
if [[ "$CLEAN" -eq 1 ]]; then
    BUILD_ARGS+=(--clean)
fi

"$REPOSITORY_DIR/firmware/scripts/build.sh" "${BUILD_ARGS[@]}"

UF2="$REPOSITORY_DIR/firmware/build/rp2350_remote_display.uf2"
[[ -f "$UF2" ]] || {
    echo "Expected UF2 was not produced: $UF2" >&2
    exit 1
}

[[ -r /dev/tty && -w /dev/tty ]] || {
    echo "An interactive terminal is required to confirm the BOOTSEL flash." >&2
    exit 1
}

{
    echo
    echo "Flash this UF2 while the RP2350 is in BOOTSEL mode:"
    echo "  $UF2"
    echo
    printf 'After the file copy has completed and the board has rebooted normally, press Enter to start the functional test: '
} > /dev/tty
IFS= read -r _ < /dev/tty

exec "$REPOSITORY_DIR/functional-test/run.sh" "${TEST_ARGS[@]}"
