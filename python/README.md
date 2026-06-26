# Python library

`rp2350-remote-display` is the Linux host library for RP2350 Remote Display. It opens the board over USB, checks protocol compatibility, sends drawing commands, receives touch events, and provides helpers for images, text, caching, dirty updates, layout, diagnostics, and RTC access.

This checkout packages release **1.2.16** of the project and Python library. It requires firmware release **1.2.16**, which speaks USB **protocol 16**.

## Requirements

- Python 3.10 or newer.
- A board running compatible firmware.
- PyUSB and a system libusb backend.
- Linux USB permission to claim the vendor interface.

## Install from this repository

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./python"
```

For development dependencies and tests:

```bash
python -m pip install -e "./python[dev]"
python -m pytest python/tests
```

Install Linux USB access rules once per host:

```bash
./python/scripts/install_linux_udev_rule.sh
```

Log out and back in, then reconnect the board. The default development firmware uses `CAFE:4010`.

## Minimal application

```python
from rp2350_remote_display import RemoteDisplay, rgb565

BLACK = rgb565(0, 0, 0)
BLUE = rgb565(45, 110, 255)
WHITE = rgb565(255, 255, 255)

with RemoteDisplay.open() as display:
    display.set_brightness(65)

    with display.frame():
        display.clear(BLACK)
        display.fill_rect(24, 24, 402, 96, BLUE)
        display.draw_text("Hello, RP2350", 48, 62, WHITE, size=22)
```

Drawing methods run inside `display.frame()`. Connection, brightness, cache management, RTC operations, device-font inspection, and diagnostics run outside a frame.

## API overview

| Area | Main API |
|---|---|
| Connection | `RemoteDisplay.open()`, `ping()`, `DisplayInfo` |
| Frames and primitives | `frame()`, `clear()`, `fill_rect()`, `stroke_rect()`, `line()`, `polyline()` |
| Images | `draw_image()`, `blit_rgb565()`, `blit_alpha()`, `blit_palette4()`, `blit_palette64()` |
| Half-resolution image transport | `draw_image_scale2()`, `blit_rgb565_scale2()`, `blit_palette4_scale2()`, `blit_palette64_scale2()` |
| Text | `draw_text()`, `draw_text_box()`, `draw_device_text()`, `measure_device_text()` |
| Reused images | `cache_rgb565()`, `cache_alpha()`, `cache_palette4()`, `draw_cached()` |
| Host-composed updates | `Canvas`, `DirtyTilePresenter` |
| Framebuffer movement | `copy_rect()`, `scroll_rect()` |
| Touch | `poll_events()`, `poll_latest_touch()`, `wait_for_touch()` |
| Diagnostics | `canvas_crc32()`, `tile_transfer_stats` |
| RTC | `read_rtc()`, `set_rtc()`, `sync_rtc_from_ntp()` |

The exported `rgb565()` helper converts 8-bit RGB components to the 16-bit display format.

## Image modes and rendering choices

| Mode | Suitable use |
|---|---|
| RGB565 RAW | Exact full-color image data |
| RGB565 RLE | Flat graphics, repeated pixels, and simple UI art |
| RGB565 auto | Per-tile RAW or RLE selection |
| Alpha8 | Tinted masks and host-rendered text |
| Palette4 | Lower-bandwidth artwork that tolerates limited color detail |
| Palette64 | Better palette fidelity with lower bandwidth than RGB565 |
| Scale2 | Animated 225×300 source background expanded to 450×600 |

Palette4 and Palette64 are visually lossy. Their optional Floyd-Steinberg dithering changes source-to-palette mapping on the host. Use RGB565 when every output pixel must match the source.

Scale2 uses 2× nearest-neighbor expansion. Draw a changing Scale2 background first, then redraw full-resolution overlays that overlap it. Scale2 source tiles are direct transfers and cannot use the cache or `DirtyTilePresenter`.

For full-resolution scenes that change repeatedly, use `Canvas` plus `DirtyTilePresenter`. Use `region_mode="rect"` when small, sparse changes benefit from tighter lossless RGB565 rectangles. Tile profiles are 18×24, 30×40, and 45×60 pixels.

## Resource cache

The session-local resource cache is suited to repeated full-resolution icons, masks, sprites, and small panels. Upload a resource outside a frame with `cache_rgb565()`, `cache_alpha()`, or `cache_palette4()`, then replay it inside a frame with `draw_cached()`. A firmware reset or a new USB session clears the cache, so applications must upload their resources again.

The cache holds up to 64 resources and 256 KiB of combined encoded data. Use `resource_cache_info()` to inspect usage and `release_cached()` or `clear_cached()` to reclaim space. Scale2 transfers cannot use the cache.

## Canvas and dirty updates

`DirtyTilePresenter` compares each full-resolution RGB565 canvas with the preceding host canvas. Its first `present()` transfers the complete canvas; later calls transfer only changed tiles or changed rectangles. It does not infer framebuffer changes made through direct device commands.

Call `presenter.reset()` after any device-side framebuffer update that did not come from that presenter, including direct drawing frames, Scale2 updates, cached-resource draws, `copy_rect()`, and `scroll_rect()`. The next `present()` then sends the complete host canvas and restores the presenter's baseline.

## Device text

`draw_text()` renders a host font into Alpha8 tiles. `draw_device_text()` uses the firmware-resident Unifont grid. Device text is useful when an application needs firmware-provided glyph metrics and compact UTF-8 drawing without transferring a mask.

The built-in font uses an 8×16 base cell, with integer scales from 1 through 4. Most glyphs occupy one cell; full-width glyphs occupy two. `measure_device_text()` returns the exact result for mixed-width text. Newline starts at the original X position, tab advances to a four-cell stop, and unsupported code points render as `?`.

Query `device_font_info()` and `measure_device_text()` outside a frame before building layouts that depend on cell geometry.

## Device-side copy and scroll

`copy_rect()` and `scroll_rect()` move existing RGB565 pixels inside the device framebuffer and run inside `display.frame()`. Overlapping `copy_rect()` operations are safe. Positive scroll X moves pixels right, positive scroll Y moves pixels down, and `fill_color` fills newly exposed pixels.

```python
with display.frame():
    display.scroll_rect(24, 120, 360, 300, delta_x=0, delta_y=-16, fill_color=0x0000)
