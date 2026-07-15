# Security policy

## Supported versions

Security fixes are developed on `main` and released in the newest available project version. Older prereleases are not maintained separately. Reproduce a report with matching firmware and Python package versions from the same release or checkout whenever possible.

## Report a vulnerability

Use GitHub's private vulnerability reporting flow at [Report a vulnerability](https://github.com/Charlie22911/RP2350-Remote-Display/security/advisories/new). Include the affected commit or release, hardware revision, host operating system, impact, reproduction steps, and any proposed mitigation.

If private reporting is unavailable, open a minimal issue asking the maintainer to establish a private contact channel. Do not include exploit details, private data, device identifiers, or secrets in a public issue.

## Security boundaries

- The display protocol is designed for a directly connected USB device. It does not authenticate or encrypt commands. Grant USB interface access only to trusted local users and applications.
- USB interface ownership is exclusive. On Windows, attaching the display to WSL transfers it away from native Windows applications; close or detach one owner before allowing the other to control the display.
- Development firmware uses the shared prototype identity `0xCAFE:0x4010`. Its per-board USB serial supports deterministic selection but is not an authentication credential; neither value proves that a connected device is genuine.
- `sync_rtc_from_ntp()` uses unauthenticated SNTP. Use it only with a trusted network and time source when time integrity matters.
- Published SHA-256 values detect accidental corruption or an artifact that differs from the release record. They do not by themselves authenticate the publisher.
- BOOTSEL flashing replaces device firmware. Verify the source and checksum of a UF2 before copying it to the board.

Please avoid testing availability failures against equipment or systems you do not own or have permission to test.
