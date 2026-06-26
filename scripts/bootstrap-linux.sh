#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'USAGE'
Usage: scripts/bootstrap-linux.sh [options]

Prepare a Linux development host for RP2350 Remote Display.

Options:
  --sdk PATH               Raspberry Pi Pico SDK location. Default: $HOME/src/pico-sdk
  --skip-system-packages   Do not install Linux packages.
  --skip-firmware-build    Do not build the UF2 image.
  --skip-udev              Do not install the development USB udev rule.
  -h, --help               Show this help.

Supported package managers:
  apt-get  Debian and Ubuntu
  pacman   Arch Linux and CachyOS
USAGE
}

REPOSITORY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_PATH="${RPD_PICO_SDK_DIR:-$HOME/src/pico-sdk}"
PICO_SDK_TAG="${RPD_PICO_SDK_TAG:-2.2.0}"
PICO_SDK_REPOSITORY="https://github.com/raspberrypi/pico-sdk.git"
INSTALL_SYSTEM_PACKAGES=1
BUILD_FIRMWARE=1
INSTALL_UDEV=1

while (($#)); do
    case "$1" in
        --sdk)
            [[ $# -ge 2 ]] || { echo "--sdk requires a path." >&2; exit 2; }
            SDK_PATH="$2"
            shift 2
            ;;
        --skip-system-packages)
            INSTALL_SYSTEM_PACKAGES=0
            shift
            ;;
        --skip-firmware-build)
            BUILD_FIRMWARE=0
            shift
            ;;
        --skip-udev)
            INSTALL_UDEV=0
            shift
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

[[ "$(uname -s)" == "Linux" ]] || {
    echo "This bootstrap script requires Linux." >&2
    exit 1
}

install_system_packages() {
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo env DEBIAN_FRONTEND=noninteractive apt-get install --yes \
            build-essential \
            cmake \
            ninja-build \
            git \
            python3 \
            python3-pip \
            python3-venv \
            gcc-arm-none-eabi \
            libnewlib-arm-none-eabi \
            libstdc++-arm-none-eabi-newlib \
            libusb-1.0-0 \
            libusb-1.0-0-dev \
            fonts-dejavu-core \
            fontconfig
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -Syu --needed --noconfirm \
            base-devel \
            cmake \
            ninja \
            git \
            python \
            python-pip \
            arm-none-eabi-gcc \
            arm-none-eabi-newlib \
            libusb \
            ttf-dejavu \
            fontconfig
    else
        echo "Unsupported Linux package manager." >&2
        echo "Install git, CMake, a native C/C++ toolchain, Python 3 with venv, libusb, DejaVu Sans, arm-none-eabi-gcc, and Arm newlib, then re-run with --skip-system-packages." >&2
        exit 1
    fi
}

prepare_pico_sdk() {
    if [[ ! -f "$SDK_PATH/pico_sdk_init.cmake" ]]; then
        if [[ -e "$SDK_PATH" ]]; then
            echo "The Pico SDK path exists but is incomplete: $SDK_PATH" >&2
            echo "Remove that partial directory or choose a different SDK path with --sdk PATH." >&2
            exit 1
        fi

        mkdir -p "$(dirname "$SDK_PATH")"
        echo "Fetching Pico SDK $PICO_SDK_TAG as a shallow checkout..."
        git clone \
            --depth 1 \
            --single-branch \
            --branch "$PICO_SDK_TAG" \
            "$PICO_SDK_REPOSITORY" \
            "$SDK_PATH"
    fi

    if [[ ! -f "$SDK_PATH/lib/tinyusb/src/tusb.h" ]]; then
        [[ -d "$SDK_PATH/.git" ]] || {
            echo "TinyUSB is missing from SDK path: $SDK_PATH" >&2
            echo "Use a Git checkout of the Pico SDK, or provide one with lib/tinyusb already initialized." >&2
            exit 1
        }
        echo "Fetching the required TinyUSB submodule as a shallow checkout..."
        git -C "$SDK_PATH" submodule update --init --depth 1 lib/tinyusb
    fi
}

if [[ "$INSTALL_SYSTEM_PACKAGES" -eq 1 ]]; then
    install_system_packages
    if command -v fc-cache >/dev/null 2>&1; then
        fc-cache -f >/dev/null 2>&1 || true
    fi
fi

required_commands=(python3)
if [[ "$BUILD_FIRMWARE" -eq 1 ]]; then
    required_commands+=(git cmake arm-none-eabi-gcc)
fi
for command in "${required_commands[@]}"; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Missing required command after setup: $command" >&2
        exit 1
    }
done

if [[ "$BUILD_FIRMWARE" -eq 1 ]]; then
    prepare_pico_sdk
    "$REPOSITORY_DIR/firmware/scripts/build.sh" --sdk "$SDK_PATH" --clean
fi

if [[ "$INSTALL_UDEV" -eq 1 ]]; then
    "$REPOSITORY_DIR/python/scripts/install_linux_udev_rule.sh"
fi

VENV_DIR="$REPOSITORY_DIR/.venv"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --upgrade pip
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --editable "$REPOSITORY_DIR/python[dev]"
"$REPOSITORY_DIR/functional-test/run.sh" --preflight-only

echo
echo "Linux setup completed."
if [[ "$BUILD_FIRMWARE" -eq 1 ]]; then
    echo "Flash this UF2 while the board is in BOOTSEL mode:"
    echo "  $REPOSITORY_DIR/firmware/build/rp2350_remote_display.uf2"
fi
if [[ "$INSTALL_UDEV" -eq 1 ]]; then
    echo "Log out and back in so the rp2350-display group takes effect, then reconnect the board."
fi
echo "Run the complete hardware validation from the repository root:"
echo "  ./functional-test/run.sh"
