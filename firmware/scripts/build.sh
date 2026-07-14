#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/build.sh [options]

Options:
  --sdk PATH          Path to the Raspberry Pi Pico SDK.
  --build-dir PATH    Build directory. Default: ./build
  --debug             Configure a Debug build. Default: Release
  --clean             Delete the selected build directory before configuring.
  --clock-khz VALUE   RP2350 system clock in kHz. Default: 250000
  --psram-max-sck-hz VALUE
                       Maximum requested PSRAM serial clock in Hz. Default: 133000000
  --vid VALUE         USB vendor ID as a C integer literal. Default: 0xCAFE
  --pid VALUE         USB product ID as a C integer literal. Default: 0x4010
  -h, --help          Show this help.

SDK lookup order:
  1. --sdk PATH
  2. PICO_SDK_PATH environment variable
  3. ../pico-sdk relative to this project
EOF
}

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$PROJECT_DIR/build"
SDK_PATH="${PICO_SDK_PATH:-}"
BUILD_TYPE="Release"
CLEAN=0
CLOCK_KHZ="250000"
PSRAM_MAX_SCK_HZ="133000000"
USB_VID="0xCAFE"
USB_PID="0x4010"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sdk)
            [[ $# -ge 2 ]] || { echo "--sdk requires a path." >&2; exit 2; }
            SDK_PATH="$2"
            shift 2
            ;;
        --build-dir)
            [[ $# -ge 2 ]] || { echo "--build-dir requires a path." >&2; exit 2; }
            BUILD_DIR="$2"
            shift 2
            ;;
        --debug)
            BUILD_TYPE="Debug"
            shift
            ;;
        --clean)
            CLEAN=1
            shift
            ;;
        --clock-khz)
            [[ $# -ge 2 ]] || { echo "--clock-khz requires a value." >&2; exit 2; }
            CLOCK_KHZ="$2"
            shift 2
            ;;
        --psram-max-sck-hz)
            [[ $# -ge 2 ]] || { echo "--psram-max-sck-hz requires a value." >&2; exit 2; }
            PSRAM_MAX_SCK_HZ="$2"
            shift 2
            ;;
        --vid)
            [[ $# -ge 2 ]] || { echo "--vid requires a value." >&2; exit 2; }
            USB_VID="$2"
            shift 2
            ;;
        --pid)
            [[ $# -ge 2 ]] || { echo "--pid requires a value." >&2; exit 2; }
            USB_PID="$2"
            shift 2
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

if [[ -z "$SDK_PATH" && -f "$PROJECT_DIR/../pico-sdk/pico_sdk_init.cmake" ]]; then
    SDK_PATH="$PROJECT_DIR/../pico-sdk"
fi

for command in cmake python3 arm-none-eabi-gcc; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Missing required command: $command" >&2
        exit 1
    }
done

[[ -n "$SDK_PATH" && -f "$SDK_PATH/pico_sdk_init.cmake" ]] || {
    echo "Raspberry Pi Pico SDK was not found." >&2
    echo "Pass --sdk PATH or export PICO_SDK_PATH=/path/to/pico-sdk." >&2
    exit 1
}

[[ -f "$SDK_PATH/lib/tinyusb/src/tusb.h" ]] || {
    echo "TinyUSB is missing from the Pico SDK at: $SDK_PATH" >&2
    echo "Run: git -C \"$SDK_PATH\" submodule update --init --depth 1 lib/tinyusb" >&2
    exit 1
}

if [[ "$CLEAN" -eq 1 ]]; then
    rm -rf "$BUILD_DIR"
fi

export PICO_SDK_PATH="$SDK_PATH"

cmake -S "$PROJECT_DIR" -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
    -DPICO_SDK_PATH="$PICO_SDK_PATH" \
    -DPICO_BOARD=waveshare_rp2350_touch_amoled_2.41 \
    -DRPD_SYS_CLOCK_KHZ="$CLOCK_KHZ" \
    -DRPD_PSRAM_MAX_SCK_HZ="$PSRAM_MAX_SCK_HZ" \
    -DRPD_USB_VID="$USB_VID" \
    -DRPD_USB_PID="$USB_PID"

cmake --build "$BUILD_DIR" --parallel

UF2="$BUILD_DIR/rp2350_remote_display.uf2"
[[ -f "$UF2" ]] || {
    echo "Build completed, but the expected UF2 was not found." >&2
    find "$BUILD_DIR" -type f -name '*.uf2' -print >&2
    exit 1
}

echo
echo "Build complete:"
echo "  $UF2"
