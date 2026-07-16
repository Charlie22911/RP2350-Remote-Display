# Troubleshooting

## The board is not found on Linux

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

## The board is not found on native Windows

Native Windows hosting requires all of the following:

- 64-bit x86 Windows 11 (AMD64).
- Firmware release 1.2.18 or later compatible firmware.
- A matching Python package installation, which brings in `libusb-package` on Windows AMD64.

BOOTSEL mode and normal display mode are different USB devices. The BOOTSEL device appears as a removable drive; the normal firmware shows `WAITING FOR HOST` and should use Microsoft's WinUSB driver. In Device Manager, open the normal device's properties, confirm that the driver provider is Microsoft, and check that **Driver Details** lists `WinUSB.sys`. Do not use Zadig or install a custom INF for compatible firmware.

If older firmware was previously attached, flash matching 1.2.18-line firmware, let the board reboot, and physically reconnect it so Windows enumerates the new descriptors. If the device is attached to WSL, detach it before opening it natively:

```powershell
usbipd list
usbipd detach --busid <BUSID>
```

Close other applications that may have the display open. Windows and WSL cannot own the interface simultaneously. See the [Windows 11 guide](windows-11.md) for the complete native and WSL workflows.

## PyUSB cannot find a backend

On Linux, install the system libusb package. The bootstrap installs it on supported distributions. On another Linux distribution, install the package that provides the libusb-1.0 shared library and restart the Python environment.

On Windows AMD64, reinstall the project package dependencies and verify the packaged backend is present:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade -e .\python
.\.venv\Scripts\python.exe -m pip show libusb-package
```

The native backend is not currently packaged for Windows ARM64. A missing or unloaded backend is a Python installation problem; replacing the automatically selected WinUSB device driver is not the remedy.

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

On Windows, inspect the same values with:

```powershell
.\.venv-windows\Scripts\python.exe -c "import rp2350_remote_display as rpd; print(rpd.__version__); print(rpd.__file__)"
```

`run.ps1` uses `.venv-windows` by default. If `RPD_TEST_VENV` is set, run the check with the Python executable from that directory instead.

## Functional-test text layout differs

On Linux, the test prefers DejaVu Sans from normal system font locations; the bootstrap installs it on supported distributions. Install the distribution's DejaVu font package and rebuild the local environment when a text-layout preflight fails. On Windows, the test also checks Segoe UI and Arial from the Windows Fonts directory. A customized or incomplete font installation can still change text metrics, so review the selected system fonts when preflight fails.

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

RTC synchronization changes the board clock only. It does not update the Linux or Windows system clock.
