# Testing and validation

The repository separates source checks from board validation. Run both when changing firmware, protocol behavior, display rendering, touch handling, or USB transport. Changes to USB descriptors, discovery, or packaged backends require physical regression runs on both Linux and native Windows using the same firmware image.

## Repository verification

From the repository root on Linux:

```bash
./scripts/verify.sh
```

This creates or reuses `.venv`, installs the Python package with development dependencies, runs Python unit tests, validates the built-in font asset, runs the functional-test preflight, and executes available native harnesses.

Continuous integration runs the Python unit suite on Linux with Python 3.10 through 3.14 and on Windows with Python 3.14. A separate Linux job runs this complete verification script, including the renderer, built-in-font, RTC, and USB-descriptor native harnesses. Wheel and source-distribution builds are installed on both Linux and Windows. These CI jobs are hardware-independent; native WinUSB support is validated separately on a physical Windows 11 AMD64 host.

For the equivalent Windows unit-test and functional-test preflight from PowerShell:

```powershell
py -3 -m venv .venv-windows
.\.venv-windows\Scripts\python.exe -m pip install --upgrade -e ".\python[dev]"
.\.venv-windows\Scripts\python.exe -m pytest .\python\tests
.\functional-test\run.ps1 --preflight-only
```

The Windows package installation automatically installs `libusb-package` on AMD64. It does not install a custom device driver; compatible firmware advertises WinUSB and Windows selects its inbox driver.

Build the Python distribution when preparing a package artifact:

```bash
./scripts/build-python-wheel.sh
```

## Firmware build

Build from a clean firmware directory when changing firmware, board support, or build configuration:

```bash
./firmware/scripts/build.sh --clean --sdk /path/to/pico-sdk
```

The expected output is:

```text
firmware/build/rp2350_remote_display.uf2
```

See [firmware/README.md](../firmware/README.md) for BOOTSEL flashing and supported build options.

## Functional test

The functional test exercises the installed Python package against a physical board. It includes session recovery, display control, primitives, device text, RGB565 image paths, palette image paths, Scale2 presentation, resource cache behavior, framebuffer copy and scroll, dirty updates, touch feedback, and diagnostics.

Run the preflight without opening the board:

```bash
./functional-test/run.sh --preflight-only
```

Run the full hardware test on Linux:

```bash
./functional-test/run.sh
```

Run the same test from native Windows PowerShell. The runner creates or reuses `.venv-windows`, installs the local package, and verifies its version before testing:

```powershell
.\functional-test\run.ps1 --report .\functional-test\reports\windows-native.json
```

Use firmware from the same release or checkout for both runs. Before a native Windows run, detach the device from WSL; before a WSL run, close the native process and attach the device to WSL. Windows and WSL cannot claim the display simultaneously.

Useful Linux options:

```bash
# Shorter visual holds and interactive stages.
./functional-test/run.sh --quick

# Omit the interactive touch stage.
./functional-test/run.sh --skip-touch

# Omit optional strict packet and tile CRC validation.
./functional-test/run.sh --skip-strict-crc

# Choose a report path.
./functional-test/run.sh --report ./functional-test/reports/validation.json
```

The PowerShell runner accepts the same options on Windows and forwards them to the Python program. It also accepts `--vid` and `--pid` with decimal or `0x`-prefixed values when validating a custom USB identity. Set `RPD_TEST_VENV` to reuse another virtual-environment directory.

Static scenes remain visible for five seconds by default. The touch stage invites interaction for twelve seconds. Use `--quick` or `--skip-touch` when an unattended run is needed.

## How results are checked

| Path | Validation |
|---|---|
| RGB565 RAW and RLE | Exact device framebuffer CRC compared with the host RGB565 canvas |
| Copy, scroll, and selected diagnostic paths | Exact framebuffer CRC compared with a host canvas mirror |
| Palette4 and Palette64 | Successful transfer plus visual inspection; palette conversion is intentionally lossy |
| Palette4 and Palette64 Scale2 | Successful transfer plus visual inspection of the expanded output |
| Touch and dynamic presentation | Interactive observation and explicit protocol assertions |

Comparing a 225×300 source CRC directly with the 2× scaled display framebuffer is invalid because the device expands every source pixel.

## Test assets and reports

The functional test verifies the reference image's dimensions, RGB mode, and SHA-256 before contacting the board. On Linux it prefers DejaVu Sans; on Windows it can use Segoe UI or Arial when DejaVu Sans is unavailable. Its licensing notice is in `functional-test/NOTICE.md`.

A JSON report records the project version, tested USB VID/PID, stage results, duration, transfer measurements, negotiated protocol data, and selected CRC values. It provides a record of the run. It does not replace visual inspection for lossy palette or Scale2 stages.
