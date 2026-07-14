## Unreleased

- Identifies post-1.2.16 development builds as `1.2.17.dev0` instead of reusing the published release version.
- Adds Python 3.14 and Windows-safe package/unit-test coverage while retaining Linux as the supported direct-USB host.
- Documents native Windows BOOTSEL flashing and the experimental WSL 2 USB-forwarding path.
- Preserves the 250 MHz system-clock and approximately 125 MHz PSRAM performance profile while exposing documented system-clock and PSRAM-ceiling build overrides.
- Makes allocator startup null-safe, rejects allocation-size overflow, bounds PSRAM QMI waits, and starts watchdog coverage earlier in boot.
- Clips line and polyline geometry before rendering and enforces thickness and raster-work budgets on both host and firmware.
- Quiesces active display presentation during recovery, adds staged-transfer expiry, and reserves reply-queue capacity under USB bursts.
- Advertises touch only after successful initialization, suppresses transient I²C failures, clears a stuck press after sustained failure, and resynchronizes held contacts after a new session.
- Adds Palette64 resource caching with encoded-index validation on both sides of the protocol.
- Adds a stable per-board USB serial number and host selection by serial number, bus, or address.
- Matches replies and errors by sequence, quarantines late responses, bounds pending/event queues, and adds `recover_session()` with explicit resource-cache invalidation.
- Normalizes PyUSB failures into the public transport exception hierarchy while preserving the original error during cleanup.
- Validates the complete `HELLO_REPLY`, enforces incoming CRC in strict mode, and aligns ping and primitive limits with firmware.
- Hardens NTP synchronization with peer validation, monotonic timing, era unfolding, and a configurable plausibility bound.
- Pins CI actions and the Pico SDK, runs every hardware-independent harness in CI, and builds and installs distributions on Linux and Windows.

## 1.2.16

- Updated the interactive plasma demo with complete visible controls, larger spatial forms, and a muted high-contrast cyclic colour gradient.
- Kept live full-resolution and half-resolution scale2 operation, palette-mode selection, and dithering controls unchanged.
- Reworked `examples/dirty_dashboard.py` as a Pico-rendered Linux system dashboard using Pico primitives, the firmware-resident font, touch navigation, declared incremental-update regions, and Pico framebuffer graph scrolling.
- Added dashboard configuration for network interface, disk target, update rate, and history range.

## 1.2.15

- Updated the interactive plasma example to support a live half-resolution scale2 toggle.
- Added a half-resolution startup option and live status reporting for scale2 mode.

## 1.2.13

- Corrected the bundled hardware functional-test setup version assertion.
- No protocol or firmware behavior change.

## 1.2.12

- Fixed the firmware build for Palette64 scale2 by including the missing on-device Palette64 scale2 decoder.
- No protocol or host API changes.

## 1.2.11

- Added Palette64 scale2 tiles for half-resolution source images upscaled 2x on the Pico.
- Added `RemoteDisplay.blit_palette64_scale2()` and Palette64 support in `RemoteDisplay.draw_image_scale2()`.
- Added the `CAP_PALETTE64_SCALE2` protocol capability and protocol version 16.

## 1.2.10

- Added Palette4 scale2 tiles for half-resolution source images upscaled 2x on the Pico.
- Added `RemoteDisplay.blit_palette4_scale2()` and Palette4 support in `RemoteDisplay.draw_image_scale2()`.
- Added the `CAP_PALETTE4_SCALE2` protocol capability and protocol version 15.

## 1.2.9

- Added RGB565 scale2 tiles for half-resolution source images that are upscaled 2x on the Pico.
- Added `RemoteDisplay.blit_rgb565_scale2()` and `RemoteDisplay.draw_image_scale2()`.
- Added the `CAP_RGB565_SCALE2` protocol capability and protocol version 14.

# Release Notes

## 1.2.8

- Targets protocol 13.
- Adds PCF85063 board RTC reads and UTC calendar writes.
- Adds host-side unauthenticated NTP synchronization through `sync_rtc_from_ntp()`.

## 1.2.5

- Adds Palette64 transfer support with local 1–64 RGB565 palettes and LSB-first packed six-bit indices.
- Adds `draw_image(..., compression="palette64")` and `blit_palette64(...)`.
- Targets protocol 12.

## 1.2.3

- Targets protocol 11, which expands the device-font information reply to use a 32-bit glyph count.
- Supports GNU Unifont 17.0.04 device-font metrics, including mixed one-cell and two-cell glyph advances.

## 1.2.2

- Restored the functional-test bouncing-ball scene to whole-tile RGB565 presentation.
- Preserved the fixed-palette Floyd-Steinberg conversion and protocol 10 compatibility.

## 1.2.1

- Restores reliable Floyd-Steinberg Palette4 conversion by creating the shared Median Cut palette once, then mapping the original RGB source through that fixed palette.
- Keeps no-dither Palette4 on the established direct Median Cut baseline.
- Adds an output-level regression test that requires Floyd-Steinberg to change the rendered Palette4 RGB565 result.

## 1.2.0

- Bumps the host protocol target to version 10.
- Adds `copy_rect()` and `scroll_rect()` for lossless Pico framebuffer movement.
- Adds `Canvas.copy_rect()` and `Canvas.scroll_rect()` as host-side mirrors for CRC checks and deterministic composition.
- Adds optional `DirtyTilePresenter(region_mode="rect")` for lossless changed sub-rectangles inside each changed tile.
- Retains the existing tile-wide dirty mode as the default.

## 1.1.0

- Bumps the host protocol target to version 9.
- Adds `device_font_info()`, `measure_device_text()`, and `draw_device_text()`.
- Adds support for firmware-resident UTF-8 bitmap text with scale 1 through 4.
- Exports `DeviceFontInfo` and `DeviceTextMetrics` from the public package API.
