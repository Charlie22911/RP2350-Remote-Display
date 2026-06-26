#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_GROUP="rp2350-display"
RULE_DEST="/etc/udev/rules.d/60-rp2350-remote-display.rules"

while (($#)); do
    case "$1" in
        --group)
            TARGET_GROUP="${2:?--group requires a value}"
            shift 2
            ;;
        -h|--help)
            echo "Usage: uninstall_linux_udev_rule.sh [--group GROUP]"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

sudo rm -f "$RULE_DEST"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb
sudo udevadm settle

echo "Removed: $RULE_DEST"
echo "The $TARGET_GROUP group and any user memberships were retained. Remove them manually if no longer needed."
