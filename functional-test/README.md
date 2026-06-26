# Functional test

The functional test validates the complete Linux-host-to-board path using the local Python package and a physical RP2350 Remote Display board. It is intended for firmware builds, protocol work, rendering changes, and release verification.

For repository-wide validation and detailed result interpretation, see [docs/testing.md](../docs/testing.md).

## Run

From the repository root:

```bash
./functional-test/run.sh --preflight-only
./functional-test/run.sh
```

The preflight does not open a USB device. It verifies scene geometry, text-layout assumptions, the reference image, and palette-dither behavior.

The full run validates protocol negotiation, display control, primitives, device text, lossless RGB565 image paths, palette paths, Scale2 presentation, resource caching, copy and scroll operations, dirty updates, touch feedback, and diagnostics.

Useful options:

```bash
./functional-test/run.sh --quick
./functional-test/run.sh --skip-touch
./functional-test/run.sh --skip-strict-crc
./functional-test/run.sh --report ./functional-test/reports/validation.json
```

## Validation classes

RGB565 RAW and RLE stages use exact framebuffer CRC checks. Palette4, Palette64, and palette Scale2 stages are intentionally lossy, so they require successful transfer and visual inspection. The test does not alter RTC state.

The test runner installs the package from `../python` into `.venv` by default. Set `RPD_TEST_VENV` to use a separate environment.

## Assets and notices

The reference image is checked for expected dimensions, RGB mode, and SHA-256 before USB access. Its separate licensing notice is in [NOTICE.md](NOTICE.md).
