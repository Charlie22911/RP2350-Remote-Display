# Functional-test release notes

## Unreleased

- Tracks the `1.2.18.dev0` development package and stabilization work after the 1.2.16 release.
- Supports physical native Windows validation through the packaged libusb backend while retaining the Linux runner and the same firmware image.
- Adds a PowerShell setup/runner, Windows system-font fallbacks, and configurable `--vid` and `--pid` selection for native or custom-identity hardware runs.
- Records the project version and tested USB identity in JSON reports.
- Runs the complete hardware-independent verification set in continuous integration.

## 1.2.16

- Updates functional-test metadata for the repository Python package and protocol 16.
- Updates the reference image used by image-transport validation.

## 1.2.13

- Corrected the bundled functional-test setup assertion so it accepts the package version shipped with this repository.
- Firmware protocol remains 16; no firmware behavior changed.

## 1.2.8

- Updates the bundled host package target to protocol 13.
- RTC state is deliberately not changed by automated functional-test scenes.

## 1.2.5

- Adds Palette64 no-dither and Floyd-Steinberg image stages.
- Requires the Palette64 capability.

## 1.2.4

- Reworks only the `COPY + SCROLL` stage into three held, visually distinct states: initial layout, non-overlapping pixel copy, and inner-work-area scroll.
- Verifies device framebuffer CRC after the initial transfer, after `COPY_RECT`, and after `SCROLL_RECT`.
- Removes the unrelated sub-tile dirty-region claim from this stage.

## 1.2.3

- Updates the device-text stage for the full GNU Unifont 17.0.04 grid font.
- Verifies narrow-cell, full-width-cell, multiline, and fallback measurements without rendering emoji in the test scene.

## 1.2.2

- Restored the bouncing-ball stage to the known-good whole-tile dirty presenter.
- Brightness remains a dynamic sweep.

## 1.2.1

- Restores the brightness sweep to a dynamic 0.45-second maximum dwell per level, independent of static scene hold time.
- Adds a reference-image Palette4 preflight that fails before USB traffic if Floyd-Steinberg renders identically to no-dither.
- Uses the same medium tile profile for the two Palette4 comparison stages.

## 1.2.0

- Renders and CRC-verifies Pico framebuffer `COPY_RECT` and `SCROLL_RECT` operations.
- Retains whole-tile dirty presentation as the bouncing-ball baseline.
