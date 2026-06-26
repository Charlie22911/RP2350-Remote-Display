# Testing and validation

The repository separates source checks from board validation. Run both when changing firmware, protocol behavior, display rendering, touch handling, or USB transport.

## Repository verification

From the repository root:

```bash
./scripts/verify.sh
```

This creates or reuses `.venv`, installs the Python package with development dependencies, runs Python unit tests, validates the built-in font asset, runs the functional-test preflight, and executes available native harnesses.

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

Run the full hardware test:

```bash
./functional-test/run.sh
```

Useful options:

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

Static scenes remain visible for five seconds by default. The touch stage invites interaction for twelve seconds. Use `--quick` or `--skip-touch` when an unattended run is needed.

## How results are checked

| Path | Validation |
|---|---|
| RGB565 RAW and RLE | Exact device framebuffer CRC compared with the host RGB565 canvas |
| Copy, scroll, and selected diagnostic paths | Exact framebuffer CRC compared with a host canvas mirror |
| Palette4 and Palette64 | Successful transfer plus visual inspection; palette conversion is intentionally lossy |
| Palette4 and Palette64 Scale2 | Successful transfer plus visual inspection of the expanded output |
| Touch and dynamic presentation | Interactive observation and explicit protocol assertions |

For a future exact Scale2 check, construct the expected 450×600 destination after source-domain quantization and 2× expansion. Comparing a 225×300 source CRC directly with the display framebuffer is invalid.

The test leaves the board RTC unchanged. Use the RTC examples or host API when RTC behavior needs separate validation.

## Test assets and reports

The functional test verifies the reference image's dimensions, RGB mode, and SHA-256 before contacting the board. Its licensing notice is in `functional-test/NOTICE.md`.

A JSON report records stage results, duration, transfer measurements, negotiated protocol data, and selected CRC values. It provides a record of the run. It does not replace visual inspection for lossy palette or Scale2 stages.