```

Mirror these operations with `Canvas.copy_rect()` or `Canvas.scroll_rect()` when a host `Canvas` must remain an exact model of the device framebuffer. Reset any associated `DirtyTilePresenter` before presenting the canvas again.

## Touch and RTC

Touch events report panel coordinates with a top-left origin. The firmware coalesces move events so `poll_latest_touch()` is appropriate for drag feedback.

RTC values are timezone-aware UTC. `sync_rtc_from_ntp()` performs one unauthenticated SNTP request from the host, writes the resulting UTC value to the board, and reads it back. It does not set the Linux system clock. Check `RtcReading.oscillator_valid` after a power-loss event.

## Examples

- `examples/basic_primitives.py`: primitives and host-rendered text.
- `examples/graphics_modes.py`: RGB565, palette, and image transfer modes.
- `examples/plasma_interactive.py`: transport comparison and Scale2 animation. Run `./python/examples/run_plasma_interactive.sh`; the program prints its controls at startup.
- `examples/dirty_dashboard.py`: `Canvas` and `DirtyTilePresenter`.
- `examples/resource_cache.py`: cached full-resolution resources.
- `examples/scrolling_log.py`: `scroll_rect()`.
- `examples/device_text.py`: firmware-resident text.
- `examples/touch_canvas.py`: touch input.
- `examples/layout_debug.py`: layout and diagnostic overlays.
- `examples/rtc_sync.py`: read, write, and NTP RTC synchronization.

## Related documentation

- [User guide](../docs/README.md)
- [Protocol reference](../docs/protocol.md)
- [Testing guide](../docs/testing.md)
- [Troubleshooting](../docs/troubleshooting.md)

## License

MIT. See [LICENSE](LICENSE).
