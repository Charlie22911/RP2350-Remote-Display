# Troubleshooting

## The board is not found

Confirm that the board has normal firmware, is connected by USB, and has rebooted after leaving BOOTSEL mode:

```bash
lsusb -d cafe:4010
```

The default development identity is `CAFE:4010`. A custom firmware build can use different values. Check the values passed to the firmware build and the matching udev rule.

## Linux reports access denied

Install the supplied rule, log out and back in, then reconnect the board:

```bash
./python/scripts/install_linux_udev_rule.sh
```

The command adds the selected user to the `rp2350-display` group. A newly added group does not apply to an existing login session.

## Windows cannot open the normal firmware device

Native Windows host operation is not currently supported. The vendor-specific normal-firmware interface does not automatically bind to WinUSB, and the project does not install or validate a native libusb backend. Do not confuse this with BOOTSEL mode, which appears as a normal removable drive and can be used directly from Windows.

Use the experimental WSL 2 forwarding workflow in the [Windows 11 guide](windows-11.md). If the device disappears after a reset or unplug, run `usbipd list` and attach its current bus ID again.

## PyUSB cannot find a backend

Install the system libusb package. The bootstrap installs it on supported distributions. On another Linux distribution, install the package that provides the libusb-1.0 shared library and restart the Python environment.

## Connection fails with a protocol mismatch

The host and board must both use protocol 16. Build and flash the firmware from the same repository revision as the Python package when changing protocol-dependent features.

A `HELLO` failure with status `3` usually indicates that one side is using a different protocol version. The source-of-truth constants are:

```text
firmware/firmware/remote_protocol.h
python/src/rp2350_remote_display/protocol.py
```

## Firmware build cannot find the Pico SDK

Pass the SDK path directly:

```bash
./firmware/scripts/build.sh --clean --sdk /path/to/pico-sdk
```

The SDK must contain `pico_sdk_init.cmake` and the TinyUSB dependency. For a Git checkout of the SDK:

```bash
git -C /path/to/pico-sdk submodule update --init --depth 1 lib/tinyusb
```

## A Scale2 image looks blocky

Scale2 expands every source pixel into a 2×2 destination block. A 225×300 source fills the 450×600 panel. Use a full-resolution RGB565 path when image detail matters more than transfer reduction.

Dithered Palette4 and Palette64 Scale2 output can show an intentional 2×2 dither pattern because dithering happens before the expansion.

## Text or icons disappear after a Scale2 update

Scale2 writes into the only device framebuffer. Draw the Scale2 background first, then redraw every full-resolution overlay that overlaps it in the same frame.

## Palette output is posterized

Palette4 and Palette64 intentionally reduce color detail. Palette64 preserves more tonal detail than Palette4. Use RGB565 RAW or RLE when the output must match source pixels exactly.

## Functional-test setup uses the wrong package

The functional-test runner installs the local `python/` package into the selected virtual environment. Check the active import path:

```bash
.venv/bin/python - <<'PY'
import rp2350_remote_display as rpd
print(rpd.__version__)
print(rpd.__file__)
PY
```

The module path should point into the repository being tested. Remove the project-local `.venv` and rerun the test setup if the environment came from a different checkout.

## Functional-test text layout differs

The test expects DejaVu Sans from normal Linux font locations. The bootstrap installs it on supported distributions. Install the distribution's DejaVu font package and rebuild the local environment when a text-layout preflight fails.

## The firmware is unstable at the default clock

The default build intentionally uses a 250 MHz RP2350 system clock and a 133 MHz maximum requested PSRAM serial clock; the divider produces about 125 MHz PSRAM SCK. Use the conservative profile when diagnosing a board-specific stability issue:

```bash
./firmware/scripts/build.sh --clean \
  --clock-khz 150000 \
  --psram-max-sck-hz 109000000 \
  --sdk /path/to/pico-sdk
```

## RTC is unavailable or reports invalid time

RTC support appears only when the PCF85063 responds during firmware startup. Read `RtcReading.oscillator_valid` before trusting the value. A false value can follow loss of valid RTC power. Set the clock from a trusted UTC source with `set_rtc()` or `sync_rtc_from_ntp()`, then read it back.

RTC synchronization changes the board clock only. It does not update the Linux system clock.
