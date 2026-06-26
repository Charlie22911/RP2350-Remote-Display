#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: install_linux_udev_rule.sh [--user USER] [--group GROUP]

Installs Linux udev access for RP2350 Remote Display development firmware.
Defaults: current user, rp2350-display group.
EOF
}

TARGET_USER="${SUDO_USER:-${USER}}"
TARGET_GROUP="rp2350-display"
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RULE_SOURCE="$ROOT_DIR/udev/60-rp2350-remote-display.rules"
RULE_DEST="/etc/udev/rules.d/60-rp2350-remote-display.rules"

while (($#)); do
    case "$1" in
        --user)
            TARGET_USER="${2:?--user requires a value}"
            shift 2
            ;;
        --group)
            TARGET_GROUP="${2:?--group requires a value}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

[[ -f "$RULE_SOURCE" ]] || { echo "Missing rule: $RULE_SOURCE" >&2; exit 1; }
id "$TARGET_USER" >/dev/null 2>&1 || { echo "Unknown user: $TARGET_USER" >&2; exit 1; }

if ! getent group "$TARGET_GROUP" >/dev/null 2>&1; then
    sudo groupadd --system "$TARGET_GROUP" 2>/dev/null || sudo groupadd "$TARGET_GROUP"
fi

sudo usermod -aG "$TARGET_GROUP" "$TARGET_USER"
sudo install -Dm644 "$RULE_SOURCE" "$RULE_DEST"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb
sudo udevadm settle

echo "Installed: $RULE_DEST"
echo "Added $TARGET_USER to group $TARGET_GROUP"
echo "Log out and back in, then reconnect the board."
