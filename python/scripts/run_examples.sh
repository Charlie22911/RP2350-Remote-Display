#!/usr/bin/env bash
# Interactive launcher for the RP2350 Remote Display Python examples.

set -uo pipefail

usage() {
    cat <<'USAGE'
Usage: ./python/scripts/run_examples.sh

Start an interactive menu for the Python examples. The launcher finds the
repository relative to its own location, creates the repository-local Python
virtual environment when needed, installs the local package in editable mode,
and returns to the menu after each example finishes.

Environment:
  PYTHON    Python interpreter used to create a new virtual environment.
            Default: python3
  RPD_VENV  Virtual-environment directory. Default: .venv at repository root
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPOSITORY_DIR="$(cd "$PYTHON_DIR/.." && pwd)"
EXAMPLES_DIR="$PYTHON_DIR/examples"
VENV_DIR="${RPD_VENV:-$REPOSITORY_DIR/.venv}"
BOOTSTRAP_PYTHON="${PYTHON:-python3}"
VENV_PYTHON="$VENV_DIR/bin/python"
CHILD_RUNNING=0

on_exit() {
    local status=$?
    if (( status == 0 )); then
        printf '\nExample launcher closed.\n'
    fi
}

on_interrupt() {
    if (( CHILD_RUNNING )); then
        printf '\nInterrupt received. Waiting for the running example to stop...\n' >&2
        return
    fi
    printf '\nInterrupted. Closing example launcher.\n' >&2
    exit 130
}

trap on_exit EXIT
trap on_interrupt INT TERM

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
    usage
    exit 0
fi

if [[ $# -ne 0 ]]; then
    printf 'This launcher is interactive and does not accept example arguments.\n' >&2
    usage >&2
    exit 2
fi

[[ -f "$REPOSITORY_DIR/VERSION" && -f "$PYTHON_DIR/pyproject.toml" ]] || {
    printf 'Could not locate an RP2350 Remote Display repository from: %s\n' "$SCRIPT_DIR" >&2
    exit 1
}

ensure_environment() {
    command -v "$BOOTSTRAP_PYTHON" >/dev/null 2>&1 || {
        printf 'Python was not found: %s\n' "$BOOTSTRAP_PYTHON" >&2
        return 1
    }

    if [[ ! -x "$VENV_PYTHON" ]]; then
        printf 'Creating Python environment: %s\n' "$VENV_DIR"
        "$BOOTSTRAP_PYTHON" -m venv "$VENV_DIR" || return 1
    fi

    printf 'Preparing local Python package...\n'
    "$VENV_PYTHON" -m pip install --disable-pip-version-check --editable "$PYTHON_DIR" || return 1
}

pause_after_example() {
    if ! IFS= read -r -p 'Press Enter to return to the menu... ' _; then
        printf '\nInput closed. Closing example launcher.\n'
        exit 0
    fi
}

run_example() {
    local title=$1
    shift

    printf '\n=== %s ===\n' "$title"
    printf 'Press Ctrl+C to stop this example and return to the menu.\n\n'

    CHILD_RUNNING=1
    "$VENV_PYTHON" "$@"
    local status=$?
    CHILD_RUNNING=0

    case "$status" in
        0)
            printf '\nExample completed.\n'
            ;;
        130)
            printf '\nExample interrupted.\n'
            ;;
        *)
            printf '\nExample exited with status %s.\n' "$status" >&2
            ;;
    esac

    pause_after_example
}

sync_rtc() {
    local server answer

    if ! IFS= read -r -p 'NTP server [time.cloudflare.com]: ' server; then
        printf '\nInput closed. Returning to menu.\n'
        return
    fi
    server=${server:-time.cloudflare.com}

    if ! IFS= read -r -p "Synchronize the board RTC from ${server}? [y/N]: " answer; then
        printf '\nInput closed. Returning to menu.\n'
        return
    fi
    case "$answer" in
        y|Y|yes|YES|Yes)
            run_example "RTC synchronization" "$EXAMPLES_DIR/rtc_sync.py" --sync-ntp --server "$server"
            ;;
        *)
            printf 'RTC synchronization cancelled.\n'
            ;;
    esac
}

print_menu() {
    cat <<'MENU'

RP2350 Remote Display examples
==============================
  1) Basic primitives
  2) Graphics transfer modes
  3) Interactive plasma benchmark
  4) System dashboard
  5) Resource cache
  6) Scrolling log
  7) Device text
  8) Touch canvas
  9) Layout diagnostics
 10) Read board RTC
 11) Synchronize board RTC from NTP

  0) Exit
MENU
}

ensure_environment || exit 1

while :; do
    print_menu
    if ! IFS= read -r -p 'Select an example: ' selection; then
        printf '\nInput closed. Closing example launcher.\n'
        break
    fi

    case "$selection" in
        1)
            run_example "Basic primitives" "$EXAMPLES_DIR/basic_primitives.py"
            ;;
        2)
            run_example "Graphics transfer modes" "$EXAMPLES_DIR/graphics_modes.py"
            ;;
        3)
            run_example "Interactive plasma benchmark" "$EXAMPLES_DIR/plasma_interactive.py"
            ;;
        4)
            run_example "System dashboard" "$EXAMPLES_DIR/dirty_dashboard.py"
            ;;
        5)
            run_example "Resource cache" "$EXAMPLES_DIR/resource_cache.py"
            ;;
        6)
            run_example "Scrolling log" "$EXAMPLES_DIR/scrolling_log.py"
            ;;
        7)
            run_example "Device text" "$EXAMPLES_DIR/device_text.py"
            ;;
        8)
            run_example "Touch canvas" "$EXAMPLES_DIR/touch_canvas.py"
            ;;
        9)
            run_example "Layout diagnostics" "$EXAMPLES_DIR/layout_debug.py"
            ;;
        10)
            run_example "Read board RTC" "$EXAMPLES_DIR/rtc_sync.py" --read
            ;;
        11)
            sync_rtc
            ;;
        0|q|Q|quit|QUIT|Quit|exit|EXIT|Exit)
            break
            ;;
        '')
            ;;
        *)
            printf 'Choose a number from the menu.\n' >&2
            ;;
    esac
done
