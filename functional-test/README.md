# Functional test

The functional test validates the complete host-to-board path using the local Python package and a physical RP2350 Remote Display board. It supports Linux and native Windows 11 AMD64 and is intended for firmware builds, protocol work, rendering changes, USB backend changes, and release verification. Use the same firmware image for both host operating systems.

For repository-wide validation and detailed result interpretation, see [docs/testing.md](../docs/testing.md).

## Run

From the repository root on Linux:

```bash
./functional-test/run.sh --preflight-only
./functional-test/run.sh
```

On native Windows, use the PowerShell runner. It creates or reuses `.venv-windows`, installs the local package, and checks that its version matches the repository:

```powershell
.\functional-test\run.ps1 --preflight-only
.\functional-test\run.ps1 --report .\functional-test\reports\windows-native.json
```

Compatible firmware binds automatically to Windows' inbox WinUSB driver, and the Python installation brings in the packaged libusb backend on AMD64. Keep the display detached from WSL during a native run because the two environments cannot own the USB interface simultaneously.

The preflight does not open a USB device. It verifies scene geometry, text-layout assumptions, the reference image, and palette-dither behavior.

The full run validates protocol negotiation, display control, primitives, device text, lossless RGB565 image paths, palette paths, Scale2 presentation, resource caching, copy and scroll operations, dirty updates, touch feedback, and diagnostics.

Useful options:

```bash
./functional-test/run.sh --quick
./functional-test/run.sh --skip-touch
./functional-test/run.sh --skip-strict-crc
./functional-test/run.sh --report ./functional-test/reports/validation.json
```

The PowerShell runner accepts the same flags on Windows and forwards them to the Python program. It also accepts `--vid` and `--pid` with decimal or `0x`-prefixed values for a custom USB identity.

## Validation classes

RGB565 RAW and RLE stages use exact framebuffer CRC checks. Palette4, Palette64, and palette Scale2 stages are intentionally lossy, so they require successful transfer and visual inspection. The test does not alter RTC state.

The Linux `run.sh` launcher installs the package from `../python` into `.venv` by default. The Windows `run.ps1` launcher uses `.venv-windows`. Set `RPD_TEST_VENV` to make either launcher use another environment directory.

## Assets and notices

The reference image is checked for expected dimensions, RGB mode, and SHA-256 before USB access. Its separate licensing notice is in [NOTICE.md](NOTICE.md).
